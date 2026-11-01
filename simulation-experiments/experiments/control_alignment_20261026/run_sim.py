"""One 1kHz free-space control-alignment smoke in the existing full workcell."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from challenge2.jacob_control.bridge import SharedStack
from challenge2.jacob_control.executor import JointExecutor
from challenge2.jacob_control.native import NativeLimiter
from challenge2.jacob_control.isaac_io import IsaacIO,transform
from experiments.control_alignment_20261026.phase_a import common_metadata,write


class ControlOnlyComplete(Exception):pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    from isaaclab.app import AppLauncher
    AppLauncher.add_app_launcher_args(parser);args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or not args.enable_cameras:raise RuntimeError('Default Pueue and existing camera-enabled runtime required')
    out=args.output;out.mkdir(parents=True,exist_ok=True);(out/'images').mkdir(exist_ok=True);(out/'evaluation_truth').mkdir(exist_ok=True)
    teaching=ROOT/'vendor/jacob_teaching/teaching';catalog=json.loads((teaching/'positions.json').read_text());point=catalog['points']['point_03']
    config=json.loads((teaching/'motion_config.json').read_text());app=AppLauncher(args).app
    from experiments.final_workcell_20261024 import scene as scene_module,render_core
    from isaaclab import scene as scene_package
    from pxr import UsdPhysics,PhysxSchema
    from isaaclab.sim import get_current_stage
    factory=scene_module.make_env_cfg;initializer=scene_package.InteractiveScene.__init__
    def construct(scene,cfg):
        initializer(scene,cfg)
        # Reuse the reviewed custom BODY/head collision authoring; no contact tuning.
        from experiments.stage2_pick_20261025.tool_model import Tool
        tool=Tool(out);tool.author(get_current_stage(),scene,out)
        for prim in get_current_stage().GetPrimAtPath('/World/envs/env_0/Robot').GetChildren():
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr(0.)
    def make_cfg(cfg,capture=False):
        env=factory(cfg,capture=capture);env.sim.dt=.001;env.sim.physx.solver_type=0;env.sim.render_interval=1000
        env.scene.robot.spawn.activate_contact_sensors=True
        positions=env.scene.robot.init_state.joint_pos
        for i,q in enumerate(point['q_rad'],1):positions[f'fr3_joint{i}']=q
        positions.pop('fr3_finger_joint.*',None)
        for i in (1,2):positions[f'fr3_finger_joint{i}']=.01
        return env
    scene_module.make_env_cfg=make_cfg;scene_package.InteractiveScene.__init__=construct
    def smoke(**context):
        from bricksim.core import compute_connected_component
        from omni.physx import get_physx_simulation_interface
        from pxr import PhysicsSchemaTools
        sim,scene,robot=context['sim'],context['scene'],context['robot'];stage=get_current_stage()
        # Track observed external robot contacts; fixed/self contacts are separate.
        contact={'points':0,'errors':[]};robot_prefix='/World/envs/env_0/Robot/'
        def report(headers,data):
            try:
                for h in headers:
                    a=str(PhysicsSchemaTools.intToSdfPath(h.actor0));b=str(PhysicsSchemaTools.intToSdfPath(h.actor1))
                    if a.startswith(robot_prefix)!=b.startswith(robot_prefix):contact['points']+=int(h.num_contact_data)
            except Exception as error:contact['errors'].append(str(error))
        subscription=get_physx_simulation_interface().subscribe_contact_report_events(report)
        def joint_frame(name):
            path='/World/envs/env_0/Robot/'+('fr3_link8/' if name=='fr3_hand_joint' else 'fr3_link'+str(int(name.removeprefix('fr3_joint'))-1)+'/')+name
            j=UsdPhysics.Joint(stage.GetPrimAtPath(path))
            if not j:raise RuntimeError('Expected actual asset joint missing: '+path)
            p0,p1=j.GetLocalPos0Attr().Get(),j.GetLocalPos1Attr().Get();q0,q1=j.GetLocalRot0Attr().Get(),j.GetLocalRot1Attr().Get()
            t0=transform(list(p0),[q0.GetReal(),*q0.GetImaginary()]);t1=transform(list(p1),[q1.GetReal(),*q1.GetImaginary()])
            return {'name':name,'path':path,'T_parent_joint':t0.tolist(),'T_child_joint':t1.tolist(),'parent':list(map(str,j.GetBody0Rel().GetTargets())),'child':list(map(str,j.GetBody1Rel().GetTargets()))}
        chain=[joint_frame(f'fr3_joint{i}') for i in range(1,8)];hand=joint_frame('fr3_hand_joint')
        flange_hand=np.asarray(hand['T_parent_joint'])@np.linalg.inv(np.asarray(hand['T_child_joint']))
        source='/World/envs/env_0/plate_source';parts,connections=compute_connected_component(source);initial_graph=(set(parts),set(connections))
        if len(parts)!=301 or len(connections)!=930:raise RuntimeError('Full300 native preassembly missing')
        names=sorted(name for name in scene.rigid_objects if name.startswith('brick_'))
        if len(names)!=300:raise RuntimeError('Full300 source required')
        from experiments.control_alignment_20261026.batched_source import BatchedSourcePoses,SourcePoseEquivalenceError
        proof_clock=float(sim.current_time)
        try:reader=BatchedSourcePoses(scene,names)
        except SourcePoseEquivalenceError as error:
            write(out/'source_pose_getter_failure.json',{'reason':str(error),'control_started':False,
                'proof':{**error.proof,'clock_before_s':proof_clock,'clock_after_s':float(sim.current_time)}})
            raise
        reader.proof.update(clock_before_s=proof_clock,clock_after_s=float(sim.current_time))
        source_poses=reader.read
        initial=source_poses();write(out/'source_initial.json',{'names':names,'poses_world_wxyz':initial.tolist(),'native_parts':list(map(str,parts)),'native_connections':list(map(str,connections))})
        recorded=[];graph=[];point_counts=[];times=[];initial_time=float(sim.current_time)
        def observe():
            p,c=compute_connected_component(source);graph.append([len(p),len(c),int(set(p)==initial_graph[0] and set(c)==initial_graph[1])]);recorded.append(source_poses())
            point_counts.append(contact['points']);contact['points']=0;times.append(float(sim.current_time))
        io=IsaacIO(sim,scene,robot,point['tool_frames']['F_T_EE'],flange_hand,None,watchdog=observe)
        limiter=NativeLimiter(ROOT/'native/libjoint_limiter.so',teaching/'robot_model.urdf');executor=JointExecutor(io,limiter,ROOT/'native/joint_check',out)
        with SharedStack(teaching,executor,source_manifest=teaching.parent/'SOURCE.json') as shared:
            io.model=shared.modules['kinematics'].Kinematics(point['tool_frames']['F_T_EE'],config['singularity_avoidance'])
            state=io.read_state();model=io.model.fk(state['q']).homogeneous;actual=np.asarray(state['O_T_EE']).reshape(4,4,order='F')
            fidelity={'position_error_m':float(np.linalg.norm(model[:3,3]-actual[:3,3])),
                'orientation_error_rad':float(Rotation.from_matrix(model[:3,:3].T@actual[:3,:3]).magnitude()),
                'scope':'Actual base-relative Isaac hand/configuredEE versus real exported model at measured q'}
            if fidelity['position_error_m']>.0001 or fidelity['orientation_error_rad']>.001:raise RuntimeError('Actual Isaac/real-model frame mismatch')
            width=shared.command_width('release')  # NOOP20; unknown is_grasped does not authorize approach.
            move=shared.move('3',relative_z_mm=1) if width==0 else 1
            values=np.asarray(recorded);g=np.asarray(graph)
            np.savez(out/'source_evaluation.npz',positions_world_m=values[:,:,:3],quaternions_wxyz=values[:,:,3:],native_parts_count=g[:,0],native_connections_count=g[:,1],native_graph_unchanged=g[:,2],robot_external_contact_points=np.asarray(point_counts),time_s=np.asarray(times))
            common_metadata(ROOT,out,executor,io,'B',{'move_returncode':move,'width_returncode':width,'model_fidelity':fidelity,
                'api_compatibility':shared.compatibility,'joint_names':[robot.joint_names[i] for i in io.arm],'root_world_transform':state['T_world_root'],
                'io_provenance':io.provenance,'actual_asset_chain':chain,'actual_hand_joint':hand,
                'actual_joint_position_limits_rad':robot.data.joint_pos_limits[0,io.arm].cpu().numpy().tolist(),
                'source_pose_getter_proof':reader.proof,'source_trace_file':'source_evaluation.npz','source_initial_file':'source_initial.json','contact_callback_errors':contact['errors'],
                'simulation_steps_observed':len(recorded),'initial_time_s':initial_time,'final_time_s':float(sim.current_time),'gripper_move_calls':io.width_commands,
                'post_initialization_pose_writes':0,'native_initial_parts':301,'native_initial_connections':930,
                'full_geometry':'300 bricks,10 layers,6 ridgesx5 per layer; unchanged native preassembly',
                'physics':{'dt_s':.001,'solver':'PGS','arm_servo':'existing implicit PD400/80 with model gravity compensation; not Franka embedded impedance'},
                'object_target_reference_registration':'UNVERIFIED; free-space control smoke only'})
            if move or width:raise RuntimeError('Shared command smoke failed; no retry')
        subscription=None
        write(out/'run_complete.json',{'completed':True,'phase':'B','shared_vendor_controls_exercised':['release20_NOOP','relative_up1mm'],'hardware_commands':0})
        raise ControlOnlyComplete()
    try:
        cameras=json.loads((ROOT/'experiments/final_workcell_20261024/end_effector/cameras.json').read_text())
        spec,bricks=render_core.load_geometry(ROOT/'experiments/final_workcell_20261024/geometry.json')
        args.appearance=ROOT/'experiments/final_workcell_20261024/appearance/materials.json'
        if not args.appearance.exists():args.appearance=None
        args.geometry=ROOT/'experiments/final_workcell_20261024/geometry.json';args.case_metadata=None
        # render() stops at its existing postassembly hook; no appearance/camera tuning.
        render_core.render(app,args,spec,bricks,cameras,[],postassembly_hook=smoke)
        raise RuntimeError('Control-only completion marker missing')
    except ControlOnlyComplete:pass
    except BaseException as error:
        write(out/'failure.json',{'type':type(error).__name__,'reason':str(error),'traceback':traceback.format_exc()});raise
    finally:
        scene_module.make_env_cfg=factory;scene_package.InteractiveScene.__init__=initializer;app.close(wait_for_replicator=False)


if __name__=='__main__':main()

"""One pre-reset staging posture and unchanged sensor-clearance diagnostic."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
ROOT = STAGE.parents[1]
sys.path[:0] = [str(STAGE), str(ROOT), str(ROOT/'experiments/stage2_contact_20261025'),
               str(ROOT/'experiments/stage2_idle_20261025')]
from controller import Controller
from run_pick import interpolate, qangle
from sensors import Sensors
from tool_model import Tool
from experiments.stage2_exposed_tip_20261025.model import save
from kinematics import derive


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    for key in ('output','geometry','cameras'):
        parser.add_argument('--'+key,type=Path,required=True)
    args,remaining = parser.parse_known_args()
    output = args.output.resolve();output.mkdir(exist_ok=True)
    (output/'online').mkdir();(output/'evaluation_truth').mkdir()
    sys.argv=[sys.argv[0],*remaining,'--output',str(output),'--geometry',str(args.geometry),
              '--cameras',str(args.cameras)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':
        raise RuntimeError('Default Pueue and frozen numerical configuration required')
    init=json.loads((HERE/'protocol.json').read_text())
    science=json.loads((STAGE/'protocol.json').read_text())
    if sha(STAGE/'protocol.json')!=init['existing_scientific_protocol_sha256']:
        raise RuntimeError('Scientific baseline changed')
    nominal=json.loads((HERE/'inputs/nominal_proprioception.json').read_text())
    from experiments.final_workcell_20261024 import scene as final_scene,render_core
    original_factory=final_scene.make_env_cfg
    original_init=None;derivation=None
    tool=Tool(output)

    def construct(scene,cfg):
        nonlocal derivation
        from isaaclab.sim import get_current_stage
        from pxr import PhysxSchema
        original_init(scene,cfg)
        stage=get_current_stage();tool.author(stage,scene,output)
        for label in ('left','right'):
            PhysxSchema.PhysxContactReportAPI.Apply(stage.GetPrimAtPath('/World/envs/env_0/Robot/fr3_'+label+'finger')).CreateThresholdAttr(0.)
        spec=tool.cfg['scene_fingertip_spec']
        q=.008+science['motion']['preopen_per_side_m']-(spec['stock_pad_backplane_abs_finger_y_m']+spec['body_mount_cad_x_mm']*.001)
        positions=scene['robot'].cfg.init_state.joint_pos
        positions.pop('fr3_finger_joint.*',None)
        positions.update(fr3_finger_joint1=q,fr3_finger_joint2=q)
        # USD exists, articulation lazy initialization/reset has not run yet.
        derivation=derive(stage,scene['robot'],science,init,nominal,output)
        for name,value in zip(derivation['joint_names'],derivation['q']):
            if name not in positions:
                raise RuntimeError('Expected explicit stock arm initialization key: '+name)
            positions[name]=float(value)

    def factory(cfg,capture=False):
        nonlocal original_init
        from isaaclab import scene as module
        from isaacsim.core.utils.extensions import enable_extension
        if not enable_extension('omni.isaac.dynamic_control'):
            raise RuntimeError('Installed property getter unavailable')
        env=original_factory(cfg,capture=capture);before=env.sim.to_dict()
        env.sim.physx.solver_type=0;env.sim.enable_scene_query_support=True
        if env.sim.to_dict()!={**before,'physx':{**before['physx'],'solver_type':0},'enable_scene_query_support':True}:
            raise RuntimeError('Unexpected physics configuration change')
        original_init=module.InteractiveScene.__init__
        module.InteractiveScene.__init__=construct
        return env

    def run(**context):
        from scipy.spatial.transform import Rotation
        from bricksim.core import compute_connected_component
        sim,scene,robot=context['sim'],context['scene'],context['robot']
        tool.validate(context)
        controller=Controller(robot,science);initial=controller.state()
        save(output/'initial_proprioception.json',initial)
        clock=float(sim.current_time)
        sensors=Sensors(sim,scene,args.geometry,args.cameras,output,science)
        candidates,frame=sensors.select(initial['tcp_pose_table_wxyz'])
        selection={**frame,'candidate':None,'diagnostic_only':True,
                   'candidate_under_test_is_not_pick_authorization':True,
                   'supported_upper_surface_m':None,'local_depth_support':{'supported':False},
                   'clearance':{'passed':False},'geometry_views':sensors.geometry_views,
                   'geometry_safety_config_sha256':sensors.safety_config_sha256}
        reason='no_present_candidate'
        if candidates:
            candidate=candidates[0];selection['candidate']=candidate
            height,support=sensors.local_height(candidate)
            selection.update(supported_upper_surface_m=height,local_depth_support=support)
            reason='unsupported_local_height'
            if height is not None:
                # Identical target/path construction to the frozen run_pick.py.
                current_pose=np.asarray(initial['tcp_pose_table_wxyz'])
                current_rotation=Rotation.from_quat(current_pose[3:][[1,2,3,0]]).as_matrix()
                parts=[];current_parts=[]
                for label,finger in tool.geometry['fingers'].items():
                    fp=np.asarray(initial['finger_poses_world_wxyz'][label]);fr=Rotation.from_quat(fp[3:][[1,2,3,0]]).as_matrix()
                    for collider in finger['colliders']:
                        world=np.asarray(collider['points_finger_m'])@fr.T+fp[:3]
                        current_parts.append(world);parts.append((world-current_pose[:3])@current_rotation)
                yaw=candidate['yaw_table_rad'];x=np.array([math.cos(yaw),math.sin(yaw),0]);z=np.array([0,0,-1.]);y=np.cross(z,x)
                rotation=np.column_stack((x,y,z));quat=Rotation.from_matrix(rotation).as_quat()[[3,0,1,2]]
                metal_delta=science['tool_frames']['metal_distal_hand_z_m']-science['tool_frames']['T_hand_grip_translation_m'][2]
                xyz=np.r_[candidate['table_xy_m'],height+.003]-rotation@np.array([0,0,metal_delta]);goal=np.r_[xyz,quat]
                tip_offset=.0584+tool.cfg['scene_fingertip_spec']['distal_tip_finger_z_m']-science['tool_frames']['T_hand_grip_translation_m'][2]
                overlap=(height-.0017)-(xyz[2]+(rotation@np.array([0,0,tip_offset]))[2])
                selection['nominal_body_side_overlap_m']=float(overlap)
                if overlap>=.002:
                    hover=goal.copy();hover[2]+=.010;path=[]
                    for a,b in ((current_pose,hover),(hover,goal)):
                        n=max(1,math.ceil(np.linalg.norm(b[:3]-a[:3])/.002),math.ceil(qangle(a[3:],b[3:])/math.radians(1)))
                        path.extend(interpolate(a,b,k/n) for k in range(n+1))
                    selection['clearance']=sensors.clearance(path,parts,current_parts)
                    selection['target_pose_table_wxyz']=goal.tolist()
                    reason='sensor_clearance_passed' if selection['clearance']['passed'] else 'unsupported_swept_envelope'
                else:
                    reason='insufficient_nominal_side_overlap'
        save(output/'online/selection.json',selection)
        end=float(sim.current_time)
        metadata={'initial_proprioception':initial,'geometry_safety_config_sha256':sensors.safety_config_sha256,
                  'geometry_views_file':'online/geometry_views.json','initial_time_s':clock,'terminal_time_s':end,
                  'post_native_physics_steps':int(round((end-clock)/sim.get_physics_dt())),
                  'diagnostic_protocol_sha256':sha(HERE/'protocol.json'),'science_sha256':sha(STAGE/'protocol.json')}
        save(output/'diagnostic_metadata.json',metadata)
        parts,edges=compute_connected_component('/World/envs/env_0/plate_source')
        save(output/'evaluation_truth/graph.json',{'parts':sorted(map(str,parts)),
             'connections':sorted(map(repr,edges)),'part_count':len(parts),'edge_count':len(edges)})
        if end!=clock:
            raise RuntimeError('Diagnostic advanced post-native physics')
        save(output/'diagnostic_complete.json',{'capture_completed':True,'reason':reason,
             'candidate_tested':selection['candidate']['candidate_id'] if selection['candidate'] else None,
             'sensor_clearance_passed':selection['clearance']['passed'],'post_native_physics_steps':0,
             'initial_time_s':clock,'terminal_time_s':end,'no_motion':True})

    final_scene.make_env_cfg=factory
    render_core.main(postassembly_hook=run)


if __name__=='__main__':
    main()

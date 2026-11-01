"""Three fixed sensing fixtures; no robot trajectory or grasp retry."""
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
from scipy.spatial.transform import Rotation

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];STAGE=ROOT/'experiments/stage2_pick_20261025'
sys.path[:0]=[str(HERE),str(STAGE),str(ROOT),str(ROOT/'experiments/stage2_contact_20261025'),str(ROOT/'experiments/stage2_idle_20261025')]
from experiments.stage2_exposed_tip_20261025.model import save,sha
from experiments.stage2_contact_20261025.geometry import distance_to_triangles
from tool_model import Tool
from recording import Recorder,settings,observer_module
from controller import Controller
from native_observer import NativeObserver

COUPON='/World/envs/env_0/contact_coupon'


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    for key in ('output','geometry','cameras'):parser.add_argument('--'+key,type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve();output.mkdir(exist_ok=True)
    sys.argv=[sys.argv[0],*remaining,'--output',str(output),'--geometry',str(args.geometry),'--cameras',str(args.cameras)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':raise RuntimeError('Frozen Pueue/epsilon required')
    protocol=json.loads((HERE/'protocol.json').read_text());science=json.loads((STAGE/'protocol.json').read_text())
    if protocol['execution_authorized'] is not True:raise RuntimeError('Probe execution not authorized')
    tool=Tool(output)
    from experiments.final_workcell_20261024 import scene as final_scene,render_core
    original_factory=final_scene.make_env_cfg;original_init=None
    def construct(scene,cfg):
        from isaaclab.sim import get_current_stage
        from pxr import PhysxSchema
        original_init(scene,cfg);stage=get_current_stage();tool.author(stage,scene,output)
        for path in ('/World/envs/env_0/Robot/fr3_leftfinger','/World/envs/env_0/Robot/fr3_rightfinger',COUPON):PhysxSchema.PhysxContactReportAPI.Apply(stage.GetPrimAtPath(path)).CreateThresholdAttr(0.)
    def factory(cfg,capture=False):
        nonlocal original_init
        from isaaclab import scene as module
        from isaaclab.assets import RigidObjectCfg
        from isaaclab.sim import CuboidCfg,RigidBodyPropertiesCfg,CollisionPropertiesCfg,MassPropertiesCfg
        from isaacsim.core.utils.extensions import enable_extension
        if not enable_extension('omni.isaac.dynamic_control'):raise RuntimeError('Installed property getter unavailable')
        env=original_factory(cfg,capture=capture);before=env.sim.to_dict();env.sim.physx.solver_type=0;env.sim.enable_scene_query_support=True
        if env.sim.to_dict()!={**before,'physx':{**before['physx'],'solver_type':0},'enable_scene_query_support':True}:raise RuntimeError('Unexpected sim change')
        env.scene.contact_coupon=RigidObjectCfg(prim_path=COUPON,spawn=CuboidCfg(size=(protocol['probe_size_m'],)*3,
            rigid_props=RigidBodyPropertiesCfg(kinematic_enabled=True,disable_gravity=True),
            collision_props=CollisionPropertiesCfg(),mass_props=MassPropertiesCfg(mass=.001)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(2.,2.,.5)))
        original_init=module.InteractiveScene.__init__;module.InteractiveScene.__init__=construct
        return env
    def run(**context):
        import torch
        from isaaclab.sim import get_current_stage
        from pxr import PhysxSchema
        import bricksim.core as core
        sim,scene,robot=context['sim'],context['scene'],context['robot'];dt=sim.get_physics_dt();stage=get_current_stage()
        if dt!=protocol['physics_dt_s']:raise RuntimeError('Unexpected dt')
        tool.validate(context);control=Controller(robot,science);initial=control.state();q0=np.asarray(initial['q']);coupon=scene['contact_coupon']
        recorder=Recorder(context,output,'I');recorder.stationary=True
        if len(recorder.ids)!=301 or len(recorder.edges)!=930:raise RuntimeError('Full source inventory differs')
        geometry=tool.geometry;role_paths={c['path']:{'side':s,'role':c['role']} for s,f in geometry['fingers'].items() for c in f['colliders']}
        actor_sides={f['body_path']:s for s,f in geometry['fingers'].items()}
        pose=np.asarray(initial['finger_poses_world_wxyz']['left']);pose[3:]/=np.linalg.norm(pose[3:]);rotation=Rotation.from_quat(pose[3:][[1,2,3,0]]).as_matrix()
        if coupon.root_physx_view.count!=1 or list(coupon.root_physx_view.prim_paths)!=[COUPON] or np.max(abs(scene.env_origins[0].cpu().numpy()))>1e-12:raise RuntimeError('Exact kinematic view/world frame differs')
        preflight=[];half=protocol['probe_size_m']/2
        for fixture in protocol['fixtures']:
            if fixture['side']!='left':raise RuntimeError('Only the frozen LEFT fixture is authorized')
            path=geometry['fingers']['left']['body_path']+'/'+fixture['collider_suffix'];point=np.asarray(fixture['point_finger_m'],float);normal=np.asarray(fixture['outward_finger'],float)
            colliders=geometry['fingers']['left']['colliders'];target=next(c for c in colliders if c['path']==path)
            distance=distance_to_triangles(point,target['points_finger_m'],target['triangle_indices'])
            if distance>protocol['matching']['position_atol_m'] or abs(np.linalg.norm(normal)-1)>1e-12:raise RuntimeError('Fixed CAD patch unsupported')
            centers=[point+(half+protocol['initial_clearance_m']-s)*normal for s in (0.,protocol['maximum_travel_m'])]
            lo=np.min(centers,axis=0)-half;hi=np.max(centers,axis=0)+half
            other=[]
            for collider in colliders:
                if collider['path']==path:continue
                bounds=np.asarray(collider['bounds_finger_m']);isolated=bool(np.any(bounds[1]<lo) or np.any(bounds[0]>hi))
                other.append({'path':collider['path'],'isolated_by_swept_AABB':isolated})
                if not isolated:raise RuntimeError('Fixture could hit another finger collider')
            preflight.append({**fixture,'path':path,'patch_surface_distance_m':distance,'swept_cube_bounds_finger_m':[lo.tolist(),hi.tolist()],'other_colliders':other})
        module=observer_module('collider_probe_tensor');module.NAMES=('left','right','coupon');module.BODIES={s:geometry['fingers'][s]['body_path'] for s in ('left','right')};module.BODIES['coupon']=COUPON
        indices={s:robot.body_names.index('fr3_'+s+'finger') for s in ('left','right')}
        proxies={s:SimpleNamespace(data=SimpleNamespace(root_com_pos_w=robot.data.body_com_pos_w[:,i])) for s,i in indices.items()}
        observer=module.ContactObserver(sim,{**proxies,'coupon':coupon},output)
        native=NativeObserver(sim,stage,output,role_paths,actor_sides)
        reporters={path:PhysxSchema.PhysxContactReportAPI.Get(stage,path).GetThresholdAttr().Get() for path in module.BODIES.values()}
        metadata={'protocol_sha256':sha(HERE/'protocol.json'),'dt_s':dt,'fixture_path':COUPON,'role_paths':role_paths,
            'settings_initial':settings(context,tool),'settings_terminal':None,'q_initial':initial['q'],'joint_names':robot.joint_names,'initial_proprioception':initial,
            'fixture_preflight':preflight,'reporters':reporters,'roles':[],
            'source_initial':{'ids':recorder.ids,'initial_edges':recorder.edges,'inventory_file':'evaluation_truth/initial_inventory.json'},'source_terminal':None,
            'observer_metadata':'contact_observations/metadata.json','native_observer_metadata':'evaluation_truth/native_contacts/metadata.json',
            'tool_geometry_file':'tool_geometry.json','cook_file':'cook_results.json','property_restoration_file':'property_restoration.json',
            'source_guard_semantics':'Native counts measured after each shared Recorder stationary watchdog assertion. Raw states, edges and any break events are retained in evaluation_truth.',
            'fixture_motion_API':'Only unloaded role/park initialization uses write_root_pose_to_sim. Measured motion uses root_physx_view.set_kinematic_targets XYZ+XYZW, index0; fixed initial finger frame.',
            'fixture_semantics':'Kinematic test-only placements and bounded approach/retract; no robot task trajectory or object-grasp credit.'}
        save(output/'metadata.json',metadata);step=0;status='running';reasons=[];last_forces={'left':0.,'right':0.,'coupon':0.}
        parked=np.array([2.,2.,.5,*pose[3:]])
        with (output/'trace.jsonl').open('w') as trace:
            def tick(role,phase,cube_pose,travel):
                nonlocal step,last_forces
                if step>=protocol['maximum_physics_steps']:raise RuntimeError('Probe step cap')
                robot.set_joint_position_target(torch.tensor(q0[None],dtype=torch.float32,device=robot.device))
                if abs(np.linalg.norm(cube_pose[3:])-1.)>1e-6:raise RuntimeError('Kinematic target quaternion is not normalized')
                coupon.root_physx_view.set_kinematic_targets(torch.tensor(cube_pose[[0,1,2,4,5,6,3]][None],dtype=torch.float32,device=robot.device),torch.tensor([0],dtype=torch.int32,device=robot.device))
                for label,i in indices.items():proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,i]
                observer.before_step();recorder.before_step();before=float(sim.current_time);native.begin(step+1)
                scene.write_data_to_sim();sim.step(render=False);scene.update(dt);step+=1
                for label,i in indices.items():proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,i]
                observed=observer.sample(step);event_file,packet=native.finish();recorder.sample(step);state=control.state()
                parts,edges=core.compute_connected_component('/World/envs/env_0/plate_source')
                if len(parts)!=301 or len(edges)!=930:raise RuntimeError('Measured native source graph changed')
                forces={}
                for label,summary in observed['bodies'].items():
                    with np.load(output/summary['file'],allow_pickle=False) as raw:forces[label]=float(abs(raw['normal_forces_N']).sum())
                actual=coupon.root_physx_view.get_transforms()[0].cpu().numpy()[[0,1,2,6,3,4,5]]
                position_error=float(np.linalg.norm(actual[:3]-cube_pose[:3]))
                qa=np.asarray(actual[3:],dtype=np.float64);qb=np.asarray(cube_pose[3:],dtype=np.float64)
                qa=qa/np.linalg.norm(qa);qb=qb/np.linalg.norm(qb)
                angle_error=float(2*np.arccos(np.clip(abs(qa@qb),0,1)))
                row={'step':step,'role':role,'phase':phase,'time_before_s':before,'time_s':float(sim.current_time),'physics_dt_s':dt,
                    'fixture_pose_world_wxyz':actual.tolist(),'fixture_command_pose_world_wxyz':cube_pose.tolist(),'fixture_command_readback_position_error_m':position_error,'fixture_command_readback_angle_rad':angle_error,
                    'fixture_travel_m':float(travel),'robot_q':state['q'],'robot_qdot':state['qdot'],
                    'finger_poses_world_wxyz':state['finger_poses_world_wxyz'],'tcp_pose_world_wxyz':state['tcp_pose_world_wxyz'],'forces_N':forces,'contacts':observed['bodies'],
                    'native_events_file':event_file,'native_online':packet,'source_guard':{'finite':bool(np.isfinite(recorder.last_states).all()),'parts':len(parts),'connections':len(edges),'stationary_watchdog_asserted':True,'break_events_asserted_empty':True}}
                trace.write(json.dumps(row,allow_nan=False)+'\n');trace.flush();last_forces=forces
                if max(forces.values())>protocol['sampled_force_abort_N']:raise RuntimeError('Sampled2N abort')
                if not np.isfinite(actual).all() or position_error>protocol['matching']['position_atol_m'] or angle_error>1e-4:raise RuntimeError('Kinematic target readback differs UNKNOWN')
                if forces['right']>protocol['force_floor_N']:raise RuntimeError('Unexpected RIGHT no-load control force')
                if not packet['complete'] or any(not v['finite'] or v['status']!='recorded_coverage_and_sign_unverified' for v in observed['bodies'].values()):raise RuntimeError('Incomplete observation UNKNOWN')
                if max(forces.values())>protocol['force_floor_N'] and not packet['robot_contacts']:raise RuntimeError('Loaded tensor stream without native report UNKNOWN')
                if np.max(abs(np.asarray(state['qdot'])[control.finger_ids]))>.002:raise RuntimeError('Finger velocity abort')
                if np.linalg.norm(np.asarray(state['tcp_pose_world_wxyz'])[:3]-np.asarray(initial['tcp_pose_world_wxyz'])[:3])>.002:raise RuntimeError('Stationary TCP drift')
                qa=np.asarray(state['tcp_pose_world_wxyz'][3:]);qb=np.asarray(initial['tcp_pose_world_wxyz'][3:])
                if 2*np.arccos(np.clip(abs(qa@qb)/(np.linalg.norm(qa)*np.linalg.norm(qb)),0,1))>np.deg2rad(2):raise RuntimeError('Stationary TCP angular drift')
                return forces['left']
            try:
                for fixture in protocol['fixtures']:
                    if max(last_forces.values())>protocol['force_floor_N']:raise RuntimeError('Loaded fixture park placement forbidden')
                    coupon.write_root_pose_to_sim(torch.tensor(parked[None],dtype=torch.float32,device=robot.device))
                    for _ in range(protocol['quiet_steps']//3):
                        tick('quiet','quiet',parked,0.)
                        if max(last_forces.values())>protocol['force_floor_N']:raise RuntimeError('Loaded relocation/quiet frame')
                    point=np.asarray(fixture['point_finger_m']);normal=np.asarray(fixture['outward_finger']);s=0.;phase='approach';positive=zero=nonzero=0;finished=False
                    if max(last_forces.values())>protocol['force_floor_N']:raise RuntimeError('Loaded next-role placement forbidden')
                    start_pose=np.r_[pose[:3]+rotation@(point+(half+protocol['initial_clearance_m'])*normal),pose[3:]]
                    coupon.write_root_pose_to_sim(torch.tensor(start_pose[None],dtype=torch.float32,device=robot.device))
                    for _ in range(protocol['steps_per_role']):
                        if phase=='approach':s=min(protocol['maximum_travel_m'],s+protocol['maximum_speed_m_s']*dt)
                        elif phase=='retract':s=max(0.,s-protocol['maximum_speed_m_s']*dt)
                        local=point+(half+protocol['initial_clearance_m']-s)*normal
                        cube_pose=np.r_[pose[:3]+rotation@local,pose[3:]]
                        force=tick(fixture['id'],phase,cube_pose,s)
                        nonzero+=int(force>protocol['force_floor_N']);positive=positive+1 if force>=protocol['positive_force_N'] else 0
                        if phase=='approach' and (positive>=protocol['positive_consecutive_steps'] or s>=protocol['maximum_travel_m']):phase='retract'
                        elif phase=='retract' and s==0.:
                            zero=zero+1 if max(last_forces.values())<=protocol['force_floor_N'] else 0
                            if zero>=3:finished=True;break
                    metadata['roles'].append({'id':fixture['id'],'retracted_unloaded':finished,'nonzero_frames':nonzero,'positive_force_last_consecutive':positive})
                    save(output/'metadata.json',metadata)
                    if not finished or nonzero<3:raise RuntimeError('Fixture evidence incomplete UNKNOWN')
                status='observation_sequence_completed'
            except Exception as error:
                reasons.append(type(error).__name__+': '+str(error));status='aborted'
        recorder.finish_control(science['stationary_guard']);tool.audit(stage,output/'geometry_terminal.json')
        parts,edges=core.compute_connected_component('/World/envs/env_0/plate_source')
        metadata.update(settings_terminal=settings(context,tool),source_terminal={'parts':len(parts),'connections':len(edges),'stationary_watchdog_asserted':status=='observation_sequence_completed'},controller_status=status,steps_executed=step)
        save(output/'metadata.json',metadata);save(output/'probe_complete.json',{'capture_completed':True,'status':status,'steps_executed':step,'stop_reasons':reasons,'grasp_or_extraction_claim':False})
    final_scene.make_env_cfg=factory;render_core.main(postassembly_hook=run)


if __name__=='__main__':main()

"""One simulation-only contact-guarded attempt; swept visibility is uncertified."""
import argparse,hashlib,json,math,os
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
STAGE=ROOT/'experiments/stage2_pick_20261025'
PARENT_RUNNER_SHA256='221d7e3ebc47d9c464172b2ee1de02d48252a237e92f8c09d958e955345f744d'
sys.path[:0]=[str(HERE),str(STAGE),str(ROOT),str(ROOT/'experiments/stage2_contact_20261025'),str(ROOT/'experiments/stage2_idle_20261025')]
from experiments.stage2_exposed_tip_20261025.model import save,sha
from tool_model import Tool
from recording import Recorder,settings,observer_module
from controller import Controller
from sensors import Sensors


def admission(clearance,authorization):
    return {'policy':'simulation_only_finger_contact_guarded',
            'visual_clearance_certified':False,'hardware_use':False,
            'measured_swept_clearance_passed':bool(clearance.get('passed',False)),
            'swept_space_status':'UNCERTIFIED_UNKNOWN',
            'known_robot_q_authorization':authorization}


def qangle(a,b):return 2*math.acos(min(1.,abs(float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b))))))
def interpolate(a,b,f):
    a,b=np.asarray(a,float),np.asarray(b,float);qb=b[3:].copy();dot=float(np.dot(a[3:],qb))
    if dot<0:qb=-qb;dot=-dot
    if dot>.9995:q=(1-f)*a[3:]+f*qb;q/=np.linalg.norm(q)
    else:
        angle=math.acos(min(1.,dot));q=(math.sin((1-f)*angle)*a[3:]+math.sin(f*angle)*qb)/math.sin(angle)
    return np.r_[(1-f)*a[:3]+f*b[:3],q]

def contacts(sample,geometry,state,selected,upper,lift_delta,protocol):
    from scipy.spatial.transform import Rotation
    from experiments.stage2_contact_20261025.geometry import own_point
    forces={};points={};reasons=[];dt=protocol['physics']['dt_s']
    for label in ('left','right'):
        summary=sample['bodies'][label];data=np.load(contacts.output/summary['file'],allow_pickle=False)
        if not summary['finite'] or 'unknown' in summary['status'] and summary['status']!='recorded_coverage_and_sign_unverified':
            reasons.append('contact_data_unknown_'+label);forces[label]=0.;points[label]=[];data.close();continue
        values=data['normal_forces_N'].reshape(-1);normal=data['normal_vectors_world'];worldpoints=data['normal_points_world_m'];separations=data['normal_separations_m'].reshape(-1)
        forces[label]=float(abs(values).sum());points[label]=[]
        if forces[label]>protocol['motion']['sampled_normal_force_abort_per_pad_N']:reasons.append('sampled_force_abort_'+label)
        if len(values) and np.max(abs(data['normal_impulses_Ns'].reshape(-1)-values*dt))>1e-7+1e-5*np.max(abs(values*dt)):reasons.append('contact_dt_scaling_'+label)
        vector=(values[:,None]*normal).sum(0);matrix=data['filtered_normal_impulse_matrix_world_Ns'].sum(axis=(0,1))/dt
        if np.linalg.norm(vector-matrix)>max(.005,.01*np.linalg.norm(vector)):reasons.append('contact_matrix_sign_'+label)
        pose=np.asarray(state['finger_poses_world_wxyz'][label]);rotation=Rotation.from_quat(pose[3:][[1,2,3,0]]).as_matrix();finger=geometry['fingers'][label]
        expected=np.array([0.,-1 if label=='left' else 1.,0.])
        for point,sep,force,n in zip(worldpoints,separations,values,normal):
            if abs(force)<=1e-8:continue
            local=(point-pose[:3])@rotation;outward=(-np.sign(force)*n)@rotation;length=np.linalg.norm(outward)
            if not np.isfinite(length) or length<=1e-12:reasons.append('invalid_contact_normal_'+label);continue
            outward/=length
            own=own_point(local,sep,finger,{'point_gate':{'surface_slack_m':protocol['contacts']['point_surface_slack_m'],'white_clearance_extra_m':protocol['contacts']['white_head_clearance_extra_m']}});flat=abs(local[1]-finger['inner_plane_y_m'])<=own['tolerance_m'];dot=float(outward@expected)
            qualified=bool(own['unique_pad'] and flat and dot>=.9)
            associated=False
            if selected is not None:
                xy=point[:2]-selected['table_xy_m'];yaw=selected['yaw_table_rad'];c,s=np.cos(yaw),np.sin(yaw);localxy=np.array([c*xy[0]+s*xy[1],-s*xy[0]+c*xy[1]])
                margin=.0015+.0005+math.sin(math.radians(1))*.016
                associated=bool(abs(localxy[0])<=.016+margin and abs(localxy[1])<=.008+margin and upper-.0017-.0096-.0015+lift_delta<=point[2]<=upper+.0015+lift_delta)
            record={'point_world_m':point.tolist(),'separation_m':float(sep),'force_signed_N':float(force),'outward_normal_finger':outward.tolist(),'flat_face_distance_m':float(abs(local[1]-finger['inner_plane_y_m'])),'lateral_qualified':qualified,'unique_body':bool(own['unique_pad']),'spatial_candidate_association':associated}
            points[label].append(record)
            if not qualified:reasons.append('unqualified_contact_'+label)
            if not associated:reasons.append('unassociated_contact_'+label)
        data.close()
    return forces,points,reasons


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--case',choices=('I',),required=True);parser.add_argument('--mode',choices=('control','pick'),required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--geometry',type=Path,required=True);parser.add_argument('--cameras',type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve();output.mkdir(exist_ok=True);(output/'online').mkdir(exist_ok=True)
    sys.argv=[sys.argv[0],*remaining,'--output',str(output),'--geometry',str(args.geometry),'--cameras',str(args.cameras)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':raise RuntimeError('Default Pueue and frozen epsilon required')
    protocol=json.loads((HERE/'protocol.json').read_text());tool=Tool(output)
    if sha(STAGE/'run_pick.py')!=PARENT_RUNNER_SHA256:raise RuntimeError('Shared parent runner source changed')
    pregrasp=protocol['pregrasp_init'];arm_names=['fr3_joint'+str(i) for i in range(1,8)]
    if pregrasp['joint_names']!=arm_names or np.asarray(pregrasp['q']).shape!=(7,) or not np.isfinite(pregrasp['q']).all():raise RuntimeError('Invalid fixed pregrasp initialization')
    authorization=HERE/pregrasp['authorization_file']
    if sha(authorization)!=pregrasp['authorization_sha256']:raise RuntimeError('Pregrasp authorization changed')
    proof=json.loads(authorization.read_text())
    if (proof['pose_integrity_subset_valid'] is not True or proof['original_full_diagnostic_passed'] is not False or
        proof['joint_names']!=arm_names or proof['q']!=pregrasp['q']):raise RuntimeError('Pregrasp evidence does not authorize these initialization values')
    from experiments.final_workcell_20261024 import scene as final_scene,render_core
    original_factory=final_scene.make_env_cfg;original_loader=render_core.load_geometry;original_init=None
    def loader(path):
        spec,bricks=original_loader(path)
        if spec['source_xy_m']!=[0.,0.]:raise RuntimeError('This controller requires the frozen identity TABLE-to-world frame')
        if args.case=='H':
            from experiments.partial_disassembly_20261024.render_adapter import prepare_case
            spec,bricks,_=prepare_case(spec,bricks,ROOT/'experiments/partial_disassembly_20261024/benchmark.json','H_mix')
        return spec,bricks
    def construct(scene,cfg):
        from isaaclab.sim import get_current_stage
        from pxr import PhysxSchema
        original_init(scene,cfg);tool.author(get_current_stage(),scene,output)
        for label in ('left','right'):PhysxSchema.PhysxContactReportAPI.Apply(get_current_stage().GetPrimAtPath('/World/envs/env_0/Robot/fr3_'+label+'finger')).CreateThresholdAttr(0.)
        spec=tool.cfg['scene_fingertip_spec'];q=.008+protocol['motion']['preopen_per_side_m']-(spec['stock_pad_backplane_abs_finger_y_m']+spec['body_mount_cad_x_mm']*.001)
        scene['robot'].cfg.init_state.joint_pos.pop('fr3_finger_joint.*',None);scene['robot'].cfg.init_state.joint_pos.update(fr3_finger_joint1=q,fr3_finger_joint2=q)
        positions=scene['robot'].cfg.init_state.joint_pos
        for name,value in zip(arm_names,pregrasp['q']):
            if name not in positions:raise RuntimeError('Missing explicit arm initialization key: '+name)
            positions[name]=float(value)  # Pre-reset cfg only; no measured-episode state write.
    def factory(cfg,capture=False):
        nonlocal original_init
        from isaaclab import scene as module
        from isaacsim.core.utils.extensions import enable_extension
        if not enable_extension('omni.isaac.dynamic_control'):raise RuntimeError('Installed property getter unavailable')
        env=original_factory(cfg,capture=capture);before=env.sim.to_dict();env.sim.physx.solver_type=0;env.sim.enable_scene_query_support=True
        expected={**before,'physx':{**before['physx'],'solver_type':0},'enable_scene_query_support':True}
        if env.sim.to_dict()!=expected:raise RuntimeError('Unexpected simulation config change')
        original_init=module.InteractiveScene.__init__;module.InteractiveScene.__init__=construct
        return env

    def run(**context):
        import torch
        from scipy.spatial.transform import Rotation
        sim,scene,robot=context['sim'],context['scene'],context['robot'];dt=sim.get_physics_dt()
        if dt!=protocol['physics']['dt_s']:raise RuntimeError('Unexpected dt')
        tool.validate(context);controller=Controller(robot,protocol);initial=controller.state();q0=np.asarray(initial['q']);finger_ids=controller.finger_ids;arm_ids=controller.arm_ids
        sensors=None;selection=None;selected=None;upper=None;target=None;status='running';stop=[]
        if args.mode=='pick':
            sensors=Sensors(sim,scene,args.geometry,args.cameras,output,protocol);candidates,frame=sensors.select(initial['tcp_pose_table_wxyz'])
            current_pose=np.asarray(initial['tcp_pose_table_wxyz']);current_rotation=Rotation.from_quat(current_pose[3:][[1,2,3,0]]).as_matrix();parts=[];current_parts=[]
            for label,finger in tool.geometry['fingers'].items():
                fp=np.asarray(initial['finger_poses_world_wxyz'][label]);fr=Rotation.from_quat(fp[3:][[1,2,3,0]]).as_matrix()
                for collider in finger['colliders']:
                    world=np.asarray(collider['points_finger_m'])@fr.T+fp[:3];current_parts.append(world);parts.append((world-current_pose[:3])@current_rotation)
            rejected=[]
            for candidate in candidates:
                height,support=sensors.local_height(candidate)
                if height is None:rejected.append({'candidate_id':candidate['candidate_id'],'reason':'unsupported_local_height','support':support});continue
                yaw=candidate['yaw_table_rad'];x=np.array([math.cos(yaw),math.sin(yaw),0]);z=np.array([0,0,-1.]);y=np.cross(z,x);rotation=np.column_stack((x,y,z));quat=Rotation.from_matrix(rotation).as_quat()[[3,0,1,2]]
                metal_delta=protocol['tool_frames']['metal_distal_hand_z_m']-protocol['tool_frames']['T_hand_grip_translation_m'][2]
                xyz=np.r_[candidate['table_xy_m'],height+.003]-rotation@np.array([0,0,metal_delta]);goal=np.r_[xyz,quat]
                tip_offset=.0584+tool.cfg['scene_fingertip_spec']['distal_tip_finger_z_m']-protocol['tool_frames']['T_hand_grip_translation_m'][2]
                overlap=(height-.0017)-(xyz[2]+(rotation@np.array([0,0,tip_offset]))[2])
                if overlap<.002:rejected.append({'candidate_id':candidate['candidate_id'],'reason':'insufficient_nominal_side_overlap'});continue
                hover=goal.copy();hover[2]+=.010;path=[]
                for a,b in ((current_pose,hover),(hover,goal)):
                    n=max(1,math.ceil(np.linalg.norm(b[:3]-a[:3])/.002),math.ceil(qangle(a[3:],b[3:])/math.radians(1)))
                    path.extend(interpolate(a,b,k/n) for k in range(n+1))
                clearance=sensors.clearance(path,parts,current_parts)
                selected,upper,target=candidate,height,goal
                selection={**frame,'candidate':candidate,'supported_upper_surface_m':height,'local_depth_support':support,'engineering_envelopes':protocol['engineering_envelopes'],'clearance':clearance,'nominal_body_side_overlap_m':float(overlap),'calibration':sensors.calibration,'rejected_candidates':rejected};break
            if selection is None:selection={**frame,'candidate':None,'local_depth_support':{'supported':False},'clearance':{'passed':False},'engineering_envelopes':protocol['engineering_envelopes'],'rejected_candidates':rejected};status='abstained'
            selection['geometry_views']=sensors.geometry_views;selection['geometry_safety_config_sha256']=sensors.safety_config_sha256
            selection['admission']=admission(selection['clearance'],pregrasp['authorization_sha256'])
            save(output/'online/selection.json',selection)
        else:save(output/'online/selection.json',None)
        recorder=Recorder(context,output,args.case,sensors,selection);recorder.stationary=args.mode=='control'
        module=observer_module('pick_online_contacts');module.NAMES=('left','right')
        proxies={label:SimpleNamespace(data=SimpleNamespace(root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')])) for label in ('left','right')}
        observer=module.ContactObserver(sim,proxies,output);contacts.output=output
        metadata={'case':args.case,'mode':args.mode,'protocol_sha256':sha(HERE/'protocol.json'),'dt_s':dt,'OSQP_EPSILON':os.environ['OSQP_EPSILON'],'T_world_table':np.eye(4).tolist(),'table_pose_world_wxyz':[0,0,0,1,0,0,0],'settings_initial':settings(context,tool),'settings_terminal':None,'tool_geometry_file':'tool_geometry.json','cook_file':'cook_results.json','property_restoration_file':'property_restoration.json','online_trace':'online/trace.jsonl','truth_inventory':'evaluation_truth/initial_inventory.json','truth_trace':'evaluation_truth/trace.jsonl','observer_metadata':'contact_observations/metadata.json','evaluation_observer_metadata':'evaluation_truth/contact_observations/metadata.json' if recorder.source_observer else None,'initial_joint_positions':initial['q'],'finger_joint_indices':finger_ids,'arm_joint_indices':arm_ids,'joint_limits':robot.data.joint_pos_limits[0].cpu().numpy().tolist()}
        metadata['initial_proprioception']=initial
        metadata['admission']=selection['admission'] if selection else None
        metadata['pregrasp_init']=pregrasp
        metadata['parent_runner_sha256']=PARENT_RUNNER_SHA256
        metadata['geometry_safety_config_sha256']=sensors.safety_config_sha256 if sensors else None
        metadata['geometry_views_file']='online/geometry_views.json' if sensors else None
        save(output/'capture_metadata.json',metadata)
        phase='control' if args.mode=='control' else 'approach';phase_start=np.asarray(initial['tcp_pose_table_wxyz']);phase_target=None;phase_time=0.;finger_command=float(q0[finger_ids].mean());positive=hold_steps=0;previous=initial;lift_start=None;last_sensor=0.;step=0
        if args.mode=='pick' and target is not None:phase_target=target.copy();phase_target[2]+=.010
        with (output/'online/trace.jsonl').open('w') as trace:
            while status=='running' and step<3600:
                before=controller.state();desired=np.asarray(before['tcp_pose_table_wxyz']);phase_time+=dt
                if args.mode=='control':desired=np.asarray(initial['tcp_pose_table_wxyz'])
                elif phase in ('approach','final_approach','lift'):
                    speed={'approach':.020,'final_approach':.002,'lift':.001}[phase]
                    duration=max(np.linalg.norm(phase_target[:3]-phase_start[:3])/speed,qangle(phase_start[3:],phase_target[3:])/protocol['motion']['orientation_command_speed_rad_s'],dt)
                    desired=interpolate(phase_start,phase_target,min(1.,phase_time/duration))
                elif phase in ('close','hold'):desired=target if phase=='close' else phase_target
                if phase=='close':finger_command-=.001*dt
                if abs(finger_command-q0[finger_ids].mean())>.004+2e-6:stop.append('finger_command_travel')
                if stop:status='aborted';break
                if args.mode=='control':
                    robot.set_joint_position_target(torch.tensor(q0[None],dtype=torch.float32,device=robot.device))
                    commanded={'joint_commands':q0.tolist(),'tcp_position_error_m':float(np.linalg.norm(np.asarray(before['tcp_pose_table_wxyz'])[:3]-desired[:3])),'tcp_angle_error_rad':qangle(np.asarray(before['tcp_pose_table_wxyz'])[3:],desired[3:]),'maximum_arm_command_increment_rad':0.}
                else:commanded=controller.command(desired,finger_command)
                for label in ('left','right'):proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')]
                observer.before_step();recorder.before_step();scene.write_data_to_sim();sim.step(render=False);scene.update(dt);step+=1
                state=controller.state()
                for label in ('left','right'):proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')]
                observed=observer.sample(step);recorder.sample(step)
                forces,qualified,reasons=contacts(observed,tool.geometry,state,selected,upper or 0.,0. if lift_start is None else state['tcp_pose_table_wxyz'][2]-lift_start[2],protocol)
                post=np.asarray(state['tcp_pose_table_wxyz']);error=float(np.linalg.norm(post[:3]-desired[:3]));angle=qangle(post[3:],desired[3:]);speed=float(np.linalg.norm(post[:3]-np.asarray(previous['tcp_pose_table_wxyz'])[:3])/dt)
                if np.max(abs(np.asarray(state['qdot'])[finger_ids]))>.002:reasons.append('finger_actual_speed')
                if np.max(abs(np.asarray(state['q'])[finger_ids]-q0[finger_ids]))>.004+2e-6:reasons.append('finger_actual_travel')
                if args.mode=='pick':
                    cap={'approach':.030,'final_approach':.003,'close':.003,'lift':.002,'hold':.002}[phase]
                    if speed>cap:reasons.append('TCP_actual_speed')
                    if phase in ('final_approach','close','lift','hold') and (error>.0005 or angle>math.radians(1)):reasons.append('TCP_tracking')
                if phase in ('control','approach','final_approach') and max(forces.values())>1e-6:reasons.append('unexpected_early_contact')
                row={'step':step,'phase':phase,'time_s':float(sim.current_time),'physics_dt_s':dt,**state,'joint_commands':commanded['joint_commands'],'tcp_target_table_wxyz':desired.tolist(),'tcp_position_error_m':error,'tcp_angle_error_rad':angle,'pre_step_command_error':commanded,'TCP_actual_speed_m_s':speed,'normal_force_per_pad_N':forces,'point_ownership':qualified,'contacts':observed['bodies'],'stop_reasons':sorted(set(reasons))}
                trace.write(json.dumps(row,allow_nan=False)+'\n');trace.flush();previous=state
                if reasons:stop+=reasons;status='aborted';break
                if args.mode=='control':continue
                if phase in ('approach','final_approach') and phase_time>=duration and np.linalg.norm(post[:3]-phase_target[:3])<=.0005 and qangle(post[3:],phase_target[3:])<=math.radians(1):
                    if phase=='approach':phase='final_approach';phase_start=post;phase_target=target.copy();phase_time=0.
                    else:phase='close';phase_time=0.
                elif phase=='close':
                    positive=positive+1 if min(forces.values())>=1.5 else 0
                    if positive>=3:phase='lift';phase_start=post.copy();lift_start=post.copy();phase_target=post.copy();phase_target[2]+=.005;phase_time=0.
                elif phase=='lift' and phase_time>=duration and np.linalg.norm(post[:3]-phase_target[:3])<=.0005:phase='hold';hold_steps=0
                elif phase=='hold':
                    hold_steps+=1
                    if hold_steps>=30:status='bounded_sequence_completed'
                if phase in ('final_approach','lift','hold') and float(sim.current_time)-last_sensor>=.1:sensors.capture();last_sensor=float(sim.current_time)
        if status=='running':
            status='control_completed' if args.mode=='control' and step==3600 else 'step_limit'
            if args.mode=='control':recorder.finish_control(protocol['stationary_guard'])
        from isaaclab.sim import get_current_stage
        tool.audit(get_current_stage(),output/'geometry_terminal.json')
        metadata['settings_terminal']=settings(context,tool);metadata['controller_status']=status;metadata['steps_executed']=step;save(output/'capture_metadata.json',metadata)
        save(output/'capture_complete.json',{'capture_completed':True,'case':args.case,'mode':args.mode,'controller_status':status,'steps_executed':step,'stop_reasons':sorted(set(stop)),'online_held_verification':'UNKNOWN; no truth-held success','native_extraction_claim':'Independent evaluation only'})
    final_scene.make_env_cfg=factory;render_core.load_geometry=loader
    render_core.main(postassembly_hook=run)

if __name__=='__main__':main()

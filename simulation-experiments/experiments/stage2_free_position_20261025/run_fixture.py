"""Fixed30-command position-only free-coupon comparison; no extraction claim."""
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
from experiments.stage2_contact_screen_20261025.screen import screen_contact
from experiments.stage2_collider_probe_20261025.native_observer import NativeObserver
from experiments.stage2_plane_pick_20261025.bridge import endpoint,model_gap

COUPON='/World/envs/env_0/contact_coupon'
POST='/World/envs/env_0/retention_post'


def fixture_design(reference,cfg,plan):
    """Known robot-only reference; upright brick root is its body BASE."""
    from scipy.spatial.transform import Rotation
    tcp=np.asarray(reference['tcp_pose_world_wxyz'],float);r=Rotation.from_quat(tcp[[4,5,6,3]]).as_matrix()
    if abs(r[2,0])>1e-4 or r[2,2]>-.9999:raise RuntimeError('Fixed fixture requires the existing hand-down orientation')
    yaw=float(math.atan2(r[1,0],r[0,0]));q=Rotation.from_euler('z',yaw).as_quat()[[3,0,1,2]]
    tips=[];spec=cfg['scene_fingertip_spec']
    inner=spec['stock_pad_backplane_abs_finger_y_m']+spec['body_mount_cad_x_mm']*.001
    for side,sign in (('left',1),('right',-1)):
        fp=np.asarray(reference['finger_poses_world_wxyz'][side],float);fr=Rotation.from_quat(fp[[4,5,6,3]]).as_matrix()
        tips.append(float((fp[:3]+fr@np.array([0.,sign*inner,spec['distal_tip_finger_z_m']]))[2]))
    top=float(np.mean(tips)+plan['nominal_body_side_overlap_m']);bottom=top-plan['body_size_m'][2]
    height=bottom-plan['table_z_m']
    if height<=0:raise RuntimeError('Passive post has nonpositive height')
    return {'coupon_pose':[*tcp[:2],bottom,*q],'yaw':yaw,'body_top':top,
        'post_pose':[*tcp[:2],plan['table_z_m']+height/2,1.,0.,0.,0.],
        'post_size':[*plan['post_size_xy_m'],height],'reference_tcp_pose_world_wxyz':tcp.tolist(),
        'reference_metadata_sha256':plan['fixture_reference_metadata']['sha256']}


def coupon_properties(coupon):
    return {k:getattr(coupon.root_physx_view,m)().cpu().numpy().tolist() for k,m in
        [('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms')]}


def fixture_initial(context,tool,initial,design,plan):
    from scipy.spatial.transform import Rotation
    from isaaclab.sim import get_current_stage
    from pxr import Usd,UsdPhysics
    import bricksim.core as core
    from omni.isaac.dynamic_control import _dynamic_control
    coupon=context['scene']['contact_coupon'];state=coupon.data.root_state_w[0].cpu().numpy().astype(float)
    requested=np.asarray(design['coupon_pose'],float)
    if np.linalg.norm(state[:3]-requested[:3])>plan['fixture_max_initial_pose_error_m'] or qangle(state[3:7],requested[3:])>plan['fixture_max_initial_angle_error_rad']:
        raise RuntimeError('Initial free coupon differs from authored pose')
    r=Rotation.from_quat(state[[4,5,6,3]]).as_matrix();x,y,z=plan['body_size_m']
    corners=np.array([[a,b,c] for a in (-x/2,x/2) for b in (-y/2,y/2) for c in (0,z)])@r.T+state[:3]
    lo,hi=corners.min(0),corners.max(0);post=np.asarray(design['post_pose'][:3]);size=np.asarray(design['post_size']);pl,ph=post-size/2,post+size/2
    overlaps={}
    for side,finger in tool.geometry['fingers'].items():
        fp=np.asarray(initial['finger_poses_world_wxyz'][side],float);fr=Rotation.from_quat(fp[[4,5,6,3]]).as_matrix()
        tip=fp[:3]+fr@np.array([0.,finger['inner_plane_y_m'],tool.cfg['scene_fingertip_spec']['distal_tip_finger_z_m']])
        overlaps[side]=float(hi[2]-tip[2])
        if abs(overlaps[side]-plan['nominal_body_side_overlap_m'])>plan['fixture_nominal_band_tolerance_m']:raise RuntimeError('Actual initial pad band differs')
        for collider in finger['colliders']:
            if not collider['enabled']:continue
            points=np.asarray(collider['points_finger_m'])@fr.T+fp[:3];cl,ch=points.min(0),points.max(0)
            if np.all(ch>=pl) and np.all(cl<=ph):raise RuntimeError('Initial post/finger overlap')
            if collider['role']!='body' and np.all(ch>=lo) and np.all(cl<=hi+[0,0,plan['stud_height_m']]):raise RuntimeError('Initial coupon/WHITE or HEAD overlap')
    if abs(lo[2]-ph[2])>plan['fixture_max_initial_pose_error_m'] or not np.all(state[:2]>pl[:2]) or not np.all(state[:2]<ph[:2]):raise RuntimeError('Passive support is not under the coupon body base')
    if pl[0]<=.128 and ph[0]>=-.128 and pl[1]<=.128 and ph[1]>=-.128:raise RuntimeError('Passive post overlaps fixed source plate footprint')
    parts,edges=core.compute_connected_component(COUPON)
    if set(parts)!={COUPON} or edges:raise RuntimeError('Fixture coupon must be isolated, never unclutched by edits')
    stage=get_current_stage();prim=stage.GetPrimAtPath(COUPON)
    if prim.GetAttribute('physics:kinematicEnabled').Get() is not False or prim.GetAttribute('physxRigidBody:disableGravity').Get() is not False:raise RuntimeError('Coupon must be dynamic under gravity')
    dc=_dynamic_control.acquire_dynamic_control_interface();props=dc.get_rigid_body_properties(dc.get_rigid_body(COUPON))
    iterations=[int(props.solver_position_iteration_count),int(props.solver_velocity_iteration_count)]
    if iterations!=[32,4]:raise RuntimeError('Actual coupon solver iterations differ')
    return {'coupon':{'path':COUPON,'root_pose_world_wxyz':state[:7].tolist(),'initial_state_world':state.tolist(),
        'body_bounds_world_m':[lo.tolist(),hi.tolist()],'body_size_m':plan['body_size_m'],'stud_height_m':plan['stud_height_m'],
        'dynamic':True,'disable_gravity':False,'properties':coupon_properties(coupon),'solver_iterations':iterations,'native_degree':0},
        'pedestal':{'path':POST,'pose_world_wxyz':design['post_pose'],'bounds_world_m':[pl.tolist(),ph.tolist()],'size_m':design['post_size'],'passive':True,
            'collider_paths':[str(p.GetPath()) for p in Usd.PrimRange(stage.GetPrimAtPath(POST)) if p.HasAPI(UsdPhysics.CollisionAPI)]},
        'design':{**design,'nominal_body_side_overlap_m':plan['nominal_body_side_overlap_m']},'actual_initial_body_side_overlap_m':overlaps}


class FixtureRecorder(Recorder):
    def sample(self,step):
        super().sample(step)
        parts,edges=self.core.compute_connected_component(COUPON)
        state=self.context['scene']['contact_coupon'].data.root_state_w[0].cpu().numpy()
        row={'step':step,'time_s':float(self.context['sim'].current_time),'coupon_state_world':state.tolist(),'native_degree':len(edges),'isolated_coupon':set(parts)=={COUPON}}
        with (self.directory/'fixture_trace.jsonl').open('a') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')
        if not np.isfinite(state).all() or edges or set(parts)!={COUPON}:raise RuntimeError('Evaluation watchdog: free coupon changed native status or became nonfinite')


def verify_fresh_control(audit_path,capture,current,initial,observer,fixture,plan,output):
    audit=json.loads(audit_path.read_text());meta=json.loads((capture/'capture_metadata.json').read_text());other=json.loads((capture/'fixture_initial.json').read_text());obs=json.loads((capture/'contact_observations/metadata.json').read_text())
    original=json.loads(Path(plan['original_control_protocol']['path']).read_text())
    checks={'passed_fresh_control':audit.get('proceed_gate_passed') is True and meta['mode']=='control' and meta['steps_executed']==plan['control_steps'],
        'control_capture_binding':Path(audit['capture_directory']).resolve()==capture.resolve() and audit['capture_metadata_sha256']==sha(capture/'capture_metadata.json'),
        'original_control_pins':sha(audit_path)==plan['original_control_audit']['sha256'] and sha(capture/'capture_metadata.json')==plan['original_control_metadata']['sha256'],
        'same_protocol':meta['contact_policy_protocol_sha256']==plan['original_control_protocol']['sha256'] and sha(Path(plan['original_control_protocol']['path']))==plan['original_control_protocol']['sha256'],
        'unchanged_control_science':all(plan[key]==original[key] for key in plan['control_physical_equivalence_keys']),
        'physical_settings':meta['settings_initial']==current,'initial_q':meta['initial_joint_positions']==initial['q'],
        'fixture':fixture==other,'raw_observer':observer==obs}
    save(output/'control_bridge.json',{'passed':all(checks.values()),'checks':checks,'control_audit_sha256':sha(audit_path),'control_capture_metadata_sha256':sha(capture/'capture_metadata.json')})
    if not all(checks.values()):raise RuntimeError('Fresh fixture control bridge failed')


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
            old_qualified=bool(own['unique_pad'] and flat and dot>=.9)
            associated=False
            if selected is not None:
                xy=point[:2]-selected['table_xy_m'];yaw=selected['yaw_table_rad'];c,s=np.cos(yaw),np.sin(yaw);localxy=np.array([c*xy[0]+s*xy[1],-s*xy[0]+c*xy[1]])
                margin=.0015+.0005+math.sin(math.radians(1))*.016
                associated=bool(abs(localxy[0])<=.016+margin and abs(localxy[1])<=.008+margin and upper-.0017-.0096-.0015+lift_delta<=point[2]<=upper+.0015+lift_delta)
            cad={'inner_plane_y_m':finger['inner_plane_y_m'],'expected_grip_normal_finger':expected.tolist(),
                'white_surfaces':[{'vertices_finger_m':c['points_finger_m'],'triangle_indices':c['triangle_indices']} for c in finger['colliders'] if c['role']=='white'],
                'head_surfaces':[{'vertices_finger_m':c['points_finger_m'],'triangle_indices':c['triangle_indices']} for c in finger['colliders'] if c['role']=='head']}
            screened=screen_contact(point,sep,-np.sign(force)*n,pose,cad,associated)
            qualified=bool(screened['compatible'])
            record={'point_world_m':point.tolist(),'separation_m':float(sep),'force_signed_N':float(force),'outward_normal_finger':outward.tolist(),'flat_face_distance_m':float(abs(local[1]-finger['inner_plane_y_m'])),'lateral_qualified':qualified,'unique_body':bool(own['unique_pad']),'spatial_candidate_association':associated,
                'old_finite_lateral_qualified':old_qualified,'plane_screen':screened}
            points[label].append(record)
            if not qualified:reasons.append('unqualified_contact_'+label)
            if not associated:reasons.append('unassociated_contact_'+label)
        data.close()
    return forces,points,reasons


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--mode',choices=('control','pick'),required=True)
    parser.add_argument('--predecessor-control',type=Path);parser.add_argument('--control-capture',type=Path)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--geometry',type=Path,required=True);parser.add_argument('--cameras',type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve();output.mkdir(exist_ok=True);(output/'online').mkdir(exist_ok=True)
    sys.argv=[sys.argv[0],*remaining,'--output',str(output),'--geometry',str(args.geometry),'--cameras',str(args.cameras)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':raise RuntimeError('Default Pueue and frozen epsilon required')
    plan=json.loads((HERE/'protocol.json').read_text());protocol=json.loads((HERE/'source_science.json').read_text());tool=Tool(output)
    if plan['execution_authorized'] is not True or sha(HERE/'source_science.json')!=plan['source_science_sha256']:raise RuntimeError('Fixture experiment/science not authorized')
    if sha(ROOT/'experiments/stage2_contact_screen_20261025/screen.py')!=plan['screen_evidence']['screen_sha256']:raise RuntimeError('Frozen pure screen changed')
    if sha(STAGE/'run_pick.py')!=PARENT_RUNNER_SHA256:raise RuntimeError('Shared parent runner source changed')
    reference_path=Path(plan['fixture_reference_metadata']['path'])
    if sha(reference_path)!=plan['fixture_reference_metadata']['sha256']:raise RuntimeError('Fixture reference changed')
    reference=json.loads(reference_path.read_text())['initial_proprioception']
    design=fixture_design(reference,tool.cfg,plan)
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
        env=original_factory(cfg,capture=capture)
        from isaaclab.assets import RigidObjectCfg,AssetBaseCfg
        from isaaclab.sim import RigidBodyPropertiesCfg,CuboidCfg,CollisionPropertiesCfg,RigidBodyMaterialCfg
        from bricksim.mdp.brick_part import BrickPartCfg
        env.scene.contact_coupon=RigidObjectCfg(prim_path=COUPON,spawn=BrickPartCfg(dimensions=(4,2,3),color=(185,145,100),
            rigid_props=RigidBodyPropertiesCfg(kinematic_enabled=False,disable_gravity=False,solver_position_iteration_count=32,solver_velocity_iteration_count=4,max_depenetration_velocity=.2)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=tuple(design['coupon_pose'][:3]),rot=tuple(design['coupon_pose'][3:])))
        env.scene.retention_post=AssetBaseCfg(prim_path=POST,spawn=CuboidCfg(size=tuple(design['post_size']),collision_props=CollisionPropertiesCfg(),
            physics_material=RigidBodyMaterialCfg(**plan['post_material'])),init_state=AssetBaseCfg.InitialStateCfg(pos=tuple(design['post_pose'][:3])))
        before=env.sim.to_dict();env.sim.physx.solver_type=0;env.sim.enable_scene_query_support=True
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
        coupon=scene['contact_coupon'];target=np.asarray(initial['tcp_pose_table_wxyz']);selected={'table_xy_m':design['coupon_pose'][:2],'yaw_table_rad':design['yaw']}
        upper=design['body_top']+plan['stud_height_m'];status='running';stop=[]
        if np.linalg.norm(target[:3]-np.asarray(reference['tcp_pose_world_wxyz'])[:3])>plan['fixture_max_initial_pose_error_m'] or qangle(target[3:],reference['tcp_pose_world_wxyz'][3:])>plan['fixture_max_initial_angle_error_rad']:
            raise RuntimeError('Actual initial TCP differs from fixed fixture reference')
        fixture=fixture_initial(context,tool,initial,design,plan)
        save(output/'fixture_initial.json',fixture)
        recorder=FixtureRecorder(context,output,'I');recorder.stationary=True
        source_module=observer_module('fixture_private_contacts');source_module.NAMES=('source',);source_module.BODIES={'source':COUPON}
        recorder.bound=COUPON;recorder.source_observer=source_module.ContactObserver(sim,{'source':SimpleNamespace(data=SimpleNamespace(root_com_pos_w=coupon.data.root_com_pos_w))},output/'evaluation_truth')
        module=observer_module('pick_online_contacts');module.NAMES=('left','right')
        proxies={label:SimpleNamespace(data=SimpleNamespace(root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')])) for label in ('left','right')}
        observer=module.ContactObserver(sim,proxies,output);contacts.output=output
        from isaaclab.sim import get_current_stage
        derived=endpoint(get_current_stage(),robot,controller,initial,tool.geometry,plan)
        startup=settings(context,tool)
        if args.mode=='pick':
            if args.predecessor_control is None or args.control_capture is None:raise RuntimeError('Fresh control evidence required')
            verify_fresh_control(args.predecessor_control,args.control_capture,startup,initial,observer.metadata,fixture,plan,output)
        role_paths={c['path']:{'side':side,'role':c['role']} for side,finger in tool.geometry['fingers'].items() for c in finger['colliders']}
        native=NativeObserver(sim,get_current_stage(),output,role_paths,{f['body_path']:s for s,f in tool.geometry['fingers'].items()})
        metadata={'case':'FREE_RETENTION','mode':args.mode,'protocol_sha256':sha(HERE/'source_science.json'),'dt_s':dt,'OSQP_EPSILON':os.environ['OSQP_EPSILON'],'T_world_table':np.eye(4).tolist(),'table_pose_world_wxyz':[0,0,0,1,0,0,0],'settings_initial':startup,'settings_terminal':None,'tool_geometry_file':'tool_geometry.json','cook_file':'cook_results.json','property_restoration_file':'property_restoration.json','online_trace':'online/trace.jsonl','truth_inventory':'evaluation_truth/initial_inventory.json','truth_trace':'evaluation_truth/trace.jsonl','observer_metadata':'contact_observations/metadata.json','evaluation_observer_metadata':'evaluation_truth/contact_observations/metadata.json' if recorder.source_observer else None,'initial_joint_positions':initial['q'],'finger_joint_indices':finger_ids,'arm_joint_indices':arm_ids,'joint_limits':robot.data.joint_pos_limits[0].cpu().numpy().tolist()}
        metadata.update(contact_policy_protocol_sha256=sha(HERE/'protocol.json'),source_science_sha256=sha(HERE/'source_science.json'),endpoint_preflight=derived,control_bridge_file='control_bridge.json' if args.mode=='pick' else None,
            native_observer_metadata='evaluation_truth/native_contacts/metadata.json',native_contact_index='evaluation_truth/native_contact_index.jsonl')
        metadata['initial_proprioception']=initial
        metadata.update(fixture_initial_file='fixture_initial.json',fixture_trace='evaluation_truth/fixture_trace.jsonl',
            fixture_contact_association='Declared known fixture initialization; no perception claim',coupon_properties_initial=fixture['coupon']['properties'])
        metadata['admission']={'policy':'known_free_coupon_retention_fixture','hardware_use':False,'perception_claim':False,'native_extraction_claim':False}
        metadata['pregrasp_init']=pregrasp
        metadata['parent_runner_sha256']=PARENT_RUNNER_SHA256
        metadata['geometry_safety_config_sha256']=None;metadata['geometry_views_file']=None
        save(output/'capture_metadata.json',metadata)
        phase='control' if args.mode=='control' else 'close';phase_start=np.asarray(initial['tcp_pose_table_wxyz']);phase_target=None;phase_time=0.;finger_command=float(q0[finger_ids].mean());positive=hold_steps=0;previous=initial;lift_start=None;last_sensor=0.;step=0
        endpoint_q=derived['endpoint_q_m'];endpoint_commands=0;confirmation=None;force_reference=None;closing_state=None
        position_count=0;position_window=[];position_candidate=None;lift_admission=None
        if args.mode=='pick':phase_target=target.copy()
        with (output/'online/trace.jsonl').open('w') as trace:
            while status=='running' and step<plan['maximum_physics_steps']:
                before=controller.state();desired=np.asarray(before['tcp_pose_table_wxyz']);phase_time+=dt
                if args.mode=='control':desired=np.asarray(initial['tcp_pose_table_wxyz'])
                elif phase in ('approach','final_approach','lift'):
                    speed={'approach':.020,'final_approach':.002,'lift':.001}[phase]
                    duration=max(np.linalg.norm(phase_target[:3]-phase_start[:3])/speed,qangle(phase_start[3:],phase_target[3:])/protocol['motion']['orientation_command_speed_rad_s'],dt)
                    desired=interpolate(phase_start,phase_target,min(1.,phase_time/duration))
                elif phase in ('close','hold'):desired=target if phase=='close' else phase_target
                if phase=='close':
                    finger_command=max(endpoint_q,finger_command-.001*dt)
                    closing_state='endpoint_settle' if abs(finger_command-endpoint_q)<=plan['endpoint_command_tolerance_m'] else 'ramp'
                if abs(finger_command-q0[finger_ids].mean())>.004+2e-6:stop.append('finger_command_travel')
                if stop:status='aborted';break
                if args.mode=='control':
                    robot.set_joint_position_target(torch.tensor(q0[None],dtype=torch.float32,device=robot.device))
                    commanded={'joint_commands':q0.tolist(),'tcp_position_error_m':float(np.linalg.norm(np.asarray(before['tcp_pose_table_wxyz'])[:3]-desired[:3])),'tcp_angle_error_rad':qangle(np.asarray(before['tcp_pose_table_wxyz'])[3:],desired[3:]),'maximum_arm_command_increment_rad':0.}
                else:commanded=controller.command(desired,finger_command)
                for label in ('left','right'):proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')]
                observer.before_step();recorder.before_step();native.begin(step+1);scene.write_data_to_sim();sim.step(render=False);scene.update(dt);step+=1
                state=controller.state()
                for label in ('left','right'):proxies[label].data.root_com_pos_w=robot.data.body_com_pos_w[:,robot.body_names.index('fr3_'+label+'finger')]
                observed=observer.sample(step);native_path,_discarded_packet=native.finish()
                with (output/'evaluation_truth/native_contact_index.jsonl').open('a') as native_index:
                    native_index.write(json.dumps({'step':step,'time_s':float(sim.current_time),'native_events_file':native_path},allow_nan=False)+'\n')
                recorder.sample(step)
                forces,qualified,reasons=contacts(observed,tool.geometry,state,selected,upper or 0.,0. if lift_start is None else state['tcp_pose_table_wxyz'][2]-lift_start[2],protocol)
                post=np.asarray(state['tcp_pose_table_wxyz']);error=float(np.linalg.norm(post[:3]-desired[:3]));angle=qangle(post[3:],desired[3:]);speed=float(np.linalg.norm(post[:3]-np.asarray(previous['tcp_pose_table_wxyz'])[:3])/dt)
                if np.max(abs(np.asarray(state['qdot'])[finger_ids]))>.002:reasons.append('finger_actual_speed')
                if np.max(abs(np.asarray(state['q'])[finger_ids]-q0[finger_ids]))>.004+2e-6:reasons.append('finger_actual_travel')
                if args.mode=='pick':
                    cap={'approach':.030,'final_approach':.003,'close':.003,'lift':.002,'hold':.002}[phase]
                    if speed>cap:reasons.append('TCP_actual_speed')
                    if phase in ('final_approach','close','lift','hold') and (error>.0005 or angle>math.radians(1)):reasons.append('TCP_tracking')
                if phase in ('control','approach','final_approach') and max(forces.values())>1e-6:reasons.append('unexpected_early_contact')
                if phase=='close' and closing_state=='endpoint_settle':endpoint_commands+=1
                actual_finger_q=np.asarray(state['q'],float)[finger_ids];commanded_finger_q=np.asarray(commanded['joint_commands'],float)[finger_ids]
                finger_errors=actual_finger_q-commanded_finger_q
                signs=[derived['fingers'][side]['opening_axis_hand'][1] for side in ('left','right')]
                actual_joint_gap=float(derived['gap_intercept_m']+signs[0]*actual_finger_q[0]-signs[1]*actual_finger_q[1])
                commanded_joint_gap=float(derived['gap_intercept_m']+signs[0]*commanded_finger_q[0]-signs[1]*commanded_finger_q[1])
                position_sample=bool(phase=='close' and closing_state=='endpoint_settle' and not reasons and
                    all(force>plan['position_contact_floor_N'] for force in forces.values()) and
                    np.all(finger_errors>plan['blocked_finger_allowance_m']) and
                    actual_joint_gap-commanded_joint_gap>plan['blocked_gap_allowance_m'])
                position_count=position_count+1 if position_sample else 0
                if phase=='close' and closing_state=='endpoint_settle':
                    position_window.append({'step':step,'endpoint_settle_completed_commands':endpoint_commands,'sample_passed':position_sample,
                        'forces_N':dict(forces),'actual_finger_q_m':actual_finger_q.tolist(),'commanded_finger_q_m':commanded_finger_q.tolist(),
                        'finger_tracking_errors_m':finger_errors.tolist(),'actual_joint_gap_m':actual_joint_gap,'commanded_joint_gap_m':commanded_joint_gap})
                    position_window=position_window[-plan['candidate_consecutive_steps']:]
                else:position_window=[]
                old_finite_reasons=['old_finite_unqualified_contact_'+side for side,values in qualified.items() if any(not p['old_finite_lateral_qualified'] for p in values)]
                row={'step':step,'phase':phase,'time_s':float(sim.current_time),'physics_dt_s':dt,**state,'joint_commands':commanded['joint_commands'],'tcp_target_table_wxyz':desired.tolist(),'tcp_position_error_m':error,'tcp_angle_error_rad':angle,'pre_step_command_error':commanded,'TCP_actual_speed_m_s':speed,'normal_force_per_pad_N':forces,'point_ownership':qualified,'contacts':observed['bodies'],'stop_reasons':sorted(set(reasons)),
                    'closing_state':closing_state,'finger_command_scalar_m':finger_command,'endpoint_settle_completed_commands':endpoint_commands,
                    'nominal_commanded_pad_gap_m':derived['gap_intercept_m']+derived['gap_per_symmetric_q']*finger_command,
                    'actual_model_pad_gap_m':model_gap(state,derived['inner_planes_finger_y_m']),'old_finite_guard_reasons':old_finite_reasons,
                    'actual_joint_gap_m':actual_joint_gap,'commanded_joint_gap_m':commanded_joint_gap,'finger_tracking_errors_m':finger_errors.tolist(),
                    'position_candidate_sample':position_sample,'position_candidate_consecutive_steps':position_count}
                trace.write(json.dumps(row,allow_nan=False)+'\n');trace.flush();previous=state
                if reasons:stop+=reasons;status='aborted';break
                if args.mode=='control':continue
                if phase in ('approach','final_approach') and phase_time>=duration and np.linalg.norm(post[:3]-phase_target[:3])<=.0005 and qangle(post[3:],phase_target[3:])<=math.radians(1):
                    if phase=='approach':phase='final_approach';phase_start=post;phase_target=target.copy();phase_time=0.
                    else:phase='close';phase_time=0.
                elif phase=='close':
                    positive=positive+1 if min(forces.values())>=plan['grasp_confirmation_N'] else 0
                    if positive>=plan['grasp_confirmation_consecutive_steps'] and force_reference is None:
                        force_reference={'step':step,'command_q_m':float(commanded['joint_commands'][finger_ids[0]]),
                            'at_endpoint':closing_state=='endpoint_settle','commanded_finger_q_m':[commanded['joint_commands'][i] for i in finger_ids]}
                    if endpoint_commands>=plan['endpoint_settle_steps']:
                        if endpoint_commands==plan['endpoint_settle_steps'] and position_count>=plan['candidate_consecutive_steps']:
                            finger_command=float(commanded['joint_commands'][finger_ids[0]])
                            position_candidate={'status':'GRASP_CANDIDATE','step':step,'command_q_m':finger_command,
                                'commanded_finger_q_m':commanded_finger_q.tolist(),'consecutive_steps':position_count,
                                'endpoint_settle_completed_commands':endpoint_commands,'window':list(position_window)}
                            lift_admission={'kind':'position_candidate','step':step,'command_q_m':finger_command}
                            closing_state='frozen';phase='lift';phase_start=post.copy();lift_start=post.copy();phase_target=post.copy();phase_target[2]+=plan['commanded_lift_m'];phase_time=0.
                        else:status='endpoint_without_position_candidate';stop.append('endpoint_without_position_candidate')
                elif phase=='lift' and phase_time>=duration and np.linalg.norm(post[:3]-phase_target[:3])<=.0005:phase='hold';hold_steps=0
                elif phase=='hold':
                    hold_steps+=1
                    if hold_steps>=plan['hold_steps']:status='bounded_sequence_completed'
        if status=='running':
            status='control_completed' if args.mode=='control' and step==plan['control_steps'] else 'step_limit'
            if args.mode=='control':recorder.finish_control(protocol['stationary_guard'])
        from isaaclab.sim import get_current_stage
        tool.audit(get_current_stage(),output/'geometry_terminal.json')
        metadata['settings_terminal']=settings(context,tool);metadata['controller_status']=status;metadata['steps_executed']=step
        metadata['coupon_properties_terminal']=coupon_properties(coupon)
        metadata['grasp_confirmation']=confirmation;metadata['endpoint_settle_completed_commands']=endpoint_commands
        metadata['position_candidate']=position_candidate;metadata['lift_admission']=lift_admission
        metadata['force_confirmation_reference']=force_reference
        metadata['force_confirmation_reference_passed']=force_reference is not None
        metadata['lift_admission_policy']='position_only_30_endpoint_commands'
        save(output/'capture_metadata.json',metadata)
        save(output/'fixture_complete.json',{'capture_completed':True,'case':'FREE_RETENTION','mode':args.mode,'controller_status':status,'steps_executed':step,'stop_reasons':sorted(set(stop)),'online_held_verification':'UNKNOWN; blocksStage3transfer','native_extraction_claim':False,'fixture_only':True})
    final_scene.make_env_cfg=factory;render_core.load_geometry=loader
    render_core.main(postassembly_hook=run)

if __name__=='__main__':main()

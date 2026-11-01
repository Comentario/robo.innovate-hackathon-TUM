"""Stock fixture and final gated proxy phases; bounded contact, no extraction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/stage2_idle_20261025'))
from geometry import BODIES,audit,own_point,metadata_scalar


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def main(adapter=None):
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--contact-case',choices=('B0_stock',),default='B0_stock')
    parser.add_argument('--proxy-stage',choices=('G','D','R'))
    parser.add_argument('--approved-proxy',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve()
    sys.argv=[sys.argv[0],*remaining,'--output',str(output)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':
        raise RuntimeError('Contact baseline requires default Pueue and explicit epsilon1e-4')
    protocol=json.loads((adapter.protocol_path if adapter else HERE/'protocol.json').read_text())
    proxy_config=proxy_reference=approved_proxy=None;proxy_artifact={}
    if args.proxy_stage:
        if hashlib.sha256((HERE/'proxy_config.json').read_bytes()).hexdigest()!=protocol['proxy_config_sha256']:raise RuntimeError('Frozen R3 proxy configuration changed')
        proxy_config=json.loads((HERE/'proxy_config.json').read_text())
        proxy_reference=json.loads((HERE/proxy_config['reference']).read_text())
        if args.proxy_stage!='G':
            if args.approved_proxy is None:raise RuntimeError('D/R require independently approved G artifact')
            approved_proxy=json.loads(args.approved_proxy.read_text())
            if approved_proxy['config_sha256']!=hashlib.sha256((HERE/'proxy_config.json').read_bytes()).hexdigest():raise RuntimeError('Approved G used another proxy configuration')
    for path,digest in protocol['input_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:raise RuntimeError('Frozen contact input changed: '+path)
    from experiments.final_workcell_20261024 import scene as final_scene,render_core
    original_factory=final_scene.make_env_cfg
    original_scene=None
    geometry_result={};opening={};factory_result={}

    def factory(cfg,capture=False):
        nonlocal original_scene
        from isaaclab import scene as scene_module
        from isaaclab.assets import RigidObjectCfg
        from isaaclab.sim import RigidBodyPropertiesCfg
        from bricksim.mdp.brick_part import BrickPartCfg
        from isaacsim.core.utils.extensions import enable_extension
        if not enable_extension('omni.isaac.dynamic_control'):raise RuntimeError('Installed runtime getter unavailable')
        env=original_factory(cfg,capture=capture)
        before=env.sim.physx.to_dict();env.sim.physx.solver_type=0
        if env.sim.physx.to_dict()!={**before,'solver_type':0}:raise RuntimeError('Only PGS scene change allowed')
        if adapter:adapter.configure(env)
        env.scene.contact_coupon=RigidObjectCfg(prim_path=BODIES['coupon'],
            spawn=BrickPartCfg(dimensions=(4,2,3),color=(185,145,100),rigid_props=RigidBodyPropertiesCfg(
                kinematic_enabled=True,disable_gravity=True,solver_position_iteration_count=32,solver_velocity_iteration_count=4)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(2.,2.,.5)))
        hand=env.scene.robot.actuators['hand']
        factory_result.update(physx_before=before,physx_after=env.sim.physx.to_dict(),hand_actuator={
            'joint_names_expr':hand.joint_names_expr,'effort_limit_sim':hand.effort_limit_sim,
            'stiffness':hand.stiffness,'damping':hand.damping})
        # render_core already holds this class locally. Patch its initializer
        # only in this queued process, not the module's class-name binding.
        original_scene=scene_module.InteractiveScene.__init__
        scene_module.InteractiveScene.__init__=construct
        return env

    def construct(result,cfg):
        from isaaclab.sim import get_current_stage
        from pxr import PhysxSchema
        original_scene(result,cfg)
        if result['robot'].is_initialized:raise RuntimeError('Finger opening must be configured BEFORE physics play')
        stage=get_current_stage()
        if adapter:
            adapter.author(stage,result,output)
            measured=audit(stage,output/'geometry.json')
        elif args.proxy_stage:
            from proxy import author_and_query
            audit(stage,output/'geometry_stock_before_proxy.json')
            proxy_artifact.update(author_and_query(stage,ROOT,proxy_config,output,approved_proxy))
            measured=audit(stage,output/'geometry.json',proxy_artifact)
            for label in ('left','right'):
                white=[c for c in measured['fingers'][label]['colliders'] if not c['is_pad']]
                reference=proxy_reference['white_colliders'][label]
                if len(white)!=len(reference):raise RuntimeError('White-finger collider inventory changed')
                for current,old in zip(white,reference):
                    import numpy as np
                    for key in ('path','type','enabled','physics_material_path','physics_material_attributes','triangle_indices'):
                        if current[key]!=old[key]:raise RuntimeError('White-finger collider changed: '+key)
                    if np.max(abs(np.asarray(current['points_finger_m'])-old['points_finger_m']))>1e-9:raise RuntimeError('White-finger geometry changed')
        else:measured=audit(stage,output/'geometry.json')
        geometry_result.update(measured)
        clearance=protocol['coupon']['initial_side_clearance_m'];half=.008
        for label,joint in (('left','fr3_finger_joint1'),('right','fr3_finger_joint2')):
            inner=measured['fingers'][label]['inner_plane_y_m']
            opening[label]=half+clearance+(-inner if label=='left' else inner)
            if args.proxy_stage:
                opening[label]+=proxy_reference['coupon_center_hand_m'][1]*(1 if label=='left' else -1)
            if not 0<opening[label]<.04:raise RuntimeError('Derived opening outside known finger range')
            pad=next(c for c in measured['fingers'][label]['colliders'] if c['is_pad'])
            if any(pad['physics_material_attributes'].get(key)!=value for key,value in (
                ('physics:staticFriction',2.5),('physics:dynamicFriction',2.0),('physics:restitution',0.))):
                raise RuntimeError('Stock pad material differs from frozen source')
        positions=result['robot'].cfg.init_state.joint_pos
        positions.pop('fr3_finger_joint.*',None)
        positions.update(fr3_finger_joint1=opening['left'],fr3_finger_joint2=opening['right'])
        for label in ('left','right'):
            PhysxSchema.PhysxContactReportAPI.Apply(stage.GetPrimAtPath(BODIES[label])).CreateThresholdAttr(0.)
        save(output/'preplay_geometry.json',{'derived_finger_opening_m':opening,'geometry':'geometry.json',
            'joint_position_config':positions,'reporters':'Zero-threshold finger reporters applied before play'})

    def contact(**context):
        import numpy as np
        import torch
        from pxr import UsdGeom,Gf,UsdPhysics,Usd
        from isaaclab.sim import get_current_stage
        from bricksim.mdp.brick_part import set_brick_part_xform
        import bricksim.core as core
        from omni.isaac.dynamic_control import _dynamic_control
        from run_idle import assess_state
        from diagnose_breakage import threshold_snapshot
        from contact_capture import ContactObserver
        sim,scene,robot=context['sim'],context['scene'],context['robot'];stage=get_current_stage()
        dt=sim.get_physics_dt();motion=protocol['motion'];finger_ids=[robot.joint_names.index('fr3_finger_joint1'),robot.joint_names.index('fr3_finger_joint2')]
        arm_ids=[robot.joint_names.index('fr3_joint'+str(i)) for i in range(1,8)]
        body_ids={label:robot.body_names.index(BODIES[label].rsplit('/',1)[-1]) for label in ('left','right')}
        hand_id=robot.body_names.index('fr3_hand');hand_pose=robot.data.body_link_pose_w[0,hand_id].cpu().numpy()
        hand_usd=UsdGeom.Xformable(stage.GetPrimAtPath('/World/envs/env_0/Robot/fr3_hand')).ComputeLocalToWorldTransform(0)
        hand_inverse=hand_usd.GetInverse();boxes={};relative={}
        for label in ('left','right'):
            finger_xf=UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0)*hand_inverse
            quat=finger_xf.ExtractRotationQuat()
            if render_core.quaternion_error([quat.GetReal(),*quat.GetImaginary()],[1,0,0,0])>protocol['initial_geometry']['parallel_finger_frame_rotation_tolerance_rad']:
                raise RuntimeError('Finger/coupon axes ambiguous; no contact motion')
            relative[label]=finger_xf
            boxes[label]=[]
            for collider in geometry_result['fingers'][label]['colliders']:
                points=np.asarray([list(finger_xf.Transform(Gf.Vec3d(*p))) for p in collider['points_finger_m']])
                boxes[label].append((collider,points.min(axis=0),points.max(axis=0)))
        pad={label:next((lo,hi) for c,lo,hi in boxes[label] if c['is_pad']) for label in ('left','right')}
        left_plane,right_plane=pad['left'][0][1],pad['right'][1][1]
        gap=left_plane-right_plane;clearance=(gap-.016)/2
        if abs(clearance-protocol['coupon']['initial_side_clearance_m'])>protocol['coupon']['clearance_tolerance_m']:
            raise RuntimeError('Actual FK/pad opening fails declared near-contact clearance')
        low=np.maximum(pad['left'][0],pad['right'][0]);high=np.minimum(pad['left'][1],pad['right'][1])
        center=np.array([(low[0]+high[0])/2,(left_plane+right_plane)/2,(low[2]+high[2])/2])
        if adapter:center=adapter.fixture_center(relative,center)
        if args.proxy_stage:
            center=np.asarray(proxy_reference['coupon_center_hand_m'],float).copy()
            if args.proxy_stage=='R':center[0]+=.002
            clearances=[left_plane-(center[1]+.008),(center[1]-.008)-right_plane]
            if np.max(abs(np.asarray(clearances)-protocol['coupon']['initial_side_clearance_m']))>protocol['coupon']['clearance_tolerance_m']:
                raise RuntimeError('Fixed B0 center does not have the declared new-pad clearance')
        coupon_lo=center+[-.016,-.008,-.0048];coupon_hi=center+[.016,.008,.0065]
        if adapter:
            adapter.check_fixture(low,high,coupon_lo,coupon_hi)
        elif high[0]<=low[0] or coupon_lo[2]<low[2] or coupon_hi[2]>high[2]:raise RuntimeError('Coupon does not fit common pad contact band')
        for label in ('left','right'):
            for collider,lo,hi in boxes[label]:
                if not collider['is_pad'] and np.all(hi>=coupon_lo-.00015) and np.all(lo<=coupon_hi+.00015):
                    raise RuntimeError('Coupon/white-collider initial AABB overlap ambiguous: '+collider['path'])
        root_hand=center+[0,0,-.0048];world=hand_usd.Transform(Gf.Vec3d(*root_hand))
        pose=[*[float(v) for v in world],*[float(v) for v in hand_pose[3:7]]]
        if args.proxy_stage!='G' and not (adapter and adapter.phase=='G'):
            scene['contact_coupon'].write_root_state_to_sim(torch.tensor([[*pose,*([0.]*6)]],dtype=torch.float32,device=robot.device))
            set_brick_part_xform(stage.GetPrimAtPath(BODIES['coupon']),pose[:3],pose[3:])
        coupon_colliders=[]
        for prim in Usd.PrimRange(stage.GetPrimAtPath(BODIES['coupon']),Usd.TraverseInstanceProxies()):
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                coupon_colliders.append({'path':str(prim.GetPath()),'type':prim.GetTypeName(),
                    'attributes':{a.GetName():metadata_scalar(a.Get()) for a in prim.GetAttributes() if isinstance(a.Get(),(int,float,bool,str))},
                    'transform_coupon_local':list(map(list,UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(BODIES['coupon'])).ComputeLocalToWorldTransform(0).GetInverse()))})
        names=['plate_source']+[b.name for b in context['bricks']];paths={'/World/envs/env_0/'+n for n in names}
        def source_states():
            rows=[]
            for name in names:
                v=scene[name].root_physx_view;p=v.get_transforms()[0].cpu().numpy()
                rows.append(np.r_[p[:3],p[6],p[3:6],v.get_velocities()[0].cpu().numpy()])
            return np.asarray(rows,float)
        initial_source=source_states();np.save(output/'source_initial.npy',initial_source)
        source_guard_cfg={**protocol['background_guards'],'maximum_final_linear_speed_m_s':.02,'maximum_final_angular_speed_rad_s':.2}
        initial_parts,initial_links=core.compute_connected_component('/World/envs/env_0/plate_source')
        if set(initial_parts)!=paths or len(initial_links)!=930 or len(names)!=301:raise RuntimeError('Full300 source guard not intact')
        if core.compute_connected_component(BODIES['coupon'])[1]:raise RuntimeError('Coupon must be unconnected')
        dc=_dynamic_control.acquire_dynamic_control_interface()
        runtime={}
        for name in names[1:]:
            path='/World/envs/env_0/'+name;props=dc.get_rigid_body_properties(dc.get_rigid_body(path))
            runtime[path]=[int(props.solver_position_iteration_count),int(props.solver_velocity_iteration_count)]
        if any(value!=[32,4] for value in runtime.values()):raise RuntimeError('Source runtime actor counts changed')
        physics_scenes=[{a.GetName():metadata_scalar(a.Get()) for a in p.GetAttributes() if isinstance(a.Get(),(float,int,bool,str))}
            for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        if not physics_scenes or any(p.get('physxScene:solverType')!='PGS' for p in physics_scenes):raise RuntimeError('Actual scene is not PGS')
        view=robot.root_physx_view
        def robot_properties():
            return {key:getattr(view,method)().cpu().numpy().tolist() for key,method in (
                ('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'),
                ('stiffnesses','get_dof_stiffnesses'),('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces'))}
        initial_props=robot_properties();q0=robot.data.joint_pos[0].cpu().numpy().copy()
        if adapter:
            adapter.initial(context,initial_props,geometry_result,center)
            if adapter.phase=='G':return
        nominal_command=robot.data.default_joint_pos[0].cpu().numpy().copy();command=nominal_command.copy()
        if np.max(abs(q0[finger_ids]-[opening['left'],opening['right']]))>5e-5:raise RuntimeError('Initial finger q readback differs')
        if np.max(abs(np.asarray(initial_props['stiffnesses'])[0,finger_ids]-2000))>1e-6 or np.max(abs(np.asarray(initial_props['dampings'])[0,finger_ids]-100))>1e-6 or np.max(abs(np.asarray(initial_props['effort_limits'])[0,finger_ids]-15))>1e-6:
            raise RuntimeError('Existing finger actuator settings changed')
        if args.proxy_stage:
            from scipy.spatial import cKDTree
            if initial_props!=proxy_reference['robot_properties']:raise RuntimeError('Robot mass/inertia/COM/actuators differ from frozen B0')
            for label in ('left','right'):
                visual=UsdGeom.Mesh(stage.GetPrimAtPath(BODIES[label]+'/UpdatedTipSTLVisual/Mesh'))
                relative=UsdGeom.Xformable(visual).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0).GetInverse()
                actual=np.asarray([list(relative.Transform(Gf.Vec3d(p))) for p in visual.GetPointsAttr().Get()])
                expected=np.asarray(proxy_artifact['tips'][label]['stl_points_finger_m'])
                error=max(cKDTree(expected).query(actual)[0].max(),cKDTree(actual).query(expected)[0].max())
                if error>proxy_config['visual_registration_match_m']:raise RuntimeError('Proxy input differs from unchanged visual registration')
            if args.proxy_stage=='G':
                if threshold_snapshot(core.get_breakage_thresholds())!=protocol['native_breakage'] or {'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force}!=protocol['native_assembly']:
                    raise RuntimeError('G native physical settings differ from the contact benchmark')
                save(output/'proxy_G_metadata.json',{'stage':'G','measured_contact_steps':0,'coupon_parked':True,
                    'protocol':protocol,'proxy_config':proxy_config,'runtime_source_actor32_4':runtime,
                    'physics_scenes':physics_scenes,'robot_properties':initial_props,'robot_properties_match_B0':True,
                    'source_parts':sorted(initial_parts),'native_connections':sorted(initial_links),
                    'native_breakage':threshold_snapshot(core.get_breakage_thresholds()),
                    'native_assembly':{'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force},
                    'native_core_sha256':hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
                    'physics_dt_s':dt,'OSQP_EPSILON':os.environ['OSQP_EPSILON'],
                    'joint_names':robot.joint_names,'joint_positions':q0.tolist(),
                    'nominal_joint_commands':nominal_command.tolist(),'robot_initialization':'robot_initialization.json',
                    'coupon_center_hand_m_frozen':center.tolist(),'proxy_geometry':'proxy_geometry.json'})
                save(output/'proxy_geometry_complete.json',{'stage':'G','capture_completed':True,'independent_fidelity_audit_required':True,'measured_contact_steps':0})
                return
        proxies={'coupon':scene['contact_coupon']}
        def refresh():
            for label,index in body_ids.items():
                proxies[label]=SimpleNamespace(data=SimpleNamespace(root_com_pos_w=robot.data.body_com_pos_w[:,index]))
        refresh();observer=ContactObserver(sim,proxies,output)
        if any(r['missing_requested_filter_paths'] or r['extra_resolved_filter_paths'] for r in observer.metadata['resolved_views'].values()):raise RuntimeError('Contact filter coverage incomplete')
        metadata={'protocol':protocol,'case':'B0_stock','geometry_file':'geometry.json','fixture_geometry':{'root_world_wxyz':pose,'body_center_hand_m':center.tolist(),'initial_side_clearance_m':clearance},
            'factory':factory_result,'physics_scenes':physics_scenes,'runtime_source_actor32_4':runtime,
            'initial_robot_properties':initial_props,'terminal_robot_properties':None,
            'initial_native_thresholds':threshold_snapshot(core.get_breakage_thresholds()),'terminal_native_thresholds':None,
            'native_assembly_initial':{'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force},
            'native_assembly_terminal':None,'initial_native_connections':sorted(initial_links),'initial_native_parts':sorted(initial_parts),
            'native_core_sha256':hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
            'physics_dt_s':dt,'OSQP_EPSILON':os.environ['OSQP_EPSILON'],
            'joint_names':robot.joint_names,'finger_joint_indices':finger_ids,'arm_joint_indices':arm_ids,
            'initial_joint_positions':q0.tolist(),'nominal_joint_commands':nominal_command.tolist(),'initial_hand_pose_world_wxyz':hand_pose.tolist(),
            'joint_limits':robot.data.joint_pos_limits[0].cpu().numpy().tolist(),
            'observer_metadata':'contact_observations/metadata.json','source_ids':names,
            'stock_collision_unchanged':True,'coupon_placement_scope':'Declared one-time fixture initialization, never perception pick'}
        if args.proxy_stage:
            metadata.update(stage=args.proxy_stage,case='D_updated_tip' if args.proxy_stage=='D' else 'R_updated_offset',
                stock_collision_unchanged=False,only_pad_mesh3_replaced=True,proxy_geometry='proxy_geometry.json',
                approved_G_geometry_sha256=hashlib.sha256(args.approved_proxy.read_bytes()).hexdigest(),
                own_cooked_hashes={label:proxy_artifact['tips'][label]['canonical_sha256'] for label in ('left','right')})
        metadata['coupon_collision_geometry']=coupon_colliders
        if adapter:metadata.update(adapter.metadata())
        metadata['coupon_collision_limit']='Native nominal body box plus full-footprint top slab, not individual-stud collision fidelity'
        metadata['fixture_geometry']['initial_clearance_per_side_m']={'left':clearance,'right':clearance}
        if metadata['initial_native_thresholds']!=protocol['native_breakage'] or metadata['native_assembly_initial']!=protocol['native_assembly']:
            raise RuntimeError('Native physical thresholds/switches differ from tested idle')
        save(output/'metadata.json',metadata)
        positive=reopened=0;phase='close';success=False;first_failure=None;signs={}
        with (output/'trace.jsonl').open('w') as trace:
            for step in range(1,motion['maximum_steps']+1):
                before=float(sim.current_time);refresh();observer.before_step()
                direction=-1 if phase=='close' else 1
                command[finger_ids]=np.maximum(nominal_command[finger_ids]-.001,np.minimum(nominal_command[finger_ids],command[finger_ids]+direction*.001*dt))
                robot.set_joint_position_target(torch.tensor(command[None],dtype=torch.float32,device=robot.device))
                scene.write_data_to_sim();sim.step(render=False);scene.update(dt);refresh()
                observed=observer.sample(step);q=robot.data.joint_pos[0].cpu().numpy();qd=robot.data.joint_vel[0].cpu().numpy()
                current=source_states();guard=assess_state(initial_source,current,source_guard_cfg)
                parts,links=core.compute_connected_component('/World/envs/env_0/plate_source');events=core.get_disassembled_connections(clear=True)
                reasons=list(guard['reasons']);guard.update(source_parts=len(parts),native_connections=len(links),break_events=[repr(e) for e in events])
                if set(parts)!=paths or set(links)!=set(initial_links) or events:reasons.append('native_source_changed')
                if not np.isfinite(robot.data.body_state_w.cpu().numpy()).all() or not np.isfinite(q).all() or not np.isfinite(qd).all() or not np.isfinite(scene['contact_coupon'].data.root_state_w.cpu().numpy()).all():reasons.append('nonfinite_robot_coupon')
                if np.max(abs(q[finger_ids]-q0[finger_ids]))>.001002 or np.max(abs(command[finger_ids]-nominal_command[finger_ids]))>.001002:reasons.append('finger_travel_limit')
                if np.max(abs(qd[finger_ids]))>.002:reasons.append('actual_finger_speed_abort')
                hand_actual=robot.data.body_link_pose_w[0,hand_id].cpu().numpy()
                hand_drift=float(np.linalg.norm(hand_actual[:3]-hand_pose[:3]))
                hand_angle=render_core.quaternion_error(hand_actual[3:],hand_pose[3:])
                if hand_drift>.002 or hand_angle>protocol['motion']['maximum_actual_hand_angle_abort_rad']:reasons.append('actual_hand_pose_abort')
                if np.any(q<robot.data.joint_pos_limits[0,:,0].cpu().numpy()) or np.any(q>robot.data.joint_pos_limits[0,:,1].cpu().numpy()):reasons.append('joint_limit')
                forces={};ownership={};poses={};vectors={}
                loaded={label:np.load(output/body['file'],allow_pickle=False) for label,body in observed['bodies'].items()}
                for label in ('left','right'):
                    data=loaded[label];resolved=observer.metadata['resolved_views'][label]['filter_paths']
                    filters=resolved[0] if len(resolved)==1 and isinstance(resolved[0],(list,tuple)) else resolved
                    partner=filters.index(BODIES['coupon']);count=int(data['normal_counts'][0,partner]);start=int(data['normal_starts'][0,partner])
                    select=(data['normal_indices']>=start)&(data['normal_indices']<start+count)
                    values=data['normal_forces_N'].reshape(-1);forces[label]=float(np.abs(values[select]).sum())
                    if np.abs(values[~select]).sum()>1e-6:reasons.append('unexpected_finger_contact')
                    if forces[label]>2:reasons.append('sampled_force_abort_'+label)
                    finger_pose=robot.data.body_link_pose_w[0,body_ids[label]].cpu().numpy();poses[label]=finger_pose.tolist()
                    world_to_finger=UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0).GetInverse()
                    ownership[label]=[]
                    vector=data['filtered_normal_impulse_matrix_world_Ns'][0,partner]/dt;vectors[label]=vector.tolist()
                    reverse=loaded['coupon'];rp=observer.metadata['resolved_views']['coupon']['filter_paths']
                    rp=rp[0] if len(rp)==1 and isinstance(rp[0],(list,tuple)) else rp
                    reverse_index=rp.index(BODIES[label])
                    reverse_start=int(reverse['normal_starts'][0,reverse_index]);reverse_count=int(reverse['normal_counts'][0,reverse_index])
                    reverse_select=(reverse['normal_indices']>=reverse_start)&(reverse['normal_indices']<reverse_start+reverse_count)
                    # Signed scalars encode force-on-sensor direction; BOTH
                    # reporting directions must own every force-carrying point.
                    for sensor,raw,mask in ((label,data,select),('coupon',reverse,reverse_select)):
                        raw_values=raw['normal_forces_N'].reshape(-1)
                        for point,sep,force,normal in zip(raw['normal_points_world_m'][mask],raw['normal_separations_m'][mask].reshape(-1),raw_values[mask],raw['normal_vectors_world'][mask]):
                            if abs(force)<=protocol['observation']['force_carrying_abs_floor_N']:continue
                            local=world_to_finger.Transform(Gf.Vec3d(*[float(v) for v in point]))
                            outward=None
                            if args.proxy_stage or adapter:
                                world_normal=(1 if sensor=='coupon' else -1)*np.sign(force)*normal
                                outward=np.asarray(world_to_finger.TransformDir(Gf.Vec3d(*[float(v) for v in world_normal])))
                            own=own_point(np.asarray(local),sep,geometry_result['fingers'][label],protocol,outward)
                            ownership[label].append({**own,'sensor':sensor,'point_world_m':point.tolist(),'separation_m':float(sep),
                                'normal_force_signed_N':float(force),'normal_force_N':float(abs(force))})
                            if not own['unique_pad']:reasons.append('nonunique_pad_contact_'+label)
                    reverse_vector=reverse['filtered_normal_impulse_matrix_world_Ns'][0,reverse_index]/dt
                    if np.linalg.norm(vector+reverse_vector)>max(.005,.01*np.linalg.norm(vector)):reasons.append('reciprocal_force_mismatch')
                    point_vector=(values[select,None]*data['normal_vectors_world'][select]).sum(axis=0)
                    if forces[label]>0:
                        choices=[s for s in (1,-1) if np.linalg.norm(s*point_vector-vector)<=max(.005,.01*np.linalg.norm(vector))]
                        if not choices:reasons.append('normal_sign_unknown')
                        elif len(choices)==1:
                            if label in signs and signs[label]!=choices[0]:reasons.append('normal_sign_changed')
                            else:signs[label]=choices[0]
                        elif forces[label]>=.2:reasons.append('ambiguous_positive_normal_sign')
                    err=np.abs(data['normal_impulses_Ns']-data['normal_forces_N']*dt)
                    if err.size and np.any(err>np.maximum(1e-7,1e-5*np.abs(data['normal_impulses_Ns']))):reasons.append('normal_dt_scaling')
                for label,data in loaded.items():
                    if not observed['bodies'][label]['finite'] or observed['bodies'][label]['status'].startswith('capacity_'):reasons.append('invalid_contact_buffer_'+label)
                    for impulses,forces_key in (('normal_impulses_Ns','normal_forces_N'),('friction_impulses_world_Ns','friction_forces_world_N')):
                        err=np.abs(data[impulses]-data[forces_key]*dt)
                        if err.size and np.any(err>np.maximum(1e-7,1e-5*np.abs(data[impulses]))):reasons.append('dt_scaling_'+label)
                coupon_data=loaded['coupon'];rp=observer.metadata['resolved_views']['coupon']['filter_paths']
                rp=rp[0] if len(rp)==1 and isinstance(rp[0],(list,tuple)) else rp
                for index,path in enumerate(rp):
                    if path in (BODIES['left'],BODIES['right']):continue
                    count=int(coupon_data['normal_counts'][0,index]);start=int(coupon_data['normal_starts'][0,index])
                    selected=(coupon_data['normal_indices']>=start)&(coupon_data['normal_indices']<start+count)
                    if np.abs(coupon_data['normal_forces_N'][selected]).sum()>1e-6:reasons.append('unexpected_coupon_partner')
                axis=np.asarray(hand_usd.TransformDir(Gf.Vec3d(0,1,0)))
                for label in ('left','right'):
                    vector=np.asarray(vectors[label]);opening_axis=axis if label=='left' else -axis
                    if forces[label]>=.01 and (np.linalg.norm(vector)<.01 or np.dot(vector,opening_axis)<.9*np.linalg.norm(vector)):
                        reasons.append('force_direction_not_opposed_to_closure_'+label)
                if len(set(signs.values()))>1:reasons.append('inconsistent_global_normal_sign')
                sign_resolved=set(signs)=={'left','right'} and len(set(signs.values()))==1
                positive=positive+1 if phase=='close' and min(forces.values())>=.2 and sign_resolved and not reasons else 0
                reopened=reopened+1 if phase=='reopen' and max(forces.values())<.01 and np.max(abs(command[finger_ids]-nominal_command[finger_ids]))<2e-6 and np.max(abs(q[finger_ids]-q0[finger_ids]))<5e-5 else 0
                record={'step':step,'phase':phase,'physics_time_before_s':before,'physics_time_after_s':float(sim.current_time),'physics_dt_s':dt,
                    'finger_poses_world_wxyz':poses,'finger_joint_positions_m':q[finger_ids].tolist(),'finger_joint_commands_m':command[finger_ids].tolist(),
                    'finger_joint_velocities_m_s':qd[finger_ids].tolist(),'arm_joint_targets':nominal_command[arm_ids].tolist(),'arm_joint_positions':q[arm_ids].tolist(),
                    'arm_joint_velocities':qd[arm_ids].tolist(),
                    'actual_hand_position_drift_m':hand_drift,'actual_hand_orientation_drift_rad':hand_angle,
                    'hand_pose_world_wxyz':hand_actual.tolist(),
                    'joint_actuation_forces_native_units':robot.root_physx_view.get_dof_actuation_forces()[0].cpu().numpy().tolist(),
                    'bodies':observed['bodies'],'source_guard':guard,'stop_reasons':sorted(set(reasons)),
                    'normal_force_per_pad_N':forces,'pair_force_vectors_world_N':vectors,'point_ownership':ownership,
                    'normal_sign_convention':signs,'positive_streak':positive,'reopen_streak':reopened}
                trace.write(json.dumps(record,allow_nan=False)+'\n');trace.flush()
                for data in loaded.values():data.close()
                if reasons:first_failure=record;break
                if positive>=3:phase='reopen';positive=0
                if reopened>=3:success=True;break
        metadata['terminal_robot_properties']=robot_properties();metadata['terminal_native_thresholds']=threshold_snapshot(core.get_breakage_thresholds())
        metadata['native_assembly_terminal']={'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force}
        terminal_parts,terminal_links=core.compute_connected_component('/World/envs/env_0/plate_source')
        metadata['terminal_native_parts']=sorted(terminal_parts);metadata['terminal_native_connections']=sorted(terminal_links)
        audit(stage,output/'geometry_terminal.json',proxy_artifact if args.proxy_stage else None)
        save(output/'metadata.json',metadata);np.save(output/'source_last.npy',current)
        if metadata['terminal_robot_properties']!=metadata['initial_robot_properties'] or metadata['terminal_native_thresholds']!=metadata['initial_native_thresholds'] or metadata['native_assembly_terminal']!=metadata['native_assembly_initial']:success=False
        save(output/'contact_report.json',{'case':metadata['case'],'stage':args.proxy_stage,'captured':True,'online_positive_reopen_gate':success,'steps_executed':step,
            'first_failure':first_failure,'limit_without_confirmation':not success and first_failure is None,
            'abort_semantics':'Any unsafe/incomplete-data failure halts further physics; no recovered/released claim after abort',
            'no_grasp_or_perception_pick_claim':True,
            **({key:metadata[key] for key in ('geometry_audit_sha256','side_authorization_sha256','global_G_passed','authorized_scope')} if adapter else {})})
        save(output/'contact_complete.json',{'capture_completed':True,'online_gate_passed':success,'independent_audit_required':True})

    final_scene.make_env_cfg=factory
    render_core.main(postassembly_hook=contact)


if __name__=='__main__':main()

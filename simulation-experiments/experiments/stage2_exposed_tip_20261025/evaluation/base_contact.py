"""Queued independent stock-pad contact audit, no simulation or physics solve."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rotation(q):
    q = np.asarray(q,float)
    if not np.isfinite(q).all() or np.linalg.norm(q) == 0:
        raise ValueError('Invalid finger WXYZ orientation')
    w,x,y,z = q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def surface_distance(point, vertices, indices):
    """Exact triangle-surface distance, including triangle edges and vertices."""
    triangles = np.asarray(vertices,float)[np.asarray(indices,int).reshape(-1,3)]
    if not len(triangles):
        return float('inf')
    a,b,c = triangles[:,0],triangles[:,1],triangles[:,2]
    ab,ac = b-a,c-a
    n = np.cross(ab,ac); n2 = np.sum(n*n,axis=1)
    ap = np.asarray(point)-a
    heights = np.sum(ap*n,axis=1)
    projected = np.asarray(point)-n*(np.divide(heights,n2,out=np.zeros_like(heights),where=n2>1e-30))[:,None]
    v = projected-a
    d00,d01,d11 = np.sum(ab*ab,axis=1),np.sum(ab*ac,axis=1),np.sum(ac*ac,axis=1)
    d20,d21 = np.sum(v*ab,axis=1),np.sum(v*ac,axis=1)
    den = d00*d11-d01*d01
    u = np.divide(d11*d20-d01*d21,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    w = np.divide(d00*d21-d01*d20,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    inside = (u>=0)&(w>=0)&(u+w<=1)&(n2>1e-30)
    face = np.divide(abs(heights),np.sqrt(n2),out=np.full(len(n2),np.inf),where=inside)
    distances = [face]
    for start,end in [(a,b),(b,c),(c,a)]:
        edge = end-start; length = np.sum(edge*edge,axis=1)
        t = np.divide(np.sum((np.asarray(point)-start)*edge,axis=1),length,out=np.zeros_like(length),where=length>1e-30)
        nearest = start+np.clip(t,0,1)[:,None]*edge
        distances.append(np.linalg.norm(np.asarray(point)-nearest,axis=1))
    return float(np.min(np.concatenate(distances)))


def classify_point(point_world, separation, pose, colliders, protocol, hulls=None, outward_world=None, proxy_config=None, flat_face_y_m=None, expected_grip_normal_finger=None):
    point = rotation(pose[3:7]).T@(np.asarray(point_world)-np.asarray(pose[:3]))
    distances = [(c['role'],surface_distance(point,c['points_finger_m'],c['triangle_indices'])) for c in colliders if c['enabled']]
    pad = min((d for role,d in distances if role=='body'),default=float('inf'))
    white = min((d for role,d in distances if role=='white'),default=float('inf'))
    head = min((d for role,d in distances if role=='head'),default=float('inf'))
    tolerance = abs(float(separation))+protocol['geometry']['pad_distance_allowance_m']
    boundary=True
    if hulls is not None:
        from union_geometry import hull_triangles,boundary_contact
        pad=min(surface_distance(point,h['vertices_m'],hull_triangles(h)[0]) for h in hulls)
        boundary=boundary_contact(point,rotation(pose[3:7]).T@np.asarray(outward_world),hulls,tolerance,proxy_config)
    unique_body=bool(boundary and np.isfinite([pad,white,head]).all() and pad<=tolerance and min(white,head)>tolerance+protocol['geometry']['white_extra_clearance_m'])
    outward=rotation(pose[3:7]).T@np.asarray(outward_world,float) if outward_world is not None else np.zeros(3)
    length=np.linalg.norm(outward);normal=outward/length if np.isfinite(outward).all() and length>0 else None
    flat_distance=abs(point[1]-flat_face_y_m) if flat_face_y_m is not None else float('inf')
    dot=float(np.dot(normal,expected_grip_normal_finger)) if normal is not None and expected_grip_normal_finger is not None else None
    lateral=bool(flat_distance<=tolerance and dot is not None and dot>=protocol['geometry']['side_contact']['minimum_outward_dot_grip_normal'])
    return {'point_finger_m':point.tolist(),'pad_distance_m':pad if np.isfinite(pad) else None,'white_distance_m':white if np.isfinite(white) else None,'head_distance_m':head if np.isfinite(head) else None,'tolerance_m':tolerance,
        'unique_body_geometry':unique_body,'flat_face_distance_m':float(flat_distance) if np.isfinite(flat_distance) else None,'flat_face_compatible':bool(flat_distance<=tolerance),
        'outward_normal_finger':normal.tolist() if normal is not None else None,'expected_grip_normal_finger':expected_grip_normal_finger,'outward_dot_grip_normal':dot,'lateral_qualified':lateral,
        'compatible_roles':[role for role,d in [('body',pad),('white',white),('head',head)] if d<=tolerance],
        'external_union_boundary_crossing':boundary,
        'uniquely_pad_compatible':unique_body and lateral}


def close(a,b,absolute,relative):
    a,b = np.asarray(a,float),np.asarray(b,float)
    return bool(np.linalg.norm(a-b) <= max(absolute,relative*max(np.linalg.norm(a),np.linalg.norm(b))))


def angle_between(q0,q):
    q0,q=np.asarray(q0,float),np.asarray(q,float)
    if not np.isfinite([q0,q]).all() or np.linalg.norm(q0)*np.linalg.norm(q)==0:
        return float('inf')
    return float(2*np.arccos(np.clip(abs(np.dot(q0,q))/(np.linalg.norm(q0)*np.linalg.norm(q)),0,1)))


def filter_paths(view):
    paths = view['filter_paths']
    if len(paths)==1 and isinstance(paths[0],list):
        paths=paths[0]
    return paths


def pair_rows(data, index, capacity):
    counts,starts = data['normal_counts'].reshape(-1),data['normal_starts'].reshape(-1)
    active = np.asarray(data['normal_indices'],int)
    n,start = int(counts[index]),int(starts[index])
    if n<0 or n and (start<0 or start+n>capacity):
        raise ValueError('Invalid pair range')
    wanted=np.arange(start,start+n,dtype=int); positions=np.searchsorted(active,wanted)
    if n and (np.max(positions)>=len(active) or not np.array_equal(active[positions],wanted)):
        raise ValueError('Pair range not present in copied active data')
    return positions


def ranges_valid(data, capacity):
    all_indices=[]
    counts=data['normal_counts'].reshape(-1);starts=data['normal_starts'].reshape(-1)
    for count,start in zip(counts,starts):
        count,start=int(count),int(start)
        if count<0 or count and (start<0 or start+count>capacity):
            return False
        if count:all_indices.extend(range(start,start+count))
    return len(all_indices)<capacity and len(set(all_indices))==len(all_indices) and np.array_equal(sorted(all_indices),data['normal_indices'])


def run_lengths(values):
    count=0;maximum=0;first=None
    for step,value in values:
        count=count+1 if value else 0
        maximum=max(maximum,count)
        if count>=3 and first is None:first=step
    return maximum,first


def view_summary(data, paths, protocol, dt):
    rules=protocol['contact_reporting'];capacity=rules['capacity_per_view']
    finite=all(np.isfinite(data[key]).all() for key in data.files)
    checks={'finite':finite,'normal_ranges_complete_unsaturated':ranges_valid(data,capacity)}
    normal_force=np.asarray(data['normal_forces_N'],float).reshape(-1)
    impulses=np.asarray(data['normal_impulses_Ns'],float).reshape(-1)
    normals=np.asarray(data['normal_vectors_world'],float)
    checks['normal_unit_vectors']=bool(np.all(abs(np.linalg.norm(normals,axis=1)-1)<=1e-3))
    checks['normal_dt_scaling']=close(impulses,normal_force*dt,rules['dt_scaling_absolute_tolerance_Ns'],rules['dt_scaling_relative_tolerance'])
    matrix=np.asarray(data['filtered_normal_impulse_matrix_world_Ns'],float).reshape(-1,3)/dt
    net=np.asarray(data['all_body_net_normal_impulse_world_Ns'],float).reshape(-1,3)[0]/dt
    checks['matrix_net_agreement']=close(matrix.sum(axis=0),net,rules['aggregate_absolute_tolerance_N'],rules['aggregate_relative_tolerance'])
    if len(matrix)!=len(paths) or data['normal_counts'].size!=len(paths):
        raise ValueError('Resolved filter order differs from contact matrix/ranges')
    pairs={}
    for i,path in enumerate(paths):
        index=pair_rows(data,i,capacity)
        vector=(normal_force[index,None]*normals[index]).sum(axis=0)
        signs=[sign for sign in [1,-1] if close(sign*vector,matrix[i],rules['aggregate_absolute_tolerance_N'],rules['aggregate_relative_tolerance'])]
        pairs[path]={'raw_signed_coefficient_sum_N':float(normal_force[index].sum()),
            'normal_magnitude_N':float(abs(normal_force[index]).sum()),
            'all_normal_magnitudes_N':float(abs(normal_force[index]).sum()),
            'matrix_force_N':matrix[i].tolist(),'point_sum_vector_N':vector.tolist(),
            'possible_signs':signs,'active_rows':index.tolist(),
            'force_carrying_rows':index[abs(normal_force[index])>protocol['force_response']['force_carrying_magnitude_floor_N']].tolist()}
    checks['all_pairs_point_matrix_agree']=all(pair['possible_signs'] for pair in pairs.values())
    friction_count=data['friction_counts'].reshape(-1);friction_start=data['friction_starts'].reshape(-1)
    friction_indices=[]
    for count,start in zip(friction_count,friction_start):
        count,start=int(count),int(start)
        if count<0 or count and (start<0 or start+count>capacity):
            checks['friction_ranges_complete_unsaturated']=False
            break
        if count:friction_indices.extend(range(start,start+count))
    else:
        checks['friction_ranges_complete_unsaturated']=len(friction_indices)<capacity and len(set(friction_indices))==len(friction_indices) and np.array_equal(sorted(friction_indices),data['friction_indices'])
    checks['friction_dt_scaling']=close(data['friction_impulses_world_Ns'],data['friction_forces_world_N']*dt,rules['dt_scaling_absolute_tolerance_Ns'],rules['dt_scaling_relative_tolerance'])
    return {'checks':checks,'pairs':pairs,'normal_point_count':len(normal_force),'friction_anchor_count':len(data['friction_indices'])}


def audit(args):
    protocol=read(HERE/'contact_protocol.json');meta=read(args.input/'metadata.json')
    geometry=read(args.input/meta['geometry_file']);observer=read(args.input/meta['observer_metadata'])
    report=read(args.input/'contact_report.json')
    rows=[json.loads(line) for line in (args.input/'trace.jsonl').read_text().splitlines()]
    observation_rows=[json.loads(line) for line in (args.input/'contact_observations/trace.jsonl').read_text().splitlines()]
    checks={};rules=protocol['contact_reporting'];motion=protocol['motion'];unchanged=protocol['unchanged']
    proxy_phase=getattr(args,'proxy_phase',None);proxy=getattr(args,'proxy_artifact',None)
    checks['declared_exposed_case']=meta['stage']==args.phase and meta['case']==args.phase+'_exposed'
    checks['budget_and_exact_steps']=0<len(rows)<=protocol['budget']['maximum_postinitialization_steps'] and [r['step'] for r in rows]==list(range(1,len(rows)+1)) and report['steps_executed']==len(rows)
    checks['same_observer_steps']=[r['step'] for r in observation_rows]==[r['step'] for r in rows]
    checks['native_binary']=meta['native_core_sha256']==unchanged['native_core_sha256']
    checks['actual_PGS']=bool(meta['physics_scenes']) and all(s.get('physxScene:solverType')=='PGS' for s in meta['physics_scenes'])
    checks['runtime_all300_32_4']=len(meta['runtime_source_actor32_4'])==300 and all(v==[32,4] for v in meta['runtime_source_actor32_4'].values())
    checks['source_inventory']=len(meta['source_ids'])==301 and len(set(meta['source_ids']))==301 and 'plate_source' in meta['source_ids'] and {p.rsplit('/',1)[-1] for p in meta['runtime_source_actor32_4']}==set(meta['source_ids'])-{'plate_source'}
    checks['native_thresholds_unchanged']=meta['initial_native_thresholds']==meta['terminal_native_thresholds'] and {k:v for k,v in meta['initial_native_thresholds'].items() if k!='debug_dump'}==unchanged['native_breakage']
    checks['native_assembly_unchanged_disabled']=meta['native_assembly_initial']==meta['native_assembly_terminal']=={'enabled':False,'required_force':1.0}
    checks['source_connection_identity_unchanged']=len(meta['initial_native_connections'])==930 and set(meta['initial_native_connections'])==set(meta['terminal_native_connections'])
    checks['source_part_identity_unchanged']=len(meta['initial_native_parts'])==301 and set(meta['initial_native_parts'])==set(meta['terminal_native_parts'])=={'/World/envs/env_0/'+name for name in meta['source_ids']}
    checks['robot_mass_inertia_actuators_unchanged']=meta['initial_robot_properties']==meta['terminal_robot_properties']
    finger_ids=meta['finger_joint_indices'];properties=meta['initial_robot_properties']
    checks['original_hand_actuators']=all(np.allclose(np.asarray(properties[field])[0,finger_ids],value,atol=1e-6,rtol=0) for field,value in [('stiffnesses',2000),('dampings',100),('effort_limits',15)])
    checks['initial_clearance']=abs(meta['fixture_geometry']['initial_side_clearance_m']-motion['initial_pad_coupon_clearance_per_side_m'])<=50e-6
    bodies={label:geometry['fingers'][label]['body_path'] for label in ['left','right']};bodies['coupon']='/World/envs/env_0/contact_coupon'
    geometry_checks={}
    for label in ['left','right']:
        colliders=geometry['fingers'][label]['colliders'];enabled=[c for c in colliders if c['enabled']]
        pads=[c for c in enabled if c['is_pad']]
        geometry_checks[label+'_pad_identity']=len(pads)==1 and pads[0]['path']==bodies[label]+protocol['geometry']['stock_pad_suffix'] and len(enabled)>1
        geometry_checks[label+'_valid_triangle_references']=all(c['approximation'] in (['convexDecomposition'] if proxy_phase and c['is_pad'] else ['convexHull','none']) and len(c['triangle_indices'])>0 and np.isfinite(c['points_finger_m']).all() for c in enabled)
        geometry_checks[label+'_stock_pad_material']=len(pads)==1 and all(pads[0]['physics_material_attributes'].get(key)==value for key,value in [('physics:staticFriction',2.5),('physics:dynamicFriction',2.0),('physics:restitution',0.0)])
    checks['pad_white_geometry_inventory']=all(geometry_checks.values())
    terminal_geometry=read(args.input/'geometry_terminal.json')
    geometry_unchanged=True
    for label in ['left','right']:
        before={c['path']:c for c in geometry['fingers'][label]['colliders']}
        after={c['path']:c for c in terminal_geometry['fingers'][label]['colliders']}
        geometry_unchanged=geometry_unchanged and set(before)==set(after)
        for path in set(before)&set(after):
            a,b=before[path],after[path]
            keys=['is_pad','enabled','approximation','contact_offset_m','rest_offset_m','physics_material_path','physics_material_attributes','authored_triangle_indices']
            geometry_unchanged=geometry_unchanged and all(a.get(k)==b.get(k) for k in keys) and np.allclose(a['points_finger_m'],b['points_finger_m'],atol=1e-8,rtol=0)
    checks['collision_geometry_materials_unchanged']=bool(geometry_unchanged)
    resolved=observer['resolved_views'];requested=set(observer['requested_all_scene_actor_filters'])|set(observer['requested_standalone_static_filters'])
    checks['three_sensor_paths_and_complete_filters']=set(resolved)==set(bodies) and all(v['sensor_paths']==[bodies[label]] and v['sensor_count']==1 and v['max_contact_data_count']==rules['capacity_per_view'] and set(filter_paths(v))==requested and len(filter_paths(v))==len(set(filter_paths(v))) for label,v in resolved.items())
    checks['required_source_and_fixture_actors_in_filters']={'/World/envs/env_0/'+name for name in meta['source_ids']}|set(bodies.values()) <= requested
    checks['SI_stage']=observer['stage_meters_per_unit']==1
    checks['processing_enabled']=observer['observation_setting']['after'] is False
    q0=np.asarray(meta['initial_joint_positions'],float)[finger_ids]
    arm_target=np.array([0,-.4,0,-2.5,0,2.1,.7854])
    frame_results=[];positive=[];release=[];possible_signs={1,-1};force_peaks={'left':0.,'right':0.};positive_first=None
    q_previous=q0.copy();step_previous=None
    for row,observation in zip(rows,observation_rows):
        if time.monotonic()>args.deadline:raise TimeoutError('Shared capture+audit deadline exhausted')
        dt=row['physics_dt_s'];step=row['step'];frame_checks={}
        frame_checks['clock']=abs(dt-unchanged['dt_s'])<1e-12 and abs(row['physics_time_after_s']-row['physics_time_before_s']-dt)<=1e-7 and (step_previous is None or abs(row['physics_time_before_s']-step_previous)<=1e-7) and abs(observation['physics_time_after_s']-row['physics_time_after_s'])<=1e-7
        frame_checks['three_fresh_bodies']=set(row['bodies'])==set(bodies) and row['bodies']==observation['bodies']
        command=np.asarray(row['finger_joint_commands_m'],float);actual=np.asarray(row['finger_joint_positions_m'],float);velocity=np.asarray(row['finger_joint_velocities_m_s'],float)
        float_allowance=2*np.finfo(np.float32).eps*max(float(abs(command).max()),float(abs(q_previous).max()))/dt
        frame_checks['command_ramp']=bool(np.max(abs(command-q_previous))/dt<=motion['maximum_command_speed_per_finger_m_s']+float_allowance)
        frame_checks['travel']=bool(np.max(abs(command-q0))<=motion['maximum_command_travel_per_finger_m']+motion['command_travel_serialization_allowance_m'] and np.max(abs(actual-q0))<=motion['maximum_actual_travel_per_finger_m']+motion['actual_travel_serialization_allowance_m'])
        frame_checks['measured_speed']=bool(np.isfinite(velocity).all() and np.max(abs(velocity))<=motion['actual_joint_speed_sampled_abort_m_s_strictly_above'])
        frame_checks['arm_targets_unchanged']=bool(np.allclose(row['arm_joint_targets'],arm_target,atol=1e-6,rtol=0))
        frame_checks['finite_actual_arm_q_qdot']=bool(np.isfinite(row['arm_joint_positions']).all() and np.isfinite(row['arm_joint_velocities']).all())
        hand0=np.asarray(meta['initial_hand_pose_world_wxyz']);hand=np.asarray(row['hand_pose_world_wxyz'])
        frame_checks['hand_pose_bound']=bool(np.isfinite(hand).all() and np.linalg.norm(hand[:3]-hand0[:3])<=motion['hand_pose_abort_translation_m_strictly_above'] and angle_between(hand0[3:7],hand[3:7])<=motion['hand_pose_abort_orientation_rad_strictly_above'])
        limit=np.asarray(meta['joint_limits'],float)[finger_ids]
        frame_checks['finger_joint_limits']=bool(np.isfinite(actual).all() and np.all(actual>=limit[:,0]) and np.all(actual<=limit[:,1]))
        guard=row['source_guard']
        frame_checks['source_guard']=guard['finite'] and guard['source_parts']==301 and guard['native_connections']==930 and not guard['break_events'] and guard['max_position_drift_m']<=unchanged['source_maximum_position_drift_m'] and guard['max_orientation_drift_rad']<=unchanged['source_maximum_orientation_drift_rad']
        frame_checks['no_capture_abort']=not row['stop_reasons']
        data={label:np.load(args.input/row['bodies'][label]['file'],allow_pickle=False) for label in bodies}
        views={label:view_summary(data[label],filter_paths(resolved[label]),protocol,dt) for label in bodies}
        frame_checks['raw_streams_complete']=all(all(v['checks'].values()) for v in views.values())
        ownership={};forces={};reciprocals={};positive_points=True;frame_signs={1,-1}
        for label in ['left','right']:
            pair=views[label]['pairs'][bodies['coupon']];reverse=views['coupon']['pairs'][bodies[label]]
            force_peaks[label]=max(force_peaks[label],pair['all_normal_magnitudes_N']);forces[label]=pair['normal_magnitude_N']
            frame_checks[label+'_force_ceiling']=pair['all_normal_magnitudes_N']<=protocol['force_response']['sampled_abort_normal_per_pad_N_strictly_above']
            reciprocal=close(pair['matrix_force_N'],-np.asarray(reverse['matrix_force_N']),rules['reciprocal_absolute_tolerance_N'],rules['reciprocal_relative_tolerance'])
            frame_checks[label+'_reciprocal']=reciprocal;reciprocals[label]=reciprocal
            ownership[label]=[]
            for sensor,pair_value in [(label,pair),('coupon',reverse)]:
                for index in pair_value['force_carrying_rows']:
                    signed_force=data[sensor]['normal_forces_N'][index].item()*data[sensor]['normal_vectors_world'][index]
                    extra={'outward_world':signed_force*(-1 if sensor==label else 1),
                        'flat_face_y_m':geometry['fingers'][label]['inner_plane_y_m'],
                        'expected_grip_normal_finger':[0.,-1. if label=='left' else 1.,0.]}
                    if proxy is not None:
                        force=data[sensor]['normal_forces_N'][index].item()*data[sensor]['normal_vectors_world'][index]
                        extra={'hulls':proxy['tips'][label]['cooked_hulls'],'outward_world':force*(-1 if sensor==label else 1),'proxy_config':proxy['config']}
                    point=classify_point(data[sensor]['normal_points_world_m'][index],data[sensor]['normal_separations_m'][index].item(),row['finger_poses_world_wxyz'][label],geometry['fingers'][label]['colliders'],protocol,**extra)
                    ownership[label].append({'sensor':sensor,'active_row':index,**point})
                    positive_points=positive_points and point['uniquely_pad_compatible']
                if pair_value['normal_magnitude_N']>=.005:
                    frame_signs&=set(pair_value['possible_signs'])
            allowed={bodies['coupon']} if label in ['left','right'] else set()
            frame_checks[label+'_no_other_contacts']=all(p['all_normal_magnitudes_N']<=1e-6 for path,p in views[label]['pairs'].items() if path not in allowed)
        frame_checks['coupon_no_other_contacts']=all(p['all_normal_magnitudes_N']<=1e-6 for path,p in views['coupon']['pairs'].items() if path not in {bodies['left'],bodies['right']})
        frame_checks['all_force_points_uniquely_pad']=positive_points
        possible_signs&=frame_signs
        frame_checks['consistent_possible_normal_sign']=bool(possible_signs)
        both_positive=min(forces.values())>=protocol['force_response']['positive_normal_per_pad_N'] and positive_points and all(frame_checks.values()) and len(possible_signs)==1
        positive.append((step,row['phase']=='close' and both_positive))
        if run_lengths(positive)[1] is not None and positive_first is None:positive_first=step
        releasing=positive_first is not None and row['phase']=='reopen' and max(forces.values())<protocol['force_response']['release_normal_per_pad_N_strictly_below'] and all(frame_checks.values())
        release.append((step,releasing))
        compact_views={label:{**value,'pairs':{path:pair for path,pair in value['pairs'].items() if pair['active_rows'] or np.linalg.norm(pair['matrix_force_N'])>0}} for label,value in views.items()}
        frame_results.append({'step':step,'phase':row['phase'],'checks':frame_checks,'normal_force_N':forces,'ownership':ownership,'views':compact_views,'possible_global_signs':sorted(possible_signs),'positive':both_positive,'release':releasing,'actual_velocity_m_s':velocity.tolist(),'arm_actual_minus_targets_rad':(np.asarray(row['arm_joint_positions'])-arm_target).tolist()})
        for value in data.values():value.close()
        q_previous=command;step_previous=row['physics_time_after_s']
    checks['all_perstep_guards']=len(frame_results)==len(rows) and all(all(f['checks'].values()) for f in frame_results)
    checks['resolved_global_normal_sign']=len(possible_signs)==1
    positive_max,positive_step=run_lengths(positive);release_max,release_step=run_lengths(release)
    checks['positive_both_pads_three_fresh']=positive_max>=protocol['force_response']['positive_consecutive_fresh_steps']
    checks['reopen_both_pads_three_fresh']=release_max>=protocol['force_response']['release_consecutive_fresh_steps']
    checks['online_offline_agree']=bool(report['online_positive_reopen_gate'])==bool(checks['positive_both_pads_three_fresh'] and checks['reopen_both_pads_three_fresh'] and checks['all_perstep_guards'])
    initial=np.load(args.input/'source_initial.npy',allow_pickle=False);last=np.load(args.input/'source_last.npy',allow_pickle=False)
    checks['source_saved_arrays_finite']=initial.shape==last.shape==(301,13) and bool(np.isfinite(initial).all() and np.isfinite(last).all())
    checks['source_final_speeds']=bool(np.linalg.norm(last[:,7:10],axis=1).max()<=unchanged['source_maximum_final_linear_speed_m_s'] and np.linalg.norm(last[:,10:13],axis=1).max()<=unchanged['source_maximum_final_angular_speed_rad_s'])
    result={'schema':'exposed-body-contact-independent-audit-signed-coefficients','input':str(args.input),'protocol_sha256':sha(HERE/'contact_protocol.json'),'checks':checks,'geometry_checks':geometry_checks,'contact_gate_passed':all(checks.values()),'steps':len(rows),'positive_first_completed_step':positive_step,'release_first_completed_step':release_step,'peak_all_normal_magnitudes_N':force_peaks,'possible_normal_signs':sorted(possible_signs),'first_capture_failure':report['first_failure'],'frames':frame_results,'limitations':['Positive normal reporting and conservative authored-surface compatibility only; cooked geometry not directly measured.','Signed scalar coefficients are retained in f*normal vectors; magnitude thresholds use SUM(abs(f)), not an inferred physical pressure sign.','Friction/materials remain uncalibrated; actuator effort is not pad force.','Sampled abort does not guarantee continuous-time force or speed caps.','No perception pick, grasp, extraction, held transform or complete STL validation.'],'claims':protocol['claims']}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'contact_gate_passed':result['contact_gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')
    print(json.dumps({'contact_gate_passed':result['contact_gate_passed'],'checks':sum(checks.values()),'total_checks':len(checks),'steps':len(rows)}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':
        raise RuntimeError('Actual contact audit requires default Pueue')
    audit(args)


if __name__=='__main__':
    main()

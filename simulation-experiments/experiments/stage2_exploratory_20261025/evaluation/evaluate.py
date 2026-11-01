"""Independent simulation-only exploratory pick; uncertified rays stay diagnostic."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time
STARTED=time.monotonic()
import cv2
import numpy as np
from contact_helpers import rotation,angle_between,view_summary,filter_paths,classify_point,close
from mass_reference import restoration_checks,targeted_write_checks
from safety_views import audit_safety
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(Path(p).read_text())
def json_default(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    raise TypeError(type(value).__name__)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def contact_file(value):return value['file'] if isinstance(value,dict) else value
def rows(p):
    with Path(p).open() as stream:
        for line in stream:
            if line.strip():yield json.loads(line)
def finite(x):return bool(np.isfinite(np.asarray(x,float)).all())
def check_time(deadline):
    if time.monotonic()>deadline:raise TimeoutError('Frozen cumulative case wall budget exhausted')
def polygon_iou(a,b):
    a,b=np.asarray(a,np.float32),np.asarray(b,np.float32)
    if a.ndim!=2 or b.ndim!=2 or a.shape[1]!=2 or b.shape[1]!=2 or not finite(a) or not finite(b):return 0.
    aa,bb=abs(cv2.contourArea(a)),abs(cv2.contourArea(b));intersection,_=cv2.intersectConvexConvex(a,b)
    return float(intersection/(aa+bb-intersection)) if aa+bb-intersection>0 else 0.
def initial_matches(polygon,faces):
    highest=max(face['layer'] for face in faces)
    return [{'id':face['id'],'iou':polygon_iou(polygon,face['image_polygon']),'layer':face['layer']} for face in faces if face['layer']==highest]

def expected_names(spec,removed):
    yaws=spec['layer_yaws_quarter_turn'];counts=spec['world_axis_counts_by_yaw_quarter_turn']
    if len(yaws)!=spec['layers']:raise ValueError('Frozen geometry layer-count mismatch')
    return ({'plate_source'}|{f'brick_{layer}_{i}_{j}' for layer,yaw in enumerate(yaws) for i in range(counts[str(yaw)][0]) for j in range(counts[str(yaw)][1])})-set(removed)

def relative_pose(tcp,body):
    rt,rb=rotation(tcp[3:7]),rotation(body[3:7])
    return rt.T@(np.asarray(body[:3])-tcp[:3]),rt.T@rb

def settings_checks(meta,science,inventory,baseline,cooked):
    a,b=meta['settings_initial'],meta['settings_terminal'];n=len(inventory['ids']);expected={str(x) for x in inventory['ids']}
    native=read(HERE/'contact_protocol.json')['unchanged'];checks={}
    checks['actual_PGS']=all(s.get('solverType')=='PGS' for s in a['physics_scenes']+b['physics_scenes']) and bool(a['physics_scenes']) and a['physics_scenes']==b['physics_scenes']
    checks['runtime_source_32_4']=a['source_actor_settings']==b['source_actor_settings'] and len(a['source_actor_settings'])==n-1 and all(v==[32,4] for v in a['source_actor_settings'].values())
    checks['frozen_robot_all6']=a['robot_properties']==b['robot_properties']==baseline['initial_robot_properties']
    checks['source_properties_unchanged']=a['source_properties']==b['source_properties']==inventory['source_properties'] and set(a['source_properties'])==expected
    checks['native_binary_and_thresholds']=all(s['native_core_sha256']==native['native_core_sha256'] and {k:v for k,v in s['native_breakage'].items() if k!='debug_dump'}==native['native_breakage'] and s['native_assembly']=={'enabled':False,'required_force':1.0} for s in [a,b])
    checks['same_frozen_cook']=a['cooked_hashes']==b['cooked_hashes']==cooked
    checks['dt_unchanged']=abs(meta['dt_s']-science['physics']['dt_s'])<=1e-12 and meta['OSQP_EPSILON']=='1e-4'
    return checks

def cook_checks(record,expected):
    checks={};finger_hashes={}
    for label in ['left','right']:
        canonical={}
        for kind in ['body','head']:
            result=record['tips'][label][kind]
            valid=result['result_valid'] is True and result['hull_count']==len(result['hulls'])==1
            hull=result['hulls'][0];vertices=np.asarray(hull['vertices_m']);planes=np.asarray([p['plane'] for p in hull['polygons']]);length=np.linalg.norm(planes[:,:3],axis=1)
            valid=valid and finite(vertices) and finite(planes) and bool(np.all(length>0)) and 4<=hull['vertex_count']==len(vertices)<=255 and 4<=hull['polygon_count']==len(planes)<=255
            checks[label+'_'+kind+'_actual_cook_valid']=bool(valid)
            planes=planes/length[:,None];rows=np.c_[np.rint(planes[:,:3]/1e-6),np.rint(planes[:,3]/1e-7)].astype(np.int64)
            canonical[kind]={'vertices':sorted(map(tuple,np.rint(vertices/1e-7).astype(np.int64).tolist())),'normalized_planes':sorted(map(tuple,rows.tolist()))}
        finger_hashes[label]=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    checks['independent_cooked_identity']=finger_hashes==record['canonical_sha256']==expected
    return checks

def geometry_checks(folder,meta,baseline_geometry):
    geometry=read(folder/meta['tool_geometry_file']);checks={}
    terminal=read(folder/'geometry_terminal.json')
    for label in ['left','right']:
        now=geometry['fingers'][label]['colliders'];old=baseline_geometry['fingers'][label]['colliders']
        white={c['path']:{k:v for k,v in c.items() if k not in ['role','is_head']} for c in now if c['role']=='white'}
        refs={c['path']:c for c in old if not c['is_pad']};same=set(white)==set(refs)
        for path,c in white.items():
            same=same and path in refs and set(c)==set(refs[path]) and all(np.allclose(c[k],refs[path][k],atol=1e-9,rtol=0) if k in ['points_finger_m','bounds_finger_m'] else c[k]==refs[path][k] for k in c)
        checks[label+'_white_unchanged']=bool(same)
        checks[label+'_body_head_inventory']=sum(c['enabled'] and c['role']=='body' for c in now)==1 and sum(c['enabled'] and c['role']=='head' for c in now)==1
        checks[label+'_body_material']=all(c['physics_material_attributes'].get(k)==v for c in now if c['role']=='body' for k,v in [('physics:staticFriction',2.5),('physics:dynamicFriction',2.0),('physics:restitution',0.0)])
        after={c['path']:c for c in terminal['fingers'][label]['colliders']};before={c['path']:c for c in now};same=set(after)==set(before)
        for path,c in before.items():
            same=same and path in after and set(c)==set(after[path]) and all(np.allclose(c[k],after[path][k],atol=1e-8,rtol=0) if k in ['points_finger_m','bounds_finger_m'] else c[k]==after[path][k] for k in c)
        checks[label+'_geometry_unchanged']=bool(same)
    return geometry,checks

def contact_frame(folder,row,gt,observer,geometry,protocol,target):
    checks={};peak={};loaded=0;worst_flat=0.;min_dot=1.;signs={1,-1};data={};summaries={}
    for label in ['left','right']:
        view=observer['resolved_views'][label];path=row['contacts'][label]
        path=path['file'] if isinstance(path,dict) else path
        with np.load(folder/path,allow_pickle=False) as raw:
            data[label]={k:raw[k].copy() for k in raw.files}
            summary=view_summary(data[label],filter_paths(view),protocol,row['physics_dt_s']);summaries[label]=summary
        checks[label+'_raw']=all(summary['checks'].values())
        peak[label]=sum(p['all_normal_magnitudes_N'] for p in summary['pairs'].values())
        checks[label+'_all_partner_force_abort']=peak[label]<=2.
        for pair in summary['pairs'].values():
            signs &= set(pair['possible_signs']) if pair['normal_magnitude_N']>protocol['contact_reporting']['aggregate_absolute_tolerance_N'] else {1,-1}
            for index in pair['force_carrying_rows']:
                f=float(data[label]['normal_forces_N'][index].item());normal=data[label]['normal_vectors_world'][index]
                point=classify_point(data[label]['normal_points_world_m'][index],data[label]['normal_separations_m'][index],row['finger_poses_world_wxyz'][label],geometry['fingers'][label]['colliders'],protocol,outward_world=-f*normal,flat_face_y_m=geometry['fingers'][label]['inner_plane_y_m'],expected_grip_normal_finger=[0,-1 if label=='left' else 1,0])
                checks['all_loaded_points_body_flat_lateral']=checks.get('all_loaded_points_body_flat_lateral',True) and point['uniquely_pad_compatible']
                loaded+=1;worst_flat=max(worst_flat,point['flat_face_distance_m']);min_dot=min(min_dot,point['outward_dot_grip_normal'])
        checks[label+'_online_aggregate_matches_raw']=close(peak[label],row['normal_force_per_pad_N'][label],1e-7,1e-5)
    reciprocal='UNMEASURED'
    if 'source' in observer['resolved_views'] and target is not None:
        source_view=observer['resolved_views']['source'];source_file=gt['contacts']['source'];source_file=source_file['file'] if isinstance(source_file,dict) else source_file
        checks['source_view_exact_prebound_target']=source_view['sensor_paths']==[target] and source_view['sensor_count']==1
        with np.load(folder/source_file,allow_pickle=False) as raw:
            source={k:raw[k].copy() for k in raw.files};summary=view_summary(source,filter_paths(source_view),protocol,row['physics_dt_s'])
        checks['source_raw_complete']=all(summary['checks'].values());reciprocal='MEASURED'
        for label in ['left','right']:
            finger_path=geometry['fingers'][label]['body_path'];pair=summaries[label]['pairs'][target];reverse=summary['pairs'][finger_path]
            rules=protocol['contact_reporting'];checks[label+'_source_reciprocal']=close(pair['matrix_force_N'],-np.asarray(reverse['matrix_force_N']),rules['reciprocal_absolute_tolerance_N'],rules['reciprocal_relative_tolerance'])
            checks[label+'_no_other_partner_load']=sum(value['normal_magnitude_N'] for path,value in summaries[label]['pairs'].items() if path!=target)<=protocol['force_response']['unexpected_other_pair_normal_magnitude_floor_N']
            if reverse['normal_magnitude_N']>rules['aggregate_absolute_tolerance_N']:signs &= set(reverse['possible_signs'])
            for index in reverse['force_carrying_rows']:
                f=float(source['normal_forces_N'][index].item());normal=source['normal_vectors_world'][index]
                point=classify_point(source['normal_points_world_m'][index],source['normal_separations_m'][index],row['finger_poses_world_wxyz'][label],geometry['fingers'][label]['colliders'],protocol,outward_world=f*normal,flat_face_y_m=geometry['fingers'][label]['inner_plane_y_m'],expected_grip_normal_finger=[0,-1 if label=='left' else 1,0])
                checks['all_reciprocal_loaded_points_body_flat_lateral']=checks.get('all_reciprocal_loaded_points_body_flat_lateral',True) and point['uniquely_pad_compatible']
                loaded+=1;worst_flat=max(worst_flat,point['flat_face_distance_m']);min_dot=min(min_dot,point['outward_dot_grip_normal'])
    elif target is not None:checks['source_reciprocal_available']=False
    return checks,{'reciprocal':reciprocal,'peak_N':peak,'loaded_observations':loaded,'max_flat_distance_m':worst_flat,'min_outward_dot':min_dot if loaded else None,'possible_signs':sorted(signs)},data,summaries

def provenance(args,p,science,meta):
    inputs=HERE.parent/'inputs';auth=read(inputs/'pregrasp_authorization.json');old=read(inputs/'source_1807_audit.json');d=read(inputs/'source_1807_derivation.json');original=read(inputs/'original_science.json');checks={}
    perception=json.loads(json.dumps(science['perception']));perception['candidate_selection']=original['perception']['candidate_selection'];perception['geometry_safety_view']['clearance_policy']=original['perception']['geometry_safety_view']['clearance_policy']
    checks['physical_numeric_sections_unchanged']=all(science[key]==original[key] for key in p['unchanged_sections']) and perception==original['perception'] and all(science['budget'][key]==original['budget'][key] for key in p['unchanged_budget_fields'])
    policy=science['admission_policy'];checks['explicit_simulation_unknown_admission']=all(policy[key] is value for key,value in [('simulation_only',True),('full_ray_certificate_required',False),('unknown_is_free',False),('one_control_then_one_pick',True),('no_improvements',True),('I_only',True)]) and policy['id']=='UNKNOWN_PATH_FINGER_CONTACT_GUARDED' and science['budget']['maximum_reviewed_improvement_rounds']==0
    checks['source_full_diagnostic_stays_failed']=old['gate_passed'] is False and old['proceed_gate_passed'] is False and auth['original_full_diagnostic_passed'] is False and auth['pose_integrity_subset_valid'] is True and sorted(k for k,v in old['checks'].items() if not v)==sorted(p['source_failed_flags']) and sum(bool(v) for v in old['checks'].values())==32
    init=science['pregrasp_init'];checks['exact_failed_diagnostic_q_authorization']=sha(inputs/'pregrasp_authorization.json')==init['authorization_sha256'] and meta['pregrasp_init']==init and init['source_full_diagnostic_passed'] is False and init['joint_names']==auth['joint_names']==d['joint_names'] and init['q']==auth['q']==d['q'] and d['state_writes']==d['simulation_steps']==0
    for old_name,new_name in p['source_file_map'].items():
        if sha(inputs/new_name)!=auth['source_sha256'][old_name]:raise ValueError('Original1807 provenance changed')
    robot=read(args.input/'robot_initialization.json');names=robot['joint_names'];indices=[names.index(n) for n in init['joint_names']];q=np.asarray(init['q']);actual=np.asarray(meta['initial_joint_positions'])[indices]
    checks['fresh_fixed_q_readback']=bool(np.isfinite(actual).all() and np.max(abs(actual-q))<=.001 and np.max(abs(np.asarray(robot['requested_joint_positions_native_units'])[indices]-q))<=.001)
    initial=meta['initial_proprioception']['tcp_pose_world_wxyz'];expected=d['predicted_tcp_pose_wxyz'];checks['fresh_staging_TCP_readback']=bool(np.linalg.norm(np.asarray(initial[:3])-expected[:3])<=.0001 and angle_between(initial[3:7],expected[3:7])<=.001)
    checks['parent_measured_controller_unchanged']=meta['parent_runner_sha256']==p['parent_runner_sha256']
    return checks

def audit(args,p,science,deadline):
    folder=args.input;meta=read(folder/'capture_metadata.json');inv=read(folder/meta['truth_inventory']);rules=p['cases'][args.case]
    checks=provenance(args,p,science,meta);checks.update({'capture_case_mode':meta['case']==args.case and meta['mode']==args.mode,'capture_scientific_pin':meta['protocol_sha256']==sha(HERE.parent/'protocol.json')})
    baseline=read(HERE.parent/'inputs/baseline_metadata.json');oldgeometry=read(HERE.parent/'inputs/baseline_geometry.json')
    gaudit=read(HERE.parent/'inputs/geometry_audit.json');auth=read(HERE.parent/'inputs/side_authorization.json')
    checks['original_G_stays_failed']=gaudit['phase']=='G' and gaudit['proceed_gate_passed'] is False and auth['global_G_passed'] is False and auth['geometry_audit_sha256']==sha(HERE.parent/'inputs/geometry_audit.json')
    checks.update(settings_checks(meta,science,inv,baseline,gaudit['cooked_hashes']));checks.update(cook_checks(read(folder/meta['cook_file']),gaudit['cooked_hashes']))
    checks['prior_lateral_contact_evidence']=all(read(HERE.parent/'inputs'/name)['proceed_gate_passed'] is True for name in ['D_contact_audit.json','R_contact_audit.json'])
    restoration=read(folder/meta['property_restoration_file']);checks.update(restoration_checks(restoration,baseline,p));checks.update(targeted_write_checks(restoration))
    geometry,extra=geometry_checks(folder,meta,oldgeometry);checks.update(extra)
    ids=inv['ids'];initial_edges={e['id']:(e['a'],e['b']) for e in inv['initial_edges']}
    adjacency={key:set() for key in ids}
    for a,b in initial_edges.values():
        if a in adjacency and b in adjacency:adjacency[a].add(b);adjacency[b].add(a)
    visited=set();pending=[ids[0]] if ids else []
    while pending:
        item=pending.pop()
        if item not in visited:visited.add(item);pending.extend(adjacency[item]-visited)
    checks['initial_native_source_connected']=visited==set(ids)
    checks['exact_inventory']=len(set(ids))==len(ids)==rules['parts'] and len(initial_edges)==len(inv['initial_edges'])==rules['edges'] and all(a in ids and b in ids and a!=b for a,b in initial_edges.values())
    truthroot=folder/Path(meta['truth_inventory']).parent
    with np.load(truthroot/inv['body_states_file'],allow_pickle=False) as raw:initial=raw['states']
    checks['initial_states']=initial.shape==(len(ids),13) and finite(initial)
    names=expected_names(read(HERE.parent/'inputs/frozen_geometry.json'),rules.get('removed',[]));checks['case_named_inventory']={x.rsplit('/',1)[-1] for x in ids}==names
    selected=None;binding=[];target=None
    if args.mode=='pick':
        selected=read(folder/'online/selection.json');candidate=selected.get('candidate')
        checks['unique_premotion_identity']=False;checks['sensor_supported_localization']=False;checks['selected_upper_depth_1mm']=False
        if candidate is not None:
            poly=candidate['image_polygon'];binding=initial_matches(poly,inv['projected_top_faces'])
            matches=[x for x in binding if x['iou']>=p['identity_binding']['iou_minimum']]
            checks['unique_premotion_identity']=selected['measurement_time_s']==inv['measurement_time_s'] and len(matches)==1 and matches[0]['id'] in ids and selected['frame_id']==inv['camera_frame_id'] and candidate['decision']=='present'
            if checks['unique_premotion_identity']:
                target=matches[0]['id'];state=initial[ids.index(target)];table=meta['table_pose_world_wxyz'];world_to_table=rotation(table[3:7]).T
                heights=[float((world_to_table@(state[:3]+rotation(state[3:7])@np.array([0,0,z])-np.asarray(table[:3])))[2]) for z in [.0096,.0113]]
                depth=selected.get('supported_upper_surface_m');checks['selected_upper_depth_1mm']=depth is not None and math.isfinite(depth) and min(abs(depth-z) for z in heights)<=.001
            checks['sensor_supported_localization']=selected['local_depth_support']['supported'] is True and selected['engineering_envelopes']==science['engineering_envelopes']
    safety_details=None
    if args.mode=='pick':
        view_checks,safety_details=audit_safety(folder,selected,meta,geometry,science)
        ray_certificate=view_checks.pop('clearance_all_nonself_have_positive_witness',None);checks.update(view_checks);safety_details['full_positive_ray_certificate_passed']=ray_certificate
        expected_admission={'policy':'simulation_only_finger_contact_guarded','visual_clearance_certified':False,'hardware_use':False,'measured_swept_clearance_passed':bool(selected['clearance']['passed']),'swept_space_status':'UNCERTIFIED_UNKNOWN','known_robot_q_authorization':science['pregrasp_init']['authorization_sha256']}
        checks['uncertified_admission_record_preserved']=selected['admission']==meta['admission']==expected_admission
        checks['minimum_nominal_side_overlap']=selected.get('candidate') is None or selected['nominal_body_side_overlap_m']>=.002
    observer=read(folder/meta['observer_metadata']);source_metadata=folder/'evaluation_truth/contact_observations/metadata.json'
    if source_metadata.exists():
        source_observer=read(source_metadata)
        checks['source_observer_same_SI_filters']=source_observer['stage_meters_per_unit']==observer['stage_meters_per_unit'] and source_observer['observation_setting']['after'] is False and set(source_observer['requested_all_scene_actor_filters'])==set(observer['requested_all_scene_actor_filters']) and set(source_observer['requested_standalone_static_filters'])==set(observer['requested_standalone_static_filters'])
        observer['resolved_views'].update(source_observer['resolved_views'])
    resolved=observer['resolved_views'];expected={c['body_path'] for c in geometry['fingers'].values()}
    requested=set(observer['requested_all_scene_actor_filters'])|set(observer['requested_standalone_static_filters'])
    checks['contact_filters_complete']=set(resolved)==({'left','right','source'} if source_metadata.exists() else {'left','right'}) and all(resolved[label]['sensor_paths']==[geometry['fingers'][label]['body_path']] for label in ['left','right']) and set(ids)|expected<=requested and all(v['sensor_count']==1 and v['max_contact_data_count']==1024 and len(filter_paths(v))==len(set(filter_paths(v))) and set(filter_paths(v))==requested for v in resolved.values())
    checks['contact_SI_processing']=observer['stage_meters_per_unit']==1 and observer['observation_setting']['after'] is False
    if args.mode=='pick' and selected.get('candidate') is None and meta['steps_executed']==0:
        checks['nonempty_pick_coverage']=False
        return {'checks':checks,'coverage_status':'ABSTAIN','geometry_safety':safety_details,'steps':0,'target_binding':{'target_id':None,'eligible_matches':[],'evaluation_only':True},'metrics':{'measured_contact_steps':0,'force_peak_N':None},'reciprocal_contact_status':'UNTESTED_NO_SELECTED_TARGET','online_hold_status':{'status':'UNKNOWN','transfer_authorized':False}}
    contact_protocol=read(HERE/'contact_protocol.json');maxsteps=3600;previous=None;first=None;seen=0;detached=None;reference=None;relative_max_m=relative_max_rad=0.;rise=None;non_target_pos=non_target_angle=0.;peaks={'left':0.,'right':0.};point_count=0;point_flat=0.;point_dot=1.;signs={1,-1};positive_count=0;positive_step=None;grasp_commands=None;lift_origin=None;lift_final=None;hold_start=None;hold_end=None;all_checks=True;failures={};last_edges=set(initial_edges);final=None
    q0=np.asarray(meta['initial_joint_positions']);finger_ids=meta['finger_joint_indices'];arm_ids=meta['arm_joint_indices'];limits=np.asarray(meta['joint_limits']);target_index=ids.index(target) if target is not None else None
    on=iter(rows(folder/meta['online_trace']));tr=iter(rows(folder/meta['truth_trace']));contact_trace=iter(rows(folder/'contact_observations/trace.jsonl'));source_trace=iter(rows(folder/'evaluation_truth/contact_observations/trace.jsonl')) if source_metadata.exists() else None
    while True:
        row=next(on,None);gt=next(tr,None);contact_row=next(contact_trace,None);source_row=next(source_trace,None) if source_trace is not None else None
        if row is None or gt is None:
            checks['same_online_truth_length']=row is None and gt is None and contact_row is None and source_row is None;break
        check_time(deadline);seen+=1;frame={};dt=meta['dt_s'];phase=row['phase']
        frame['fresh_exact_step_clock']=row['step']==gt['step']==seen and abs(row['time_s']-gt['time_s'])<=1e-7 and (previous is None or abs(row['time_s']-previous['time_s']-dt)<=1e-7)
        frame['clock_dt']=abs(row['physics_dt_s']-dt)<=1e-12
        frame['finger_raw_step_association']=contact_row is not None and contact_row['step']==seen and abs(contact_row['physics_time_after_s']-row['time_s'])<=1e-7 and set(row['contacts'])==set(contact_row['bodies'])=={'left','right'} and all(contact_file(row['contacts'][label])==contact_file(contact_row['bodies'][label]) for label in ['left','right'])
        if source_trace is not None:
            frame['source_raw_step_association']=source_row is not None and source_row['step']==seen and abs(source_row['physics_time_after_s']-row['time_s'])<=1e-7 and contact_file(gt['contacts']['source'])=='evaluation_truth/'+contact_file(source_row['bodies']['source'])
        frame['known_phase']=phase in (['control'] if args.mode=='control' else ['initial','perceive','approach','final_approach','close','lift','hold','abstain'])
        with np.load(truthroot/gt['state_file'],allow_pickle=False) as raw:state=raw['states']
        frame['finite_states']=state.shape==initial.shape and finite(state) and not gt['nonfinite']
        edges=set(gt['edges']);lost=set(initial_edges)-edges
        frame['no_new_or_duplicate_edges']=len(edges)==len(gt['edges']) and edges<=set(initial_edges)
        frame['native_events_match_lost_edges']={e['id'] for e in gt['break_events']}==last_edges-edges and all(initial_edges.get(e['id'])==(e['a'],e['b']) for e in gt['break_events'])
        if args.mode=='control':frame['stationary_graph_unchanged']=not lost
        elif target is not None:
            frame['no_collateral_native_loss']=all(target in initial_edges[e] for e in lost)
            singleton=not any(target in initial_edges[e] for e in edges)
            if singleton and detached is None:detached=seen;reference=relative_pose(row['tcp_pose_world_wxyz'],state[target_index])
            if detached is not None:
                frame['remains_singleton']=singleton
                position,orient=relative_pose(row['tcp_pose_world_wxyz'],state[target_index]);relative_max_m=max(relative_max_m,float(np.linalg.norm(position-reference[0])));relative_max_rad=max(relative_max_rad,float(np.arccos(np.clip((np.trace(reference[1].T@orient)-1)/2,-1,1))))
        other=[i for i in range(len(ids)) if i!=target_index];position=float(np.linalg.norm(state[other,:3]-initial[other,:3],axis=1).max());dot=abs(np.sum(initial[other,3:7]*state[other,3:7],axis=1));length=np.linalg.norm(initial[other,3:7],axis=1)*np.linalg.norm(state[other,3:7],axis=1);angle=float((2*np.arccos(np.clip(dot/length,0,1))).max())
        non_target_pos=max(non_target_pos,position);non_target_angle=max(non_target_angle,angle);frame['non_target_pose_guard']=position<=.002 and angle<=math.radians(2)
        q=np.asarray(row['q']);qd=np.asarray(row['qdot']);command=np.asarray(row['joint_commands']);tcp=np.asarray(row['tcp_pose_world_wxyz'])
        frame['finite_robot']=finite(q) and finite(qd) and finite(command) and finite(tcp)
        frame['joint_asset_limits']=q.shape==limits[:,0].shape and bool(np.all(q>=limits[:,0]) and np.all(q<=limits[:,1]))
        frame['actual_joint_speed']=bool(np.max(abs(qd[arm_ids]))<=1 and np.max(abs(qd[finger_ids]))<=.002)
        frame['finger_travel']=bool(np.max(abs(command[finger_ids]-q0[finger_ids]))<=.004002 and np.max(abs(q[finger_ids]-q0[finger_ids]))<=.004002)
        if previous is not None:
            old_command=np.asarray(previous['joint_commands']);delta=command-old_command;float_allow=2*np.finfo(np.float32).eps*max(float(abs(command[arm_ids]).max()),float(abs(old_command[arm_ids]).max()),1e-4);finger_allow=2*np.finfo(np.float32).eps*max(float(abs(command[finger_ids]).max()),float(abs(old_command[finger_ids]).max()),1e-4)
            frame['joint_command_steps']=bool(np.max(abs(delta[arm_ids]))<=.005+float_allow and np.max(abs(delta[finger_ids]))<=.001*dt+finger_allow)
            speed=float(np.linalg.norm(tcp[:3]-np.asarray(previous['tcp_pose_world_wxyz'])[:3])/dt)
            cap={'approach':.03,'final_approach':.003,'lift':.002,'hold':.002,'close':.003}.get(phase)
            frame['actual_tcp_speed']=cap is None or speed<=cap
            target_tcp=np.asarray(row['tcp_target_table_wxyz']);old_target=np.asarray(previous['tcp_pose_table_wxyz'] if phase in ['final_approach','lift'] and previous['phase']!=phase else previous['tcp_target_table_wxyz']);target_delta=target_tcp[:3]-old_target[:3]
            command_cap={'approach':.02,'final_approach':.002,'lift':.001,'hold':0.,'close':0.}.get(phase)
            frame['tcp_command_rate']=command_cap is None or np.linalg.norm(target_delta)<=command_cap*dt+1e-9
            if phase in ['lift','hold']:
                frame['straight_table_Z_lift']=abs(target_delta[0])<=1e-9 and abs(target_delta[1])<=1e-9 and target_delta[2]>=-1e-9 and angle_between(target_tcp[3:7],old_target[3:7])<=1e-6
            frame['orientation_command_rate']=angle_between(target_tcp[3:7],old_target[3:7])<=science['motion']['orientation_command_speed_rad_s']*dt+1e-6
        if args.mode=='control':frame['control_commands_stationary']=first is None or row['joint_commands']==first['joint_commands']
        if phase in ['final_approach','close','lift','hold']:
            actual_tcp=np.asarray(row['tcp_pose_table_wxyz']);target_tcp=np.asarray(row['tcp_target_table_wxyz'])
            frame['tcp_tracking']=bool(finite(actual_tcp) and finite(target_tcp) and np.linalg.norm(actual_tcp[:3]-target_tcp[:3])<=.0005 and angle_between(actual_tcp[3:7],target_tcp[3:7])<=math.radians(1))
        rawchecks,detail,_,_=contact_frame(folder,row,gt,observer,geometry,contact_protocol,target);frame.update(rawchecks);signs &= set(detail['possible_signs']);point_count+=detail['loaded_observations'];point_flat=max(point_flat,detail['max_flat_distance_m'])
        frame['unexpected_early_finger_contact_absent']=phase not in ['control','approach','final_approach'] or max(detail['peak_N'].values())<=1e-6
        if detail['min_outward_dot'] is not None:point_dot=min(point_dot,detail['min_outward_dot'])
        for label in peaks:peaks[label]=max(peaks[label],detail['peak_N'][label])
        both=all(detail['peak_N'][x]>=1.5 for x in peaks);positive_count=positive_count+1 if both else 0
        if positive_count>=3 and positive_step is None:positive_step=seen;grasp_commands=command[finger_ids].copy()
        if positive_step is not None:frame['grasp_targets_held']=bool(np.array_equal(command[finger_ids],grasp_commands))
        if phase=='lift':
            if lift_origin is None:lift_origin=np.asarray(previous['tcp_pose_table_wxyz'][:3] if previous is not None else row['tcp_target_table_wxyz'][:3])
            lift_final=np.asarray(row['tcp_target_table_wxyz'][:3])
        if phase in ['lift','hold']:frame['force_trigger_before_lift']=positive_step is not None
        if phase=='hold':hold_start=row['time_s'] if hold_start is None else hold_start;hold_end=row['time_s']
        frame['no_capture_abort']=not row['stop_reasons']
        for name,value in frame.items():
            if not value:all_checks=False;failures[name]=failures.get(name,0)+1
        if first is None:first=row
        previous=row;last_edges=edges;final=state
        if seen>maxsteps:raise ValueError('Frozen measured step cap exceeded')
    checks['all_measured_frame_guards']=all_checks;checks['global_signed_vector_convention']=bool(signs) and (args.mode=='control' or len(signs)==1)
    checks['bounded_nonempty_steps']=0<seen<=maxsteps
    checks['controller_record_complete']=meta['steps_executed']==seen and meta['controller_status']==('control_completed' if args.mode=='control' else 'bounded_sequence_completed')
    terminal_other=[i for i in range(len(ids)) if i!=target_index]
    checks['non_target_terminal_speeds']=final is not None and bool(np.max(np.linalg.norm(final[terminal_other,7:10],axis=1))<=.02 and np.max(np.linalg.norm(final[terminal_other,10:13],axis=1))<=.2)
    if args.mode=='control':checks['full_stationary_3600']=seen==3600
    else:
        rise=float(final[target_index,2]-initial[target_index,2]) if final is not None and target_index is not None else None
        checks['target_detached_singleton']=detached is not None
        checks['detachment_after_grasp_trigger']=detached is not None and positive_step is not None and detached>=positive_step
        checks['commanded_straight_5mm_lift']=lift_origin is not None and bool(np.allclose(lift_final-lift_origin,[0,0,.005],atol=1e-8,rtol=0))
        checks['target_rise_4mm']=rise is not None and rise>=.004
        checks['held_relative_transform']=detached is not None and relative_max_m<=.001 and relative_max_rad<=math.radians(3)
        checks['final_hold_250ms']=hold_start is not None and hold_end-hold_start+meta['dt_s']>=.25-1e-7 and previous['phase']=='hold'
        checks['positive_force_trigger']=positive_step is not None
    return {'checks':checks,'geometry_safety':safety_details,'frame_failure_counts':failures,'steps':seen,'target_binding':{'target_id':target,'eligible_matches':[x for x in binding if x['iou']>=.5],'evaluation_only':True},'metrics':{'first_singleton_step':detached,'target_rise_m':rise,'held_translation_max_m':relative_max_m if detached else None,'held_angle_max_rad':relative_max_rad if detached else None,'non_target_translation_max_m':non_target_pos,'non_target_angle_max_rad':non_target_angle,'force_peak_N':peaks,'first_force_trigger_step':positive_step,'loaded_point_observations':point_count,'max_loaded_flat_distance_m':point_flat if point_count else None,'min_loaded_outward_dot':point_dot if point_count else None},'reciprocal_contact_status':'MEASURED' if target is not None and 'source' in resolved else 'UNMEASURED_ZERO_LOAD_CONTROL' if args.mode=='control' else 'UNMEASURED','online_hold_status':read(folder/'online/held_association.json') if (folder/'online/held_association.json').exists() else {'status':'UNKNOWN','transfer_authorized':False}}

def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--case',choices=['I'],required=True);parser.add_argument('--mode',choices=['control','pick'],required=True)
    for key in ['input','output']:parser.add_argument('--'+key,type=Path,required=True)
    for key in ['predecessor-control','prior-case-supervisor']:parser.add_argument('--'+key,type=Path)
    args=parser.parse_args();result={'case':args.case,'mode':args.mode,'proceed_gate_passed':False,'protocol_sha256':sha(HERE.parent/'protocol.json'),'evaluation_protocol_sha256':sha(HERE/'protocol.json')}
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    p=read(HERE/'protocol.json');science=read(HERE.parent/'protocol.json');supervisor=read(args.input/'supervisor.json');prior=float(supervisor['prior_case_wall_seconds']);capture=float(supervisor['capture_wall_seconds']);limit=float(science['budget']['capture_plus_independent_audit_seconds_per_case'])
    def stop(*_):raise TimeoutError('Frozen cumulative case budget exhausted')
    signal.signal(signal.SIGALRM,stop)
    try:
        if limit!=p['case_budget_seconds']:raise ValueError('Scientific/evaluator case budgets differ')
        remaining=limit-prior-capture
        if not math.isfinite(prior+capture) or min(prior,capture)<0 or remaining<=0:raise ValueError('Invalid cumulative budget')
        signal.setitimer(signal.ITIMER_REAL,max(.001,remaining-(time.monotonic()-STARTED)));deadline=STARTED+remaining
        if sha(HERE.parent/'protocol.json')!=p['capture_protocol_sha256']:raise ValueError('Frozen scientific protocol changed')
        if sha(HERE.parent.parent/'stage2_exposed_tip_20261025/model_config.json')!=science['physics']['geometry_model_sha256']:raise ValueError('Frozen exposed model changed')
        for name,digest in p['inputs_sha256'].items():
            if sha(HERE.parent/'inputs'/name)!=digest:raise ValueError('Frozen input changed: '+name)
        for name,digest in p['helpers_sha256'].items():
            if sha(HERE/name)!=digest:raise ValueError('Frozen helper changed: '+name)
        predecessor_checks={};clockpath=args.prior_case_supervisor or HERE.parent/'inputs/prior_case_pipeline_supervisor.json';clock=read(clockpath)
        predecessor_checks['retained_cost_charged']=clock['case']=='I' and clock['within_budget'] is True and clock['cumulative_case_seconds']==prior
        if args.mode=='control':
            predecessor_checks['fresh_control_no_old_predecessor']=args.predecessor_control is None and sha(clockpath)==science['prior_case_clock']['source_sha256'] and prior==science['prior_case_clock']['prior_case_seconds']
        else:
            path=args.predecessor_control;prev=read(path);control_clock=path.parent/'predecessor_control_pipeline_supervisor.json'
            predecessor_checks['fresh_same_protocol_control']=prev['case']=='I' and prev['mode']=='control' and prev['proceed_gate_passed'] is True and prev['stationary_guard_passed'] is True and prev['protocol_sha256']==result['protocol_sha256']
            predecessor_checks['exact_current_control_clock']=sha(clockpath)==sha(control_clock) and clock['mode']=='control' and clock['proceed_gate_passed'] is True and clock['audit_sha256']==sha(path)
            result['predecessor_control_sha256']=sha(path)
        result['prior_case_supervisor_sha256']=sha(clockpath)
        marker=read(args.input/'capture_complete.json') if (args.input/'capture_complete.json').exists() else {}
        if supervisor['capture_completed'] is not True or marker.get('capture_completed') is not True:result.update(status='INCOMPLETE_CAPTURE',scientific_claims='No extraction acceptance; incomplete capture and any partial motion/contact evidence remain unverified',capture_controller_status=marker.get('controller_status','NOT_RECORDED'),capture_failure=read(args.input/'failure.json') if (args.input/'failure.json').exists() else None)
        else:
            result.update(audit(args,p,science,deadline));result['checks']['completion_marker_case_mode']=marker['case']==args.case and marker['mode']==args.mode;result['checks'].update(predecessor_checks);result['checks']['cumulative_case_wall']=prior+capture+time.monotonic()-STARTED<=limit
            result.update(status='independent_audit_complete',proceed_gate_passed=all(result['checks'].values()))
            result['positive_ray_certificate_passed']=result.get('geometry_safety',{}).get('full_positive_ray_certificate_passed') if result.get('geometry_safety') else None
            result['physics_extraction_passed']=args.mode=='pick' and result['proceed_gate_passed'];result['stationary_guard_passed']=args.mode=='control' and result['proceed_gate_passed'];result['transfer_authorized']=False
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result.update(admission_policy='UNKNOWN_PATH_FINGER_CONTACT_GUARDED',simulation_only=True,ray_certification_required_for_this_baseline=False,unknown_space_is_free=False,whole_arm_contact_coverage='UNMEASURED',case_limit_seconds=limit,prior_case_wall_seconds=prior,capture_wall_seconds=capture,audit_wall_seconds=time.monotonic()-STARTED,cumulative_case_seconds=prior+capture+time.monotonic()-STARTED,scope=p['scope'],global_geometry_passed=False)
        args.output.mkdir(parents=True,exist_ok=True);(args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False,default=json_default)+'\n');(args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'case':args.case,'mode':args.mode,'proceed_gate_passed':result['proceed_gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')

if __name__=='__main__':main()

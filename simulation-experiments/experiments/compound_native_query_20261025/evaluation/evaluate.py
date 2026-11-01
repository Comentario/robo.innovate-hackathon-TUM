"""Independent sparse queries of one fixed cooked compound; no contact promotion."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

STARTED=time.monotonic()
import numpy as np
from query_reference import reference_mesh,reference_valid,ray_reference,transform,direction
from geometry_reference import rotation,angle_between,surface_distance
from union_reference import outside_winding

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def classification(path,targets,body):return 'compound_target' if path in targets else 'white_finger' if path.startswith(body+'/collisions/') else 'other'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['input','output','stl','config','reference','compound','offline-audit','baseline-metadata','baseline-geometry','capture-protocol']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    protocol=read(HERE/'protocol.json');supervisor=read(args.input/'supervisor.json')
    result={'schema':protocol['schema'],'tested_clear_features_passed':False,'contact_authorized':False,'proceed_gate_passed':False,'protocol_sha256':sha(HERE/'protocol.json')}
    def stop(*_):raise TimeoutError('Fixed capture-plus-audit180s exhausted; no retry')
    signal.signal(signal.SIGALRM,stop)
    capture_wall=float(supervisor['capture_wall_seconds']);prior_wall=protocol['charged_prior_active_seconds'];remaining=protocol['capture_plus_audit_wall_s']-prior_wall-capture_wall-(time.monotonic()-STARTED)
    if not math.isfinite(capture_wall) or capture_wall<0 or remaining<=0:raise ValueError('Invalid actual capture budget')
    signal.setitimer(signal.ITIMER_REAL,remaining)
    try:
        for path,key in [(args.stl,'stl_sha256'),(args.config,'proxy_config_sha256'),(args.reference,'reference_sha256'),(args.compound,'compound_sha256'),(args.offline_audit,'offline_audit_sha256'),(args.capture_protocol,'capture_protocol_sha256'),(args.baseline_metadata,'baseline_metadata_sha256'),(args.baseline_geometry,'baseline_geometry_sha256')]:
            if sha(path)!=protocol[key]:raise ValueError('Frozen input changed: '+str(path))
        for name,digest in protocol['helpers_sha256'].items():
            if sha(HERE/name)!=digest:raise ValueError('Frozen reference helper changed')
        if not supervisor['observation_completed']:
            result.update(status='INCOMPLETE_CAPTURE',raw_queries=read(args.input/'queries.json') if (args.input/'queries.json').exists() else [],target_geometry='UNTESTED',supervisor=supervisor,restoration_raw=read(args.input/'property_restoration.json') if (args.input/'property_restoration.json').exists() else 'NOT_RECORDED')
        else:
            config=read(args.config);reference=read(args.reference);capture=read(args.capture_protocol);report=read(args.input/'query_report.json');authored=read(args.input/'compound_authoring.json');queries=read(args.input/'queries.json');props=read(args.input/'property_checks.json');cooks=read(args.input/'cook_results.json')
            checks={'offline_candidate_pin_passed':read(args.offline_audit)['offline_candidate_passed'] is True}
            checks['complete_zero_motion']=report['observation_complete'] and report['measured_postassembly_physics_steps']==0 and report['queries_do_not_move_actors'] and report['initial']==report['terminal'] and report['graph_unchanged']
            checks['full_source_PGS32_4']=len(set(report['source_parts']))==len(report['source_parts'])==301 and len(set(report['native_connections']))==len(report['native_connections'])==930 and len(report['runtime_source32_4'])==300 and all(v==[32,4] for v in report['runtime_source32_4'].values()) and bool(report['physics_scenes']) and all(s['solver']=='PGS' and s['enable_scene_query_support'] is True for s in report['physics_scenes']) and report['scene_query_support_runtime'] is True
            checks['native_binary_dt_epsilon']=report['native_core_sha256']==capture['input_sha256']['.deps/bricksim/core.cpython-311-x86_64-linux-gnu.so'] and report['dt_s']==capture['source']['dt_s'] and report['OSQP_EPSILON']==capture['source']['OSQP_EPSILON']
            checks['nominal_q']=bool(np.allclose(report['initial']['q'],[protocol['nominal_joint_positions']],atol=protocol['nominal_joint_tolerance'],rtol=0) and np.isfinite(report['initial']['qdot']).all())
            factory=report['factory'];checks['only_declared_scene_changes']=factory['before']['solver_type']==1 and factory['after']=={**factory['before'],'solver_type':0} and factory['enable_scene_query_support_configured_before'] is False and factory['enable_scene_query_support_configured_after'] is True and factory['full_sim_cfg_only_declared_changes_verified'] is True and factory['changed_paths']==['physx.solver_type','enable_scene_query_support']
            byid={q['id']:q for q in queries};checks['unique250']=len(byid)==len(queries)==250
            checks['all_callback_counts']=all(q['callback_count']==len(q['hits']) and (q['api_return_bool']==bool(q['hits']) if q['kind']=='ray' else q['api_return_count']==len(q['hits'])) for q in queries)
            control=capture['query_control'];pos,neg,inside,outside=[byid[k] for k in ['control_hit','control_miss','control_inside','control_outside']]
            controlhits=[h for h in pos['hits'] if h['collision']==control['path']]
            checks['four_controls']=len(controlhits)==1 and abs(controlhits[0]['distance_m']-control['expected_hit_distance_m'])<=control['distance_tolerance_m'] and np.max(abs(np.asarray(controlhits[0]['normal_world'])-[0,0,1]))<=control['normal_component_tolerance'] and not neg['hits'] and len(inside['hits'])==1 and inside['hits'][0]['collision']==control['path'] and not outside['hits']
            checks['control_probe_contract']=all(np.allclose(q[field],expected,atol=1e-8,rtol=0) for q,field,expected in [(pos,'origin_world_m',control['ray_hit_origin_m']),(neg,'origin_world_m',np.asarray(control['ray_hit_origin_m'])+control['miss_offset_world_m']),(inside,'center_world_m',control['center_world_m']),(outside,'center_world_m',np.asarray(control['center_world_m'])+control['miss_offset_world_m'])]) and all(q['direction_world']==control['ray_direction'] and q['length_m']==control['ray_length_m'] for q in [pos,neg]) and all(q['radius_m']==control['overlap_radius_m'] for q in [inside,outside])
            checks.update(property_checks(props,read(args.baseline_metadata),read(args.baseline_geometry),protocol))
            restoration=read(args.input/'property_restoration.json');checks.update(restoration_checks(restoration,read(args.baseline_metadata),protocol));checks.update(targeted_write_checks(restoration))
            checks['source_property_inventory_matches_observed_actors']=set(props['initial']['source'])==set(report['initial']['source'])
            checks['authored_input_pins']=authored['candidate_sha256']==protocol['compound_sha256'] and authored['offline_audit_sha256']==protocol['offline_audit_sha256'] and authored['offline_manifest_sha256']==capture['offline_approval']['manifest_sha256'] and authored['registration_reference_sha256']==protocol['reference_sha256']
            allids={'control_hit','control_miss','control_inside','control_outside'};tips={};cookdiag={};quality={}
            for label in ['left','right']:
                body='/World/envs/env_0/Robot/fr3_'+label+'finger';targets=set(authored['tips'][label]['target_paths']);frame=report['frames'][label];matrix=np.asarray(frame['world_from_finger']);physical=np.asarray(frame['physics_body_link_pose_world_wxyz']);usd=np.asarray(frame['USD_pose_world_wxyz'])
                checks[label+'_48_target_paths']=len(targets)==48 and all(p.startswith(body+'/collisions/mesh_3/part_') for p in targets)
                checks[label+'_frame']=bool(np.isfinite(matrix).all() and np.linalg.norm(physical[:3]-usd[:3])<=capture['frame_verification']['physics_vs_USD_position_m'] and angle_between(physical[3:],usd[3:])<=capture['frame_verification']['physics_vs_USD_orientation_rad'] and np.allclose(matrix[3,:3],usd[:3],atol=1e-8,rtol=0) and np.allclose(matrix[:3,:3],rotation(usd[3:]).T,atol=1e-6,rtol=0))
                vertices,tri,R=reference_mesh(args.stl,config,label);valid=reference_valid(vertices,tri,protocol);checks[label+'_reference_valid']=valid
                checks[label+'_authored_cells'],cookdiag[label]=authored_and_cooked(authored,cooks,label,read(args.compound),config,read(args.baseline_geometry))
                lo,hi=vertices.min(axis=0),vertices.max(axis=0);specs=[]
                for ix,x in enumerate(capture['contact_ray_grid']['hand_x_offsets_m']):
                    for iz,z in enumerate(capture['contact_ray_grid']['hand_z_offsets_m']):
                        local=transform(transform(np.asarray(reference['coupon_center_hand_m'])+[x,0,z],report['world_from_hand']),np.linalg.inv(matrix));local[1]=lo[1]-.02 if label=='left' else hi[1]+.02
                        specs.append((f'{label}_grid_{ix}_{iz}',local,np.array([0,1 if label=='left' else -1,0]),float(hi[1]-lo[1]+.04)))
                for axis in range(3):
                    for sign in [-1,1]:
                        origin=(lo+hi)/2;origin[axis]=lo[axis]-.02 if sign==1 else hi[axis]+.02;d=np.zeros(3);d[axis]=sign;specs.append((f'{label}_bbox_{axis}_{sign}',origin,d,float(hi[axis]-lo[axis]+.04)))
                rays=[];probeok=True;hitok=True;tol=protocol['probe_position_tolerance_m']
                for identity,origin,d,length in specs:
                    allids.add(identity);q=byid[identity];probeok=probeok and q['kind']=='ray' and q['tip']==label and np.linalg.norm(np.asarray(q['origin_finger_m'])-origin)<=tol and np.linalg.norm(np.asarray(q['origin_world_m'])-transform(origin,matrix))<=tol and np.linalg.norm(np.asarray(q['direction_world'])-direction(d,matrix))<=protocol['probe_direction_tolerance'] and abs(q['length_m']-length)<=tol
                    ref=ray_reference(origin,d,length,vertices,tri,protocol);targethits=[]
                    for i,h in enumerate(q['hits']):
                        p=np.asarray(h['position_world_m']);n=np.asarray(h['normal_world']);distance=h['distance_m'];hitok=hitok and bool(np.isfinite([*p,*n,distance]).all() and 0<=distance<=length+1e-5 and np.linalg.norm(p-(np.asarray(q['origin_world_m'])+distance*np.asarray(q['direction_world'])))<=protocol['ray_hit_position_and_distance_tolerance_m'] and abs(np.linalg.norm(n)-1)<=protocol['unit_normal_tolerance'])
                        if h['collision'] in targets:hitok=hitok and h['rigid_body']==body;targethits.append((i,h))
                    nearest=min(targethits,key=lambda x:x[1]['distance_m']) if targethits else None;nearestany=min(enumerate(q['hits']),key=lambda x:x[1]['distance_m']) if q['hits'] else None
                    flagged=ref.get('edge_sensitive',False) or ref.get('grazing',False);error=nearest[1]['distance_m']-ref['distance_m'] if nearest and ref['hit'] else None
                    rays.append({'id':identity,'reference':ref,'hit_parity':bool(nearest)==ref['hit'],'nearest_target_hit':{'raw_index':nearest[0],**nearest[1]} if nearest else None,'nearest_any_hit':{'raw_index':nearestany[0],**nearestany[1]} if nearestany else None,'target_hit_count':len(targethits),'firsthit_error_m':error,'distance_status':'UNRESOLVED_EDGE_OR_GRAZING' if flagged else 'clear_reference_hit' if ref['hit'] else 'reference_miss','all_raw_hit_paths':[h['collision'] for h in q['hits']],'classes':dict(Counter(classification(h['collision'],targets,body) for h in q['hits']))})
                overlaps=[];f=config['fidelity'];reg=config['registration'][label]
                for x in f['bore_x_cad_mm']:
                    for k in range(f['bore_witnesses_per_x']):
                        identity=f'{label}_bore_{x}_{k}';allids.add(identity);q=byid[identity];offset=np.zeros(2) if k==0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)]);point=np.r_[x,np.asarray(f['bore_center_cad_yz_mm'])+offset]*config['stl_unit_m']@R.T+reg['translation_m']
                        probeok=probeok and q['kind']=='overlap' and q['tip']==label and np.linalg.norm(np.asarray(q['center_finger_m'])-point)<=tol and np.linalg.norm(np.asarray(q['center_world_m'])-transform(point,matrix))<=tol and q['radius_m']==capture['bore_overlaps']['radius_m']
                        clear=surface_distance(point,vertices,tri);free,winding=outside_winding(point,vertices,tri);paths=[h['collision'] for h in q['hits']];hitok=hitok and all(h['rigid_body']==body for h in q['hits'] if h['collision'] in targets)
                        overlaps.append({'id':identity,'reference_free':bool(valid and free and clear>f['witness_reference_clearance_m'] and clear>q['radius_m']),'reference_clearance_m':clear,'reference_winding':winding,'target_hit_paths':[p for p in paths if p in targets],'all_raw_hit_paths':paths})
                checks[label+'_probe_contract']=probeok;checks[label+'_hit_data']=hitok;checks[label+'_27_reference_free_spheres']=len(overlaps)==27 and all(o['reference_free'] for o in overlaps)
                clear=[r for r in rays if r['distance_status']=='clear_reference_hit'];flagged=[r['id'] for r in rays if r['distance_status']=='UNRESOLVED_EDGE_OR_GRAZING']
                quality[label+'_96_parities']=len(rays)==96 and all(r['hit_parity'] for r in rays)
                quality[label+'_clear_firsthits_100um']=len(clear)>=1 and all(r['firsthit_error_m'] is not None and abs(r['firsthit_error_m'])<=protocol['maximum_clear_firsthit_error_m'] for r in clear)
                quality[label+'_27_no_target_overlaps']=len(overlaps)==27 and all(not o['target_hit_paths'] for o in overlaps)
                tips[label]={'rays':rays,'overlaps':overlaps,'clear_reference_hit_ids':[r['id'] for r in clear],'unresolved_distance_ids':flagged,'target_rays_with_hits':sum(r['target_hit_count']>0 for r in rays),'missing_CAD_hits':[r['id'] for r in rays if r['reference']['hit'] and not r['target_hit_count']],'unexpected_target_hits':[r['id'] for r in rays if not r['reference']['hit'] and r['target_hit_count']],'sphere_target_overlap_ids':[o['id'] for o in overlaps if o['target_hit_paths']]}
            checks['exact250_probe_ids']=set(byid)==allids;elapsed=time.monotonic()-STARTED;checks['total180s']=prior_wall+capture_wall+elapsed<=180
            result.update(status='query_audit_complete',integrity_checks={k:bool(v) for k,v in checks.items()},quality_checks={k:bool(v) for k,v in quality.items()},observation_integrity_passed=bool(all(checks.values())),tested_clear_features_passed=bool(all(checks.values()) and all(quality.values())),tips=tips,cooked_representation_diagnostics=cookdiag)
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);elapsed=time.monotonic()-STARTED;result.update(prior_charged_active_seconds=prior_wall,capture_wall_seconds=capture_wall,audit_wall_seconds=elapsed,cumulative_active_wall_seconds=prior_wall+capture_wall+elapsed,scope=protocol['scope']);args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');(args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'tested_clear_features_passed':result['tested_clear_features_passed'],'contact_authorized':False,'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


def property_checks(props,baseline,geometry,protocol):
    first,last=props['initial'],props['terminal']
    whiteok=True
    for label in ['left','right']:
        old={c['path']:c for c in geometry['fingers'][label]['colliders'] if not c['is_pad']};new={c['path']:c for c in first['white'][label]}
        whiteok=whiteok and set(old)==set(new)
        for path,row in new.items():
            whiteok=whiteok and path in old and set(row)==set(old[path]) and all(np.allclose(row[k],old[path][k],atol=protocol['white_geometry_match_tolerance_m'],rtol=0) if k in ('points_finger_m','bounds_finger_m') else row[k]==old[path][k] for k in row)
    return {'actual_properties_unchanged':props['unchanged'] is True and first==last,
        'robot_properties_match_B0':first['robot_matches_B0'] is True and first['robot']==baseline['initial_robot_properties'],
        'white_colliders_match_B0':first['white_matches_B0'] is True and bool(whiteok),
        'all301_source_properties':len(first['source'])==301 and all(set(actor)=={'masses','inertias','coms'} and all(np.isfinite(value).all() for value in actor.values()) for actor in first['source'].values())}


def restoration_checks(record,baseline,protocol):
    expected=baseline['initial_robot_properties'];names=record['body_names'];paths=record['link_paths'];before=record['before'];after=record['after'];n=len(names)
    mapping=n==len(expected['masses'][0]) and n>11 and names[10:12]==['fr3_leftfinger','fr3_rightfinger'] and paths==[['/World/envs/env_0/Robot/'+name for name in names]]
    nonfinger=[i for i in range(n) if i not in (10,11)]
    physical=['masses','coms','inertias'];actuators=['stiffnesses','dampings','effort_limits']
    compatible=set(before)==set(after)==set(expected) and all(np.asarray(before[k]).shape==np.asarray(expected[k]).shape for k in expected)
    unchanged_nonfingers=compatible and all(np.array_equal(np.asarray(before[k])[:,nonfinger],np.asarray(expected[k])[:,nonfinger]) for k in physical)
    unchanged_actuators=compatible and all(before[k]==expected[k] for k in actuators)
    return {'restoration_one_frozen_order':record['count']==1 and record['order']==record['completed_setters']==['set_masses','set_coms','set_inertias'],
        'restoration_reference_pin':record['reference_sha256']==protocol['reference_sha256'],
        'restoration_timing':record['timing']=='after_scene_reset_before_explicit_preassembly_step' and record['sim_reset_internal_initialization_precedes_restore'] is True,
        'restoration_finger_mapping':bool(mapping),'restoration_only_finger_properties_prechanged':bool(unchanged_nonfingers and unchanged_actuators),
        'restoration_exact_all6_B0_readback':after==expected,
        'restoration_no_q_or_qdot_change':record['q_before']==record['q_after'] and record['qdot_before']==record['qdot_after'] and bool(np.isfinite(record['q_after']).all() and np.isfinite(record['qdot_after']).all()),
        'restoration_no_physics_time_change':record['physics_time_before_s']==record['physics_time_after_s'] and math.isfinite(record['physics_time_before_s'])}


def targeted_write_checks(record):
    views=record['target_views'];expected=[];valid=set(views)=={'left','right'}
    for label,index in [('left',10),('right',11)]:
        path='/World/envs/env_0/Robot/fr3_'+label+'finger';v=views[label]
        valid=valid and v['path']==path and v['resolved_paths']==[path] and v['count']==1 and v['articulation_link_index']==index
        for state in ['before','after']:
            valid=valid and set(v[state])=={'masses','coms','inertias'} and all(np.asarray(v[state][k]).shape==shape and np.isfinite(v[state][k]).all() for k,shape in [('masses',(1,1)),('coms',(1,7)),('inertias',(1,9))])
    for setter,shape in [('set_masses',[1,1]),('set_coms',[1,7]),('set_inertias',[1,9])]:
        for label in ['left','right']:
            expected.append({'path':'/World/envs/env_0/Robot/fr3_'+label+'finger','setter':setter,'view_index':0,'shape':shape})
    return {'only_two_exact_finger_views':record['route']=='two_exact_finger_rigid_body_views' and bool(valid),
        'only_six_targeted_property_writes':record['targeted_writes']==expected}


def authored_and_cooked(authored,cooks,label,candidate,config,baseline_geometry):
    tip=authored['tips'][label];parts=tip['parts'];actual=cooks['tips'][label];cells={c['id']:c for c in candidate['cells']}
    body='/World/envs/env_0/Robot/fr3_'+label+'finger';parent=body+'/collisions/mesh_3'
    ok=set(parts)==set(actual)==set(cells) and len(parts)==48 and tip['disabled_stock_parent']==parent and tip['stock_parent_collision_enabled'] is False and tip['reference_STL_only'] is True
    reg=config['registration'][label];a=math.radians(reg['rotation_z_deg']);R=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
    pad=next(c for c in baseline_geometry['fingers'][label]['colliders'] if c['is_pad']);rows=[]
    for identity,c in cells.items():
        p=parts[identity];cooked=actual[identity];v=np.asarray(p['vertices_finger_m']);expected=np.asarray(c['vertices_mm'])*config['stl_unit_m']@R.T+reg['translation_m'];path=parent+'/part_'+identity
        good=p['path']==path and p['collision_enabled'] is True and np.allclose(v,expected,atol=config['visual_registration_match_m'],rtol=0) and p['triangles']==c['triangles'] and p['approximation']=='convexHull' and p['hullVertexLimit']==255 and p['physics_material_path']==pad['physics_material_path'] and np.allclose(p['transform_finger'],np.eye(4),atol=1e-9,rtol=0)
        good=good and cooked['path']==path and cooked['result_valid'] is True and cooked['hull_count']==len(cooked['hulls'])==1
        hullrows=[]
        for h in cooked['hulls']:
            hv=np.asarray(h['vertices_m'],float);polygons=h['polygons'];finite=bool(np.isfinite(hv).all() and all(np.isfinite(poly['plane']).all() for poly in polygons))
            valid=finite and hv.ndim==2 and hv.shape[1]==3 and h['vertex_count']==len(hv) and 4<=len(hv)<=255 and h['polygon_count']==len(polygons) and 4<=len(polygons)<=255 and all(len(poly['indices'])>=3 and all(isinstance(i,int) and 0<=i<len(hv) for i in poly['indices']) for poly in polygons)
            good=good and valid
            hullrows.append({'vertex_count':h['vertex_count'],'polygon_count':h['polygon_count'],'finite_valid_indices':valid,'bounds_delta_from_authored_m':float(np.max(abs(np.array([hv.min(axis=0),hv.max(axis=0)])-np.array([v.min(axis=0),v.max(axis=0)])))) if finite and len(hv) else None})
        rows.append({'id':identity,'passed':bool(good),'raw_cook_result':cooked['result'],'hull_count':cooked['hull_count'],'hulls':hullrows});ok=ok and good
    ok=ok and set(tip['target_paths'])=={p['path'] for p in parts.values()}
    return bool(ok),{'cells':rows,'meaning':'Actual returned counts/bounds only. No plane-halfspace identity or global cooked-fidelity assertion.'}


if __name__=='__main__':main()

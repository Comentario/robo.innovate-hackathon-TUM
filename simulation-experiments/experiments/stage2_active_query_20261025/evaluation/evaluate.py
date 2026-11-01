"""Independent active-shape observations, never promotion of old G or contact."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time

import numpy as np
from geometry_reference import rotation,surface_distance,angle_between
from union_reference import outside_winding

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def transform(point,matrix):return (np.r_[point,1.]@np.asarray(matrix))[:3]
def direction(vector,matrix):
    d=(np.r_[vector,0.]@np.asarray(matrix))[:3]
    return d/np.linalg.norm(d)


def hit_class(path,target):
    if path==target:return 'target_pad'
    body=target.rsplit('/collisions/',1)[0]
    if path.startswith(body+'/collisions/'):return 'white_finger'
    return 'other'


def reference_mesh(stl,config,label):
    raw=stl.read_bytes();count=struct.unpack_from('<I',raw,80)[0]
    if len(raw)!=84+50*count:raise ValueError('Unexpected frozen STL')
    triangles=np.asarray([list(struct.iter_unpack('<fff',raw[84+50*i+12:84+50*i+48])) for i in range(count)])
    v,indices=np.unique(triangles.reshape(-1,3),axis=0,return_inverse=True);tri=indices.reshape(-1,3)
    r=config['registration'][label];a=math.radians(r['rotation_z_deg']);R=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
    return v*config['stl_unit_m']@R.T+r['translation_m'],tri,R


def reference_valid(v,tri,protocol):
    edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]);counts=Counter(map(tuple,np.sort(edges,axis=1)))
    oriented=Counter(map(tuple,edges));t=v[tri]
    volume=float(np.sum(t[:,0]*np.cross(t[:,1],t[:,2]))/6)
    return bool(np.isfinite(v).all() and all(c==2 for c in counts.values()) and all(c==oriented[(b,a)] for (a,b),c in oriented.items()) and np.all(np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)>protocol['reference_degenerate_cross_norm_floor_m2']) and abs(volume)>protocol['reference_nonzero_volume_floor_m3'])


def ray_reference(origin,vector,length,vertices,triangles,protocol):
    t=vertices[triangles];e1,e2=t[:,1]-t[:,0],t[:,2]-t[:,0]
    p=np.cross(np.broadcast_to(vector,e2.shape),e2);det=np.sum(e1*p,axis=1)
    usable=abs(det)>protocol['ray_triangle_parallel_determinant_floor_m2'];inverse=np.divide(1.,det,out=np.zeros_like(det),where=usable)
    s=np.asarray(origin)-t[:,0];u=np.sum(s*p,axis=1)*inverse;q=np.cross(s,e1)
    v=np.sum(q*vector,axis=1)*inverse;distance=np.sum(q*e2,axis=1)*inverse;a=protocol['ray_barycentric_allowance']
    mask=usable&(u>=-a)&(v>=-a)&(u+v<=1+a)&(distance>=0)&(distance<=length)
    if not mask.any():return {'hit':False}
    index=int(np.flatnonzero(mask)[np.argmin(distance[mask])]);normal=np.cross(e1[index],e2[index]);normal/=np.linalg.norm(normal)
    return {'hit':True,'distance_m':float(distance[index]),'triangle':index,'normal_finger':normal.tolist(),
        'edge_sensitive':bool(min(u[index],v[index],1-u[index]-v[index])<=1e-6),'grazing':bool(abs(np.dot(normal,vector))<.05)}


def failed_capture(args,supervisor,protocol,started):
    path=args.capture_protocol or args.input/'capture_protocol.json'
    historical=read(path);queries=read(args.input/'queries.json') if (args.input/'queries.json').exists() else []
    first_attempt=sha(path)==protocol['execution_history']['attempt1']['capture_protocol_sha256']
    if not first_attempt and historical!=protocol['capture_protocol']:raise ValueError('Staged failed-capture protocol is neither frozen1759 nor reviewed corrected protocol')
    controls=[q for q in queries if q['id'].startswith('control_')]
    target=[q for q in queries if 'tip' in q]
    setup=read(args.input/'prequery_setup.json') if (args.input/'prequery_setup.json').exists() else None
    result={'schema':'active-query-failed-capture-audit-v1','observation_integrity_passed':False,'proceed_gate_passed':False,
        'auditor_protocol_sha256':sha(HERE/'protocol.json'),'historical_capture_protocol_sha256':sha(path),
        'historical_capture_schema':historical['schema'],'corrected_protocol_applied_to_historical_capture':False,
        'recognized_capture_protocol':'frozen1759 initial setup' if first_attempt else 'reviewed corrected setup; still incomplete',
        'supervisor':supervisor,'failure':read(args.input/'failure.json') if (args.input/'failure.json').exists() else None,
        'raw_controls':controls,'raw_control_count':len(controls),'raw_control_hit_counts':{q['id']:len(q['hits']) for q in controls},'raw_target_probe_count':len(target),
        'target_observations':'NOT_EXECUTED' if not target else 'PARTIAL RAW DATA UNTESTED; capture incomplete',
        'target_geometry_and_reference_checks':'UNTESTED','scene_query_support_runtime':setup['scene_query_support_runtime'] if setup else 'NOT_RECORDED in historical1759',
        'prequery_setup_readbacks':setup if setup else 'NOT_RECORDED in historical1759',
        'interpretation':'Incomplete capture does not support target geometry inference. For1759, failed positive controls and a documented query-manager setup omission are not evidence of unusable collision geometry. Old G/contact failures remain unchanged.',
        'capture_wall_s':supervisor['capture_wall_seconds'],'audit_wall_s':time.monotonic()-started}
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'observation_integrity_passed':False,'proceed_gate_passed':False,'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


def main():
    started=time.monotonic();parser=argparse.ArgumentParser(description=__doc__)
    for name in ['input','output']:parser.add_argument('--'+name,type=Path,required=True)
    for name in ['stl','config','reference','capture-protocol']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Actual query/reference batch requires default Pueue')
    supervisor=read(args.input/'supervisor.json');protocol=read(HERE/'protocol.json')
    if supervisor['observation_completed'] is not True:
        failed_capture(args,supervisor,protocol,started);return
    if any(p is None for p in [args.stl,args.config,args.reference]):raise ValueError('Completed observation requires frozen STL/config/reference')
    capture=protocol['capture_protocol'];config=read(args.config);reference=read(args.reference)
    for path,digest in [(args.stl,protocol['stl_sha256']),(args.config,protocol['proxy_config_sha256']),(args.reference,protocol['reference_sha256'])]:
        if sha(path)!=digest:raise ValueError('Frozen reference changed: '+str(path))
    for name,digest in protocol['helpers_sha256'].items():
        if sha(HERE/name)!=digest:raise ValueError('Frozen helper changed')
    report=read(args.input/'query_report.json');authored=read(args.input/'authored_proxy.json');queries=read(args.input/'queries.json')
    checks={};checks['complete_observation']=report['observation_complete'] and supervisor['observation_completed']
    checks['zero_motion']=report['measured_postassembly_physics_steps']==0 and report['queries_do_not_move_actors'] and report['initial']==report['terminal'] and report['graph_unchanged']
    checks['full_source_PGS32_4']=len(report['source_parts'])==301 and len(set(report['source_parts']))==301 and len(report['native_connections'])==930 and len(report['runtime_source32_4'])==300 and all(v==[32,4] for v in report['runtime_source32_4'].values()) and bool(report['physics_scenes']) and all(s['solver']=='PGS' for s in report['physics_scenes'])
    checks['binary_dt_epsilon']=report['native_core_sha256']==capture['input_sha256']['.deps/bricksim/core.cpython-311-x86_64-linux-gnu.so'] and report['dt_s']==capture['source']['dt_s'] and report['OSQP_EPSILON']==capture['source']['OSQP_EPSILON']
    checks['nominal_q']=bool(np.allclose(report['initial']['q'],[protocol['nominal_joint_positions']],atol=protocol['nominal_joint_tolerance'],rtol=0) and np.isfinite(report['initial']['qdot']).all())
    checks['same_authored_configuration']=authored['config']==config
    checks['runtime_query_support_enabled']=report['scene_query_support_runtime'] is True and bool(report['physics_scenes']) and all(s['enable_scene_query_support'] is True for s in report['physics_scenes'])
    factory=report['factory']
    checks['only_declared_factory_changes']=factory['before']['solver_type']==1 and factory['after']=={**factory['before'],'solver_type':0} and factory['enable_scene_query_support_configured_before'] is False and factory['enable_scene_query_support_configured_after'] is True and factory['full_sim_cfg_only_declared_changes_verified'] is True and factory['changed_paths']==['physx.solver_type','enable_scene_query_support']
    by_id={q['id']:q for q in queries};checks['exact_unique_count']=len(queries)==protocol['expected_queries']==len(by_id)
    checks['callback_return_consistency']=all(q['callback_count']==len(q['hits']) and (q['api_return_bool']==bool(q['hits']) if q['kind']=='ray' else q['api_return_count']==len(q['hits'])) for q in queries)
    control=capture['query_control'];pos=by_id['control_hit'];neg=by_id['control_miss'];inside=by_id['control_inside'];outside=by_id['control_outside']
    control_hits=[h for h in pos['hits'] if h['collision']==control['path']]
    checks['ray_control_positive']=len(control_hits)==1 and bool(pos['api_return_bool']) and abs(control_hits[0]['distance_m']-control['expected_hit_distance_m'])<=control['distance_tolerance_m'] and np.max(abs(np.asarray(control_hits[0]['normal_world'])-[0,0,1]))<=control['normal_component_tolerance']
    checks['ray_control_miss']=not neg['hits'] and not neg['api_return_bool']
    checks['overlap_control_positive']=inside['api_return_count']==1 and len(inside['hits'])==1 and inside['hits'][0]['collision']==control['path']
    checks['overlap_control_miss']=outside['api_return_count']==0 and not outside['hits']
    checks['control_probe_contract']=all(np.allclose(q[field],expected,atol=1e-8,rtol=0) for q,field,expected in [(pos,'origin_world_m',control['ray_hit_origin_m']),(neg,'origin_world_m',np.asarray(control['ray_hit_origin_m'])+control['miss_offset_world_m']),(inside,'center_world_m',control['center_world_m']),(outside,'center_world_m',np.asarray(control['center_world_m'])+control['miss_offset_world_m'])])
    checks['control_directions_lengths_radii']=all(np.allclose(q['direction_world'],control['ray_direction'],atol=1e-8,rtol=0) and q['length_m']==control['ray_length_m'] for q in [pos,neg]) and all(q['radius_m']==control['overlap_radius_m'] for q in [inside,outside])
    tol=protocol['probe_position_tolerance_m'];tip_results={};expected_ids={'control_hit','control_miss','control_inside','control_outside'}
    for label in ['left','right']:
        frame=report['frames'][label];matrix=np.asarray(frame['world_from_finger']);physical=np.asarray(frame['physics_body_link_pose_world_wxyz']);usd=np.asarray(frame['USD_pose_world_wxyz'])
        checks[label+'_frame']=bool(np.isfinite(matrix).all() and np.linalg.norm(physical[:3]-usd[:3])<=capture['frame_verification']['physics_vs_USD_position_m'] and angle_between(physical[3:],usd[3:])<=capture['frame_verification']['physics_vs_USD_orientation_rad'] and np.allclose(matrix[3,:3],usd[:3],atol=1e-8,rtol=0) and np.allclose(matrix[:3,:3],rotation(usd[3:]).T,atol=1e-6,rtol=0))
        vertices,tri,R=reference_mesh(args.stl,config,label);valid=reference_valid(vertices,tri,protocol);checks[label+'_reference_valid']=valid
        author=authored['tips'][label];target='/World/envs/env_0/Robot/fr3_'+label+'finger/collisions/mesh_3'
        checks[label+'_registration']=author['path']==target and np.allclose(author['vertices_finger_m'],vertices,atol=config['visual_registration_match_m'],rtol=0) and np.array_equal(author['triangles'],tri) and np.allclose(author['transform_finger'],np.eye(4),atol=1e-9,rtol=0)
        checks[label+'_cook_parameters']=all(abs(author['cook_readback'][k]-v)<=config['schema_float_readback_atol'] if isinstance(v,float) else author['cook_readback'][k]==v for k,v in config['collision'].items() if k!='approximation')
        lo,hi=vertices.min(axis=0),vertices.max(axis=0);specs=[]
        for ix,x in enumerate(capture['contact_ray_grid']['hand_x_offsets_m']):
            for iz,z in enumerate(capture['contact_ray_grid']['hand_z_offsets_m']):
                center=np.asarray(reference['coupon_center_hand_m'])+[x,0,z];local=transform(transform(center,report['world_from_hand']),np.linalg.inv(matrix));local[1]=lo[1]-.02 if label=='left' else hi[1]+.02
                specs.append((f'{label}_grid_{ix}_{iz}',local,np.array([0,1 if label=='left' else -1,0]),float(hi[1]-lo[1]+.04)))
        for axis in range(3):
            for sign in [-1,1]:
                origin=(lo+hi)/2;origin[axis]=lo[axis]-.02 if sign==1 else hi[axis]+.02;d=np.zeros(3);d[axis]=sign
                specs.append((f'{label}_bbox_{axis}_{sign}',origin,d,float(hi[axis]-lo[axis]+.04)))
        ray_results=[];probe_ok=True;hit_data_ok=True
        for identity,origin,d,length in specs:
            expected_ids.add(identity);q=by_id[identity]
            probe_ok=probe_ok and q['kind']=='ray' and q['tip']==label and np.linalg.norm(np.asarray(q['origin_finger_m'])-origin)<=tol and np.linalg.norm(np.asarray(q['origin_world_m'])-transform(origin,matrix))<=tol and np.linalg.norm(np.asarray(q['direction_world'])-direction(d,matrix))<=protocol['probe_direction_tolerance'] and abs(q['length_m']-length)<=tol
            reference_hit=ray_reference(origin,d,length,vertices,tri,protocol) if valid else {'hit':None}
            target_hits=[]
            for i,h in enumerate(q['hits']):
                position=np.asarray(h['position_world_m']);normal=np.asarray(h['normal_world']);distance=h['distance_m']
                hit_data_ok=hit_data_ok and bool(np.isfinite([*position,*normal,distance]).all() and 0<=distance<=length+1e-5 and np.linalg.norm(position-(np.asarray(q['origin_world_m'])+distance*np.asarray(q['direction_world'])))<=protocol['ray_hit_position_and_distance_tolerance_m'] and abs(np.linalg.norm(normal)-1)<=protocol['unit_normal_tolerance'])
                if h['collision']==target:
                    hit_data_ok=hit_data_ok and h['rigid_body']==target.rsplit('/collisions/',1)[0]
                    target_hits.append((i,h))
            nearest=min(target_hits,key=lambda p:p[1]['distance_m']) if target_hits else None;all_nearest=min(enumerate(q['hits']),key=lambda p:p[1]['distance_m']) if q['hits'] else None
            ray_results.append({'id':identity,'reference':reference_hit,'target_hit_count':len(target_hits),'nearest_target_hit':{'raw_index':nearest[0],**nearest[1]} if nearest else None,'nearest_any_hit':{'raw_index':all_nearest[0],**all_nearest[1]} if all_nearest else None,'target_minus_CAD_first_distance_m':nearest[1]['distance_m']-reference_hit['distance_m'] if nearest and reference_hit['hit'] else None,'all_raw_hit_paths':[h['collision'] for h in q['hits']],'all_hit_class_counts':dict(Counter(hit_class(h['collision'],target) for h in q['hits'])),'status':'active_target_observed' if nearest else 'no_target_hit_observed; mesh coverage not certified'})
        checks[label+'_ray_probe_contract']=probe_ok;checks[label+'_ray_hit_data']=hit_data_ok
        overlaps=[];f=config['fidelity'];r=config['registration'][label]
        for x in f['bore_x_cad_mm']:
            for k in range(f['bore_witnesses_per_x']):
                identity=f'{label}_bore_{x}_{k}';expected_ids.add(identity);q=by_id[identity]
                offset=np.zeros(2) if k==0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)])
                point=np.r_[x,np.asarray(f['bore_center_cad_yz_mm'])+offset]*config['stl_unit_m']@R.T+r['translation_m']
                probe_ok=probe_ok and q['kind']=='overlap' and q['tip']==label and np.linalg.norm(np.asarray(q['center_finger_m'])-point)<=tol and np.linalg.norm(np.asarray(q['center_world_m'])-transform(point,matrix))<=tol and q['radius_m']==capture['bore_overlaps']['radius_m']
                clearance=surface_distance(point,vertices,tri);free,winding=outside_winding(point,vertices,tri);reference_free=valid and free and clearance>f['witness_reference_clearance_m'] and clearance>q['radius_m']
                paths=[h['collision'] for h in q['hits']];pad=target in paths
                overlaps.append({'id':identity,'reference_free_sphere':bool(reference_free),'reference_clearance_m':clearance,'reference_winding':winding,'target_pad_overlap_observed':pad,'all_raw_hit_paths':paths,'all_hit_class_counts':dict(Counter(hit_class(path,target) for path in paths)),'status':'PAD overlap in CAD-free sphere: conditional local discrepancy evidence' if reference_free and pad else 'no PAD overlap observed; target-overlap coverage not certified' if reference_free else 'reference classification UNKNOWN'})
        checks[label+'_overlap_probe_contract']=probe_ok;checks[label+'_27_reference_free_spheres']=len(overlaps)==27 and all(o['reference_free_sphere'] for o in overlaps)
        tip_results[label]={'rays':ray_results,'bore_overlaps':overlaps,'target_ray_queries_with_hit':sum(r['target_hit_count']>0 for r in ray_results),'CAD_ray_hits_without_target_hit':sum(bool(r['reference']['hit']) and not r['target_hit_count'] for r in ray_results),'target_hits_without_CAD_hit':sum(r['target_hit_count']>0 and r['reference']['hit'] is False for r in ray_results),'bore_queries_with_PAD_overlap':sum(o['target_pad_overlap_observed'] for o in overlaps)}
    checks['exact_probe_ID_set']=set(by_id)==expected_ids
    elapsed=time.monotonic()-started;capture_wall=float(supervisor['capture_wall_seconds']);checks['total_180s_budget']=capture_wall+elapsed<=protocol['capture_plus_audit_wall_s']
    result={'schema':protocol['schema'],'observation_integrity_passed':bool(all(checks.values())),'checks':{k:bool(v) for k,v in checks.items()},'tips':tip_results,'capture_wall_s':capture_wall,'audit_wall_s':elapsed,'total_active_wall_s':capture_wall+elapsed,'proceed_gate_passed':False,'old_G_status':'FAILED and closed, including102.881um>100um bounds; not reassessed as pass','contact_D_R_status':'NOT_RUN','full_property_equivalence':'UNTESTED','limits':'Cube controls establish basic query operation, not complete decomposed-mesh coverage. No-hit is an observation, not proof of absence. No force/contact/grasp/physical-mount validation.','protocol_sha256':sha(HERE/'protocol.json')}
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');(args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'observation_integrity_passed':result['observation_integrity_passed'],'proceed_gate_passed':False,'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


if __name__=='__main__':main()

"""One frozen R3 G/D/R read-only audit; all real geometry processing is queued."""
import argparse
import json
import math
import os
from pathlib import Path
import struct
import time
from types import SimpleNamespace

import numpy as np
from scipy.spatial import cKDTree

import evaluate as contact
from union_geometry import canonical_hash,contains,external_cloud,samples,outside_winding,check_time

HERE=Path(__file__).resolve().parent


def registered_stl(path,config,label):
    data=path.read_bytes()
    if contact.sha(path)!=config['stl_sha256']:raise ValueError('Frozen source STL hash mismatch')
    count=struct.unpack_from('<I',data,80)[0]
    if len(data)!=84+50*count:raise ValueError('Invalid binary STL')
    raw=np.asarray([list(struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])) for i in range(count)])
    vertices,inverse=np.unique(raw.reshape(-1,3),axis=0,return_inverse=True)
    r=config['registration'][label];a=math.radians(r['rotation_z_deg'])
    rotation=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
    return (vertices*config['stl_unit_m'])@rotation.T+np.asarray(r['translation_m']),inverse.reshape(-1,3),rotation


def white_matches(geometry,reference):
    for label in ['left','right']:
        current={c['path']:c for c in geometry['fingers'][label]['colliders'] if not c['is_pad']}
        baseline={c['path']:c for c in reference['white_colliders'][label]}
        if set(current)!=set(baseline):return False
        for path,c in current.items():
            b=baseline[path]
            if any(c.get(k)!=b.get(k) for k in ['type','enabled','approximation','attributes','physics_material_path','physics_material_attributes','contact_offset_m','rest_offset_m']):return False
            if not np.allclose(c['points_finger_m'],b['points_finger_m'],atol=1e-8,rtol=0):return False
    return True


def hull_checks(tip,config):
    hulls=tip['cooked_hulls'];epsilon=config['fidelity']['membership_epsilon_m']
    valid=1<len(hulls)<=config['collision']['maxConvexHulls']
    for h in hulls:
        v,p=np.asarray(h['vertices_m'],float),np.asarray(h['planes'],float)
        valid=valid and 4<=len(v)<=config['collision']['hullVertexLimit'] and np.isfinite(v).all() and np.isfinite(p).all() and p.shape[1]==4 and len(p)==len(h['polygons'])
        valid=valid and np.allclose(np.linalg.norm(p[:,:3],axis=1),1,atol=1e-6,rtol=0) and np.max(v@p[:,:3].T+p[:,3])<=epsilon
        for face,plane in zip(h['polygons'],p):
            valid=valid and len(face)>=3 and min(face)>=0 and max(face)<len(v) and np.max(abs(v[face]@plane[:3]+plane[3]))<=epsilon
    return bool(valid)


def fidelity(tip,label,config,stl,deadline):
    v,t,rotation=registered_stl(stl,config,label)
    if not np.allclose(tip['stl_points_finger_m'],v,atol=1e-9,rtol=0):raise ValueError('Exported STL registration differs from independent original STL')
    # The closed oriented source mesh is necessary to call bore witnesses free.
    edges=np.concatenate([t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]]);undirected=np.sort(edges,axis=1)
    _,counts=np.unique(undirected,axis=0,return_counts=True)
    from collections import Counter
    if not np.all(counts==2) or Counter(map(tuple,edges))!=Counter(map(tuple,edges[:,::-1])):raise ValueError('Reference STL is not closed and consistently oriented; witness space is unknown')
    f=config['fidelity'];stl_cloud,_=samples(v,t,f['surface_sample_spacing_m'],f['maximum_stl_samples_per_tip'],deadline)
    hull_cloud,candidates=external_cloud(tip['cooked_hulls'],config,deadline)
    check_time(deadline)
    to_hull=cKDTree(hull_cloud).query(stl_cloud,workers=1)[0]
    to_stl=cKDTree(stl_cloud).query(hull_cloud,workers=1)[0]
    all_vertices=np.concatenate([np.asarray(h['vertices_m']) for h in tip['cooked_hulls']])
    bound_error=float(np.max(abs(np.array([all_vertices.min(axis=0),all_vertices.max(axis=0)])-np.array([v.min(axis=0),v.max(axis=0)]))))
    yz=np.asarray(f['bore_center_cad_yz_mm']);witness=[]
    for x in f['bore_x_cad_mm']:
        for k in range(f['bore_witnesses_per_x']):
            offset=np.zeros(2) if k==0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)])
            point=np.r_[x,yz+offset]*config['stl_unit_m']@rotation.T+config['registration'][label]['translation_m']
            free,winding=outside_winding(point,v,t)
            distance=contact.surface_distance(point,v,t)
            outside=not contains([point],tip['cooked_hulls'],f['membership_epsilon_m'])[0]
            witness.append({'canonical_x_mm':x,'position_finger_m':point.tolist(),'reference_winding':winding,'reference_clearance_m':distance,'reference_free':bool(free and distance>f['witness_reference_clearance_m']),'cooked_union_free':bool(outside)})
            check_time(deadline)
    maximum=float(max(to_hull.max(),to_stl.max()))
    return {'STL_sample_count':len(stl_cloud),'hull_candidate_sample_count':candidates,'external_union_sample_count':len(hull_cloud),'STL_to_union_sample_max_m':float(to_hull.max()),'union_to_STL_sample_max_m':float(to_stl.max()),'maximum_sampled_boundary_distance_m':maximum,'outer_bound_error_m':bound_error,'witnesses':witness,'passed':maximum<=f['maximum_bidirectional_external_boundary_sample_distance_m'] and bound_error<=f['maximum_outer_bound_error_m'] and len(witness)==27 and all(w['reference_free'] and w['cooked_union_free'] for w in witness)}


def main():
    started=time.monotonic();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['G','D','R'],required=True)
    for name in ['input','stl','config','reference','output']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--predecessor',type=Path);parser.add_argument('--approved-G',dest='approved_G',type=Path)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Actual proxy audit requires default Pueue')
    protocol=contact.read(HERE/'proxy_protocol.json');config=contact.read(args.config);reference=contact.read(args.reference)
    if config!=protocol['configuration']:raise ValueError('Frozen one-configuration proxy changed')
    if contact.sha(args.reference)!=config['reference_sha256']:raise ValueError('Frozen B0 reference changed')
    supervisor=contact.read(args.input/'supervisor.json');capture_wall=float(supervisor['wall_seconds'])
    remaining=config['budgets']['capture_plus_audit_per_phase_s']-capture_wall
    if remaining<=0:raise TimeoutError('No remaining audit phase budget')
    deadline=started+remaining;artifact=contact.read(args.input/'proxy_geometry.json');geometry=contact.read(args.input/'geometry.json');checks={}
    checks['supervisor_capture_completed']=supervisor['capture_completed'] is True
    checks['input_config_hash_frame']=artifact['config']==config and artifact['config_sha256']==contact.sha(args.config) and artifact['frame']=='finger_local_m' and artifact['source_stl_sha256']==config['stl_sha256']
    checks['base_contact_contract_hash']=contact.sha(HERE/'protocol.json')==protocol['base_contact_protocol_sha256']
    checks['white_Cubes_unchanged']=white_matches(geometry,reference)
    checks['source_initial_unchanged']=contact.sha(args.input/'source_initial.npy')==protocol['baseline_source_initial_sha256']
    tips={};approved=None;prior_active=0
    if args.phase!='G':
        if args.predecessor is None:raise ValueError('Conditional phase needs predecessor independent audit')
        previous=contact.read(args.predecessor)
        checks['previous_phase_passed']=previous['phase']==('G' if args.phase=='D' else 'D') and previous['proceed_gate_passed'] and previous['protocol_sha256']==contact.sha(HERE/'proxy_protocol.json')
        prior_active=previous['cumulative_active_wall_s']
        approved=previous if args.phase=='D' else contact.read(args.approved_G)
        checks['approved_G_valid']=approved['phase']=='G' and approved['proceed_gate_passed'] and approved['protocol_sha256']==contact.sha(HERE/'proxy_protocol.json')
    for label,tip in artifact['tips'].items():
        digest=canonical_hash(tip['cooked_hulls'],config)
        checks[label+'_actual_cooked_hulls']=hull_checks(tip,config) and 'RESULT_VALID' in tip['cooking_result'] and tip['path']=='/World/envs/env_0/Robot/fr3_'+('left' if label=='left' else 'right')+'finger/collisions/mesh_3' and tip['frame']=='finger_local_m' and np.allclose(tip['identity_transform'],np.eye(4),atol=1e-9,rtol=0)
        checks[label+'_canonical_hash']=digest==tip['canonical_sha256']
        checks[label+'_cooking_parameters']=all(abs(tip['cook_parameters_readback'][k]-v)<=config['schema_float_readback_atol'] if isinstance(v,float) else tip['cook_parameters_readback'][k]==v for k,v in config['collision'].items() if k!='approximation')
        tips[label]={'canonical_sha256':digest}
        if args.phase=='G':tips[label]['fidelity']=fidelity(tip,label,config,args.stl,deadline);checks[label+'_sampled_fidelity']=tips[label]['fidelity']['passed']
        else:checks[label+'_same_approved_G']=digest==approved['tips'][label]['canonical_sha256']
    checks['two_tips']=set(tips)=={'left','right'}
    if args.phase=='G':
        meta=contact.read(args.input/'proxy_G_metadata.json');base=contact.read(HERE/'protocol.json')['unchanged']
        marker=contact.read(args.input/'proxy_geometry_complete.json')
        checks['G_no_contact_steps']=meta['stage']=='G' and meta['measured_contact_steps']==0 and meta['coupon_parked'] is True and marker['stage']=='G' and marker['capture_completed'] is True and marker['measured_contact_steps']==0
        checks['PGS32_4_source301930']=len(meta['source_parts'])==301 and len(set(meta['source_parts']))==301 and len(meta['native_connections'])==930 and len(meta['runtime_source_actor32_4'])==300 and all(v==[32,4] for v in meta['runtime_source_actor32_4'].values()) and bool(meta['physics_scenes']) and all(s.get('physxScene:solverType')=='PGS' for s in meta['physics_scenes'])
        checks['native_unchanged']=meta['native_core_sha256']==base['native_core_sha256'] and {k:v for k,v in meta['native_breakage'].items() if k!='debug_dump'}==base['native_breakage'] and meta['native_assembly']=={'enabled':False,'required_force':1.0} and meta['physics_dt_s']==base['dt_s'] and meta['OSQP_EPSILON']==base['OSQP_EPSILON']
        checks['B0_robot_properties']=meta['robot_properties']==reference['robot_properties']
        checks['fixed_B0_coupon_center']=np.allclose(meta['coupon_center_hand_m_frozen'],reference['coupon_center_hand_m'],atol=1e-12,rtol=0)
    else:
        meta=contact.read(args.input/'metadata.json')
        checks['B0_robot_properties']=meta['initial_robot_properties']==meta['terminal_robot_properties']==reference['robot_properties']
        center=np.asarray(reference['coupon_center_hand_m'])+np.array([.002 if args.phase=='R' else 0,0,0])
        checks['fixed_coupon_center']=np.allclose(meta['fixture_geometry']['body_center_hand_m'],center,atol=1e-12,rtol=0)
        checks['approval_file_binding']=meta['approved_G_geometry_sha256']==approved['proxy_geometry_sha256']
        check_time(deadline)
        contact.audit(SimpleNamespace(input=args.input,output=args.output/'contact',proxy_phase=args.phase,proxy_artifact=artifact,deadline=deadline))
        checked=contact.read(args.output/'contact/evaluation.json');checks['same_contact_gate_passed']=checked['contact_gate_passed']
    import hashlib
    checks['frozen_capture_protocol']=hashlib.sha256(json.dumps(meta['protocol'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==protocol['capture_protocol_semantic_sha256']
    check_time(deadline);elapsed=time.monotonic()-started
    checks['phase_active_budget']=capture_wall+elapsed<=config['budgets']['capture_plus_audit_per_phase_s']
    checks['cumulative_budget']=prior_active+capture_wall+elapsed<=config['budgets']['maximum_all_phase_active_s']
    result={'schema':'R3-proxy-independent-audit-v1','phase':args.phase,'protocol_sha256':contact.sha(HERE/'proxy_protocol.json'),'proxy_geometry_sha256':contact.sha(args.input/'proxy_geometry.json'),'approved_G_proxy_geometry_sha256':contact.sha(args.input/'proxy_geometry.json') if args.phase=='G' else approved['proxy_geometry_sha256'],'proceed_gate_passed':bool(all(checks.values())),'checks':{k:bool(v) for k,v in checks.items()},'tips':tips,'capture_wall_s':capture_wall,'audit_wall_s':elapsed,'cumulative_active_wall_s':prior_active+capture_wall+elapsed,'claims':'Sampled CAD representation and bounded fixture contact only, no global certification or grasp/extraction validity.'}
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');(args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'proceed_gate_passed':result['proceed_gate_passed'],'evaluation_sha256':contact.sha(args.output/'evaluation.json')})+'\n')
    print(json.dumps({'phase':args.phase,'proceed_gate_passed':result['proceed_gate_passed'],'checks':sum(result['checks'].values()),'total':len(checks)}))


if __name__=='__main__':main()

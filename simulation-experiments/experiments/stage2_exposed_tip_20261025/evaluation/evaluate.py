"""One frozen exposed-tip G/D/reserved audit, reusing signed-contact contracts."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time
STARTED=time.monotonic()
import numpy as np
from base_contact import rotation,angle_between
import base_contact
from mass_reference import restoration_checks,targeted_write_checks
from query_checks import check_rays
from query_reference import transform
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fixed_geometry(folder,cfg):
    before=read(folder/'geometry_stock_before.json');now=read(folder/'geometry.json');terminal=read(folder/'geometry_terminal.json');exposed=read(folder/'exposed_geometry.json');cooked=read(folder/'cook_results.json');checks={}
    heads=read(HERE.parent/'head_reference.json')['heads']
    for label in ['left','right']:
        head=exposed['tips'][label]['head'];ref=heads['fr3_'+label+'finger']
        checks[label+'_head_matches_current_visual']=head['axis']=='Y' and head['sides']==32 and abs(head['radius_m']-ref['head_radius_m'])<=1e-9 and abs(head['height_m']-ref['head_height_m'])<=1e-9 and np.allclose(head['center_finger_m'],ref['head_center_finger_m'],atol=cfg['visual_registration_readback_m'],rtol=0)
        old={c['path']:c for c in before['fingers'][label]['colliders'] if not c['is_pad']};new={c['path']:c for c in now['fingers'][label]['colliders'] if c['role']=='white'}
        same=set(old)==set(new)
        for p,c in new.items():
            row={k:v for k,v in c.items() if k not in ['role','is_head']};same=same and p in old and set(row)==set(old[p]) and all(np.allclose(row[k],old[p][k],atol=1e-9,rtol=0) if k in ['points_finger_m','bounds_finger_m'] else row[k]==old[p][k] for k in row)
        checks[label+'_white_unchanged']=bool(same)
        a={c['path']:c for c in now['fingers'][label]['colliders']};b={c['path']:c for c in terminal['fingers'][label]['colliders']};same=set(a)==set(b)
        for p,c in a.items():same=same and all(np.allclose(c[k],b[p][k],atol=1e-8,rtol=0) if k in ['points_finger_m','bounds_finger_m'] else c[k]==b[p][k] for k in c)
        checks[label+'_geometry_terminal_unchanged']=bool(same)
        checks[label+'_one_body_one_head']=sum(c['role']=='body' and c['is_pad'] for c in a.values())==1 and sum(c['role']=='head' and not c['is_pad'] for c in a.values())==1
        for kind,part in exposed['tips'][label]['parts'].items():
            settings=part['cook_readback'];r=cooked['tips'][label][kind]
            checks[label+'_'+kind+'_explicit_cooking']=settings['approximation']=='convexHull' and settings['hullVertexLimit']==255 and abs(settings['minThickness']-.0001)<=cfg['schema_float_atol_m'] and np.allclose(part['transform_finger'],np.eye(4),atol=1e-9,rtol=0)
            checks[label+'_'+kind+'_native_hull']=r['result_valid'] is True and r['hull_count']==len(r['hulls'])==1 and all(4<=h['vertex_count']==len(h['vertices_m'])<=255 and 4<=h['polygon_count']==len(h['polygons'])<=255 and np.isfinite(h['vertices_m']).all() and all(np.isfinite(p['plane']).all() and len(p['indices'])>=3 and all(0<=i<h['vertex_count'] for i in p['indices']) for p in h['polygons']) for h in r['hulls'])
            bounds=np.array([np.asarray(part['vertices_finger_m']).min(axis=0),np.asarray(part['vertices_finger_m']).max(axis=0)])
            checks[label+'_'+kind+'_bounds_100um']=all(np.max(abs(np.array([np.asarray(h['vertices_m']).min(axis=0),np.asarray(h['vertices_m']).max(axis=0)])-bounds))<=.0001 for h in r['hulls'])
    return checks,now,exposed,cooked


def fixture(meta,geometry,cfg,phase):
    frames=meta['fixture_frames'];z=cfg['metal_distal_finger_z_m']+.0005+.0048;actual=np.asarray(frames['center_hand_m']);expected_x=.002 if phase=='R' else 0.;centers=[];overlaps=[];checks={}
    for label in ['left','right']:
        m=np.asarray(frames['finger_to_hand'][label]);centers.append(transform([0,0,z],m)[2]);colliders=geometry['fingers'][label]['colliders'];body=next(c for c in colliders if c['role']=='body');points=np.c_[body['points_finger_m'],np.ones(len(body['points_finger_m']))]@m
        overlap=min(points[:,2].max(),actual[2]+.0048)-max(points[:,2].min(),actual[2]-.0048);overlaps.append(overlap)
        lo=actual+[-.016,-.008,-.0048];hi=actual+[.016,.008,.0065]
        checks[label+'_fixture_no_white_head_overlap']=True
        for c in colliders:
            if c['role']=='body':continue
            q=np.c_[c['points_finger_m'],np.ones(len(c['points_finger_m']))]@m
            if np.all(q.max(axis=0)[:3]>=lo-.00015) and np.all(q.min(axis=0)[:3]<=hi+.00015):checks[label+'_fixture_no_white_head_overlap']=False
    checks['fixture_named_frame_transform']=bool(abs(frames['center_finger_z_m']-z)<=1e-9 and max(centers)-min(centers)<=2e-6 and abs(actual[2]-sum(centers)/2)<=2e-6 and abs(actual[0]-expected_x)<=1e-9 and abs(actual[1])<=1e-9 and np.allclose(meta['fixture_geometry']['body_center_hand_m'],actual,atol=2e-6,rtol=0))
    checks['fixture_partial_side_overlap_7mm']=bool(min(overlaps)>=.007 and abs(frames['body_side_overlap_m']-min(overlaps))<=2e-6)
    checks['fixture_per_side_gaps']=all(abs(x-.00025)<=.00005 for x in meta['fixture_geometry']['initial_clearance_per_side_m'].values())
    return checks


def query_audit(args,p,cfg,before):
    folder=args.input;r=read(folder/'query_report.json');queries=read(folder/'queries.json');checks,geometry,exposed,cooked=fixed_geometry(folder,cfg)
    checks['same_fixed_model_config']=exposed['config']==cfg
    checks['zero_motion_native_graph']=r['phase']=='G' and r['initial']==r['terminal'] and r['measured_postassembly_physics_steps']==0 and len(set(r['source_parts']))==301 and len(set(r['native_connections']))==930
    checks['actual_PGS_querysupport_32_4']=r['scene_query_support_runtime'] is True and bool(r['physics_scenes']) and all(s['solver']=='PGS' and s['enable_scene_query_support'] is True for s in r['physics_scenes']) and len(r['runtime_source32_4'])==300 and all(v==[32,4] for v in r['runtime_source32_4'].values())
    capture=p['capture_protocol'];checks['native_physical_settings']=r['native_breakage']==capture['native_breakage'] and r['native_assembly']==capture['native_assembly'] and r['native_core_sha256']==capture['input_sha256']['.deps/bricksim/core.cpython-311-x86_64-linux-gnu.so'] and r['dt_s']==capture['source']['dt_s'] and r['OSQP_EPSILON']==capture['source']['OSQP_EPSILON']
    checks['robot_full6_B0_equal']=r['robot_properties_initial']==r['robot_properties_terminal']==before['initial_robot_properties']
    checks['source_properties_unchanged']=r['source_properties_initial']==r['source_properties_terminal'] and set(r['source_properties_initial'])==set(r['initial']['source']) and len(r['source_properties_initial'])==301 and all(np.isfinite(v).all() for actor in r['source_properties_initial'].values() for v in actor.values())
    for label,frame in r['frames'].items():
        a=np.asarray(frame['physics_body_link_pose_world_wxyz']);b=np.asarray(frame['USD_pose_world_wxyz']);m=np.asarray(frame['world_from_finger'])
        checks[label+'_frame']=bool(np.linalg.norm(a[:3]-b[:3])<=2e-6 and angle_between(a[3:],b[3:])<=1e-4 and np.allclose(m[3,:3],b[:3],atol=1e-8,rtol=0) and np.allclose(m[:3,:3],rotation(b[3:]).T,atol=1e-6,rtol=0))
    by={q['id']:q for q in queries};checks['unique216_callbacks']=len(by)==len(queries)==216 and all(q['callback_count']==len(q['hits']) and (q['api_return_bool']==bool(q['hits']) if q['kind']=='ray' else q['api_return_count']==len(q['hits'])) for q in queries)
    c=capture['query_control'];pos,neg,inside,outside=[by[k] for k in ['control_hit','control_miss','control_inside','control_outside']]
    checks['four_metric_query_controls']=len(pos['hits'])==1 and pos['hits'][0]['collision']==c['path'] and abs(pos['hits'][0]['distance_m']-.04)<=1e-5 and np.max(abs(np.asarray(pos['hits'][0]['normal_world'])-[0,0,1]))<=1e-5 and not neg['hits'] and len(inside['hits'])==1 and inside['hits'][0]['collision']==c['path'] and not outside['hits']
    checks['control_definitions']=all(np.allclose(q[field],value,atol=1e-8,rtol=0) for q,field,value in [(pos,'origin_world_m',c['ray_hit_origin_m']),(neg,'origin_world_m',np.asarray(c['ray_hit_origin_m'])+c['miss_offset_world_m']),(inside,'center_world_m',c['center_world_m']),(outside,'center_world_m',np.asarray(c['center_world_m'])+c['miss_offset_world_m'])]) and all(q['direction_world']==c['ray_direction'] and q['length_m']==c['ray_length_m'] for q in [pos,neg]) and all(q['radius_m']==c['overlap_radius_m'] for q in [inside,outside])
    extra,quality,details=check_rays(args.stl,exposed,r,queries,cfg,p);checks.update(extra)
    return {'checks':checks,'quality_checks':quality,'rays':details,'cooked_hashes':cooked['canonical_sha256'],'gate':all(checks.values()) and all(quality.values())}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--phase',choices=['G','D','R'],required=True)
    for name in ['input','output','stl','baseline-metadata','baseline-geometry']:parser.add_argument('--'+name,type=Path,required=True)
    for name in ['geometry-audit','side-authorization','predecessor-D']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    p=read(HERE/'protocol.json');cfg=p['model_config'];supervisor=read(args.input/'supervisor.json');capture_wall=float(supervisor['capture_wall_seconds']);result={'schema':p['schema'],'phase':args.phase,'proceed_gate_passed':False,'protocol_sha256':sha(HERE/'protocol.json')}
    def stop(*_):raise TimeoutError('Frozen capture+audit180second budget exhausted')
    signal.signal(signal.SIGALRM,stop);remaining=180-capture_wall-(time.monotonic()-STARTED)
    if not math.isfinite(capture_wall) or capture_wall<0 or remaining<=0:raise ValueError('Invalid remaining audit budget')
    args.deadline=STARTED+180-capture_wall
    signal.setitimer(signal.ITIMER_REAL,remaining)
    try:
        if args.phase=='G':raise ValueError('Original G is closed and failed; this protocol authorizes no replacement G')
        for path,digest in [(args.stl,cfg['stl_sha256']),(args.baseline_metadata,p['baseline_metadata_sha256']),(args.baseline_geometry,p['baseline_geometry_sha256']),(HERE.parent/'model_config.json',p['model_config_sha256']),(HERE.parent/'protocol.json',p['capture_protocol_sha256']),(HERE.parent/'head_reference.json',cfg['head_reference_sha256']),(HERE/'contact_protocol.json',p['force_protocol_sha256'])]:
            if sha(path)!=digest:raise ValueError('Frozen input changed: '+str(path))
        for name,digest in p['helpers_sha256'].items():
            if sha(HERE/name)!=digest:raise ValueError('Frozen audit helper changed')
        if not supervisor['capture_completed']:result.update(status='INCOMPLETE_CAPTURE',target_claims='UNTESTED',supervisor=supervisor)
        else:
            before=read(args.baseline_metadata);restoration=read(args.input/'property_restoration.json');checks=restoration_checks(restoration,before,p);checks.update(targeted_write_checks(restoration))
            if args.phase=='G':
                body=query_audit(args,p,cfg,before);checks.update(body.pop('checks'));result.update(body);gate=result.pop('gate') and all(checks.values())
            else:
                predecessor=read(args.geometry_audit);authorization=read(args.side_authorization)
                checks['original_failed_geometry_binding']=sha(args.geometry_audit)==p['side_contact']['geometry_audit_sha256']==authorization['geometry_audit_sha256'] and predecessor['phase']=='G' and predecessor['proceed_gate_passed'] is False
                checks['distinct_lateral_authorization']=sha(args.side_authorization)==p['side_contact']['authorization_sha256'] and authorization['schema']=='exposed-tip-lateral-authorization-v1' and authorization['authorization']=='D_then_conditional_R_lateral_only' and authorization['global_G_passed'] is False and authorization['existing_attempts_only'] is True and authorization['model_config_sha256']==p['model_config_sha256'] and authorization['cooked_hashes']==predecessor['cooked_hashes'] and authorization['point_contract']==p['side_contact']['point_contract']
                if args.phase=='R':
                    d=read(args.predecessor_D);checks['approved_D_predecessor']=d['phase']=='D' and d['proceed_gate_passed'] and d['protocol_sha256']==sha(HERE/'protocol.json') and d['cooked_hashes']==predecessor['cooked_hashes'] and d['side_authorization_sha256']==sha(args.side_authorization) and d['geometry_audit_sha256']==sha(args.geometry_audit)
                geometry_checks,geometry,exposed,cooked=fixed_geometry(args.input,cfg);checks.update(geometry_checks);meta=read(args.input/'metadata.json');checks.update(fixture(meta,geometry,cfg,args.phase));checks['strict_B0_properties']=meta['initial_robot_properties']==meta['terminal_robot_properties']==before['initial_robot_properties'];checks['same_G_cooked_representation']=cooked['canonical_sha256']==predecessor['cooked_hashes']
                checks['capture_lateral_authorization_binding']=meta['side_authorization_sha256']==sha(args.side_authorization) and meta['geometry_audit_sha256']==sha(args.geometry_audit) and meta['global_G_passed'] is False
                base_contact.audit(args);contact=read(args.output/'evaluation.json');online=read(args.input/'contact_report.json');checks['online_report_authorization_binding']=online['side_authorization_sha256']==sha(args.side_authorization) and online['geometry_audit_sha256']==sha(args.geometry_audit) and online['global_G_passed'] is False
                result.update(contact=contact,cooked_hashes=cooked['canonical_sha256'],side_authorization_sha256=sha(args.side_authorization),geometry_audit_sha256=sha(args.geometry_audit),global_G_passed=False,authorized_scope='lateral-qualified normal contact only, including edge anchors; no full G or zero-axial-force claim');gate=contact['contact_gate_passed'] and all(checks.values())
            checks['capture_plus_audit_180s']=capture_wall+time.monotonic()-STARTED<=180
            result.update(status='independent_audit_complete',checks={k:bool(v) for k,v in checks.items()},proceed_gate_passed=bool(gate and all(checks.values())))
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result.update(capture_wall_seconds=capture_wall,audit_wall_seconds=time.monotonic()-STARTED,scope=p['scope']);args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');(args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'phase':args.phase,'proceed_gate_passed':result['proceed_gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


if __name__=='__main__':main()

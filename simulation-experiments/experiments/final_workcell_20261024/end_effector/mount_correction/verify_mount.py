"""Queued visual-mount readbacks and unchanged-workcell checks; no physical-fit claim."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def point(p,m):return (np.r_[p,1.]@m)[:3]
def axis(p,m):
    a=(np.r_[p,0.]@m)[:3]
    return a/np.linalg.norm(a)


def native_height_anchors(record):
    if any(c!=3 for c in record['face_counts']):raise ValueError('Expected native triangle faces')
    points=np.asarray(record['points_finger_m']);faces=np.asarray(record['face_indices'],int).reshape(-1,3)
    subsets={s['path'].rsplit('/',1)[-1]:s['face_indices'] for s in record['material_subsets']}
    return float(points[faces[subsets['material_1']],2].min()),float(points[faces[subsets['material_0']],2].max())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['before','after','output']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    before,after=[read(p/'manifest.json') for p in [args.before,args.after]];tips=read(args.after/'updated_fingertips.json')
    layouts=[copy.deepcopy(m['final_layout']['layout_estimates']) for m in [before,after]]
    for layout in layouts:layout.pop('fingertip_visual',None)
    checks={'layout_except_tip_visual_unchanged':layouts[0]==layouts[1]}
    for key in ['geometry','applied_lighting_attributes','resolved_render_settings','brick_count','native_connections','native_connected_parts','post_connection_physics_steps']:
        checks[key+'_unchanged']=before[key]==after[key]
    checks['full300_native_static']=(after['brick_count'],after['native_connections'],after['native_connected_parts'],after['post_connection_physics_steps'])==(300,930,301,0) and after['all_capture_states_exactly_equal']
    checks['source_states_exact']=bool(np.array_equal(np.load(args.before/'evaluation_truth/active_root_states.npy'),np.load(args.after/'evaluation_truth/active_root_states.npy')))
    native=[[{k:v for k,v in r.items() if k!='source_layers'} for r in read(p/'native_finger_visual_audit.json')] for p in [args.before,args.after]]
    checks['native_white_visual_geometry_exact']=native[0]==native[1]
    for key in ['requested_joint_positions_native_units','actual_joint_positions_native_units','hand_usd_pose_wxyz']:
        checks[key+'_unchanged']=bool(np.allclose(before['robot_initialization'][key],after['robot_initialization'][key],atol=1e-6,rtol=0))
    checks['D435_mount_unchanged']=read(args.before/'wrist_mount_side.json')==read(args.after/'wrist_mount_side.json')
    checks['C920_actual_visual_report_unchanged']=before['final_layout']['additional_wrist_visual']==after['final_layout']['additional_wrist_visual']
    cameras=[{c['id']:c for c in read(p/'evaluation_truth/cameras.json')} for p in [args.before,args.after]]
    common=sorted(set(cameras[0])&set(cameras[1]));checks['existing_camera_views_present']={'diagnostic_table_top','diagnostic_c920_profile','diagnostic_c920_grasp_side'}<=set(common)
    for name in common:
        checks[name+'_camera_K_pose_unchanged']=all(cameras[0][name][k]==cameras[1][name][k] for k in ['actual_eye_world_m','actual_quaternion_wxyz_opengl','intrinsics'])
    checks['two_supplied_tips']=len(tips['instances'])==2 and {t['finger'] for t in tips['instances']}=={'fr3_leftfinger','fr3_rightfinger'}
    details={};normals={};probes=tips['reference_CAD_probes_mm'];headcfg=after['final_layout']['layout_estimates']['fingertip_visual']['outside_screw_visual']
    for t in tips['instances']:
        label=t['finger'];left=label=='fr3_leftfinger';m=np.asarray(t['actual_matrix_CAD_mm_to_finger_m'],float)
        expected_R=np.array([[0,-1 if left else 1,0],[-1 if left else 1,0,0],[0,0,-1.]])
        checks[label+'_proper_flip']=bool(np.isfinite(m).all() and np.allclose(m[:3,:3]/t['scale'],expected_R,atol=1e-6,rtol=0) and abs(np.linalg.det(m[:3,:3]/t['scale'])-1)<1e-6)
        grip=axis([1,0,0],m);boss=axis([-1,0,0],m);distal=axis([0,0,-1],m)
        checks[label+'_taper_distal']=bool(np.allclose(distal,[0,0,1],atol=1e-6,rtol=0))
        checks[label+'_grip_inward_boss_outward']=bool(np.allclose(grip,[0,-1 if left else 1,0],atol=1e-6,rtol=0) and np.allclose(boss,-grip,atol=1e-6,rtol=0))
        checks[label+'_reported_directions_match']=bool(np.allclose(t['grip_normal_finger'],grip,atol=1e-6,rtol=0) and np.allclose(t['boss_direction_finger'],boss,atol=1e-6,rtol=0))
        transformed={k:point(v,m) for k,v in probes.items()}
        checks[label+'_reported_probes_match']=all(np.allclose(t['probes_finger_m'][k],v,atol=1e-6,rtol=0) for k,v in transformed.items())
        seat=transformed['body_mount_axis'];front=transformed['boss_front_axis'];taper=transformed['taper_distal'];proximal=transformed['broad_proximal']
        checks[label+'_nominal_body_mount_plane']=abs(seat[1]-t['nominal_mount_plane_finger_y_m'])<1e-6
        depth=float(np.dot(front-seat,boss));checks[label+'_visual_attached_to_finger']=t['prim'].startswith('/World/envs/env_0/Robot/'+label+'/')
        checks[label+'_taper_more_distal_than_boss_and_proximal']=bool(taper[2]>front[2] and taper[2]>proximal[2])
        stock_prox,metal_distal=native_height_anchors(next(r for r in native[1] if r['finger']==label))
        expected_tip=stock_prox+(probes['broad_proximal'][2]-probes['taper_distal'][2])*t['scale']
        checks[label+'_proximal_edge_matches_stock_pad']=bool(abs(proximal[2]-stock_prox)<1e-6 and abs(t['bounds_finger_m'][0][2]-stock_prox)<1e-6)
        checks[label+'_longer_tip_extends_beyond_metal']=bool(taper[2]>metal_distal and t['bounds_finger_m'][1][2]>metal_distal)
        checks[label+'_height_matches_proximal_anchor_and_CAD_span']=bool(abs(taper[2]-expected_tip)<1e-6 and abs(t['bounds_finger_m'][1][2]-expected_tip)<1e-6)
        checks[label+'_only_old_pad_faces_hidden']=t['removed_stock_pad_faces']==262 and t['retained_white_finger_faces']==362
        checks[label+'_white_fingerprint_preserved']=t['white_fingerprint_before']==t['white_fingerprint_after']
        checks[label+'_stock_collision_fingerprint_preserved']=t['collision_fingerprint_before']==t['collision_fingerprint_after']
        checks[label+'_width_centered']=abs(sum(np.asarray(t['bounds_finger_m'])[:,0]))<1e-6
        head=t['outside_screw_visual'];sign=1 if left else -1;base=head['head_base_finger_y_m'];outer=head['head_outer_finger_y_m'];radius=head['head_radius_m'];center=np.asarray(head['head_center_finger_m'])
        expected_envelope=[[center[0]-radius,min(base,outer),center[2]-radius],[center[0]+radius,max(base,outer),center[2]+radius]]
        checks[label+'_round_head_visual_attached']=head['visual_only'] is True and head['physical_fit_or_clearance_verified'] is False and head['parent_finger']=='/World/envs/env_0/Robot/'+label and head['parent'].startswith(head['parent_finger']+'/') and head['head_prim'].startswith(head['parent']+'/') and head['axis']=='Y'
        checks[label+'_head_configured_envelope']=bool(abs(radius-headcfg['head_radius_m'])<1e-9 and abs(head['head_height_m']-headcfg['outward_protrusion_m'])<1e-9 and abs(head['outward_protrusion_m']-headcfg['outward_protrusion_m'])<1e-9 and abs(sign*(outer-base)-headcfg['outward_protrusion_m'])<1e-9 and np.allclose(head['head_envelope_finger_m'],expected_envelope,atol=1e-6,rtol=0))
        checks[label+'_head_outside_at_boss_height']=bool(sign*base>=sign*front[1]-1e-6 and np.allclose(center,[(front[0]),(base+outer)/2,front[2]],atol=1e-6,rtol=0))
        normals[label]=grip;details[label]={'grip_normal_finger':grip.tolist(),'boss_direction_finger':boss.tolist(),'nominal_mount_axis_finger_m':seat.tolist(),'nominal_boss_front_finger_m':front.tolist(),'nominal_taper_finger_m':taper.tolist(),'native_stock_pad_proximal_z_m':stock_prox,'native_metal_distal_z_m':metal_distal,'expected_tip_from_proximal_anchor_m':expected_tip,'nominal_boss_depth_m':depth,'outside_screw_visual':head}
    checks['grip_normals_opposed']=bool(np.allclose(normals['fr3_leftfinger'],-normals['fr3_rightfinger'],atol=1e-6,rtol=0))
    result={'schema':'visual-mount-correction-verification-v1','checks':{k:bool(v) for k,v in checks.items()},'all_passed':bool(all(checks.values())),
        'tip_readbacks':details,'unchanged_existing_camera_ids':common,'added_diagnostic_camera_ids':sorted(set(cameras[1])-set(cameras[0])),
        'physical_mount_fit_verified':False,'exact_recess_center_and_clearance':'UNMEASURED;1770 found no unique distal seat; current anchoring remains nominal',
        'new_tip_collision_validated':False,'scope':'Visual orientation/readback and invariant checks only. No physical seating/calibration/contact or old-failure promotion.',
        'before':str(args.before),'after':str(args.after),'input_sha256':{'before_manifest':sha(args.before/'manifest.json'),'after_manifest':sha(args.after/'manifest.json'),'updated_fingertips':sha(args.after/'updated_fingertips.json')}}
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'verification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if not result['all_passed']:raise SystemExit(1)


if __name__=='__main__':main()

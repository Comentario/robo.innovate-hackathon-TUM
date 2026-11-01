"""Data-only pose export/width bridge. No hardware, rendering, FK solve or fit."""
import argparse
from collections import Counter
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
import numpy as np
import scipy
from scipy.spatial.transform import Rotation

HERE=Path(__file__).resolve().parent
ROTATION_ATOL=1e-5  # Existing float32 transform serialization, not pose accuracy.
GRID_ATOL_M=1e-8


def extract(text):
    blocks=re.findall(r'```json\s*\n(.*?)\n```',text,re.S)
    if len(blocks)!=1:raise ValueError('Exactly one authoritative JSON block required')
    return blocks[0],json.loads(blocks[0])


def matrix(values):
    a=np.asarray(values,dtype=np.float64)
    if a.shape!=(16,) or not np.isfinite(a).all():raise ValueError('Finite column-major16 required')
    return a.reshape(4,4,order='F')


def proper(a):
    return bool(np.allclose(a[3],[0,0,0,1],atol=ROTATION_ATOL,rtol=0) and
        np.allclose(a[:3,:3].T@a[:3,:3],np.eye(3),atol=ROTATION_ATOL,rtol=0) and
        abs(np.linalg.det(a[:3,:3])-1)<=ROTATION_ATOL)


def urdf_fixed(path,name):
    matches=[j for j in ET.parse(path).getroot().findall('joint') if j.attrib['name']==name]
    if len(matches)!=1 or matches[0].attrib['type']!='fixed':raise ValueError('Unique fixed URDF joint required')
    joint=matches[0];origin=joint.find('origin');a=np.eye(4)
    a[:3,3]=list(map(float,origin.attrib['xyz'].split()))
    a[:3,:3]=Rotation.from_euler('xyz',list(map(float,origin.attrib['rpy'].split()))).as_matrix()
    return a


def bridge_pose(base_ee,flange_hand,flange_ee,hand_grip):
    # Exported base-Z -15mm is ALREADY in base_ee. Never apply it again.
    hand_ee=np.linalg.inv(flange_hand)@flange_ee
    base_hand=base_ee@np.linalg.inv(hand_ee)
    return base_hand,base_hand@hand_grip,hand_ee


def run(inputs,output):
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('315-pose numerical audit requires default Pueue')
    start=time.monotonic();inputs=Path(inputs);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    protocol=json.loads(inputs.read_text());files={};hashes={}
    for name,record in protocol['files'].items():
        path=(inputs.parent/record['path']).resolve();digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=record['sha256']:raise ValueError('Input SHA mismatch: '+name)
        files[name]=path;hashes[name]=digest
    raw,data=extract(files['markdown'].read_text());registry=json.loads(files['registry'].read_text())
    science=json.loads(files['science'].read_text());usd=json.loads(files['usd_chain'].read_text())
    width=json.loads(files['width_reference'].read_text());checks={}
    checks['original_bytes']=all(hashes[name]==registry['original_files'][filename]['sha256'] for name,filename in
        [('markdown','1-lego_grasp_poses.md'),('photo','2-saved_positions.jpeg')])
    checks['export_conventions']=all(data[k]==v for k,v in {'reference_frame':'robot_base_O','pose_frame':'configured_end_effector_EE',
        'position_units':'m','matrix_storage':'column_major','source_sha256':registry['export_claim']['source_positions_sha256'],
        'default_grasp_offset_base_m':[0,0,-.015]}.items())
    rows=data['poses'];byid={r['id']:r for r in rows};inferred=[r for r in rows if r['kind']=='inferred'];recorded=[r for r in rows if r['kind']=='recorded']
    checks['counts']=len(rows)==len(byid)==315 and len(inferred)==300 and len(recorded)==15
    checks['grid_ids']=set((r['n'],r['m'],r['k']) for r in inferred)=={(n,m,k) for n in range(6) for m in range(5) for k in range(10)}
    checks['grid_id_spelling']=all(r['id']==f"a_{r['n']}_{r['m']}_{r['k']}" for r in inferred)
    transforms={r['id']:matrix(r['O_T_EE']) for r in rows}
    checks['proper_exported_poses']=all(proper(a) for a in transforms.values())
    checks['xyz_matrix_agree']=all(np.allclose(transforms[r['id']][:3,3],r['xyz_m'],atol=1e-12,rtol=0) for r in rows)
    checks['offset_already_applied_declarations']=all(r['offset_from_recorded_pose_base_m']==[0,0,-.015] for r in rows)
    p=lambda n,m,k:transforms[f'a_{n}_{m}_{k}'][:3,3]
    spacing=.0318;height=.0096;origin=p(0,0,9);u=(p(0,1,9)-origin)/spacing;v=(p(1,0,9)-origin)/spacing
    checks['orthogonal_318mm_grid']=bool(abs(np.linalg.norm(u)-1)<=ROTATION_ATOL and abs(np.linalg.norm(v)-1)<=ROTATION_ATOL and abs(u@v)<=ROTATION_ATOL)
    grid_errors=[];orientation_errors=[]
    for r in inferred:
        n,m,k=r['n'],r['m'],r['k'];odd=k%2==1
        expected=origin+spacing*(m*u+n*v if odd else .5*(v-u)+n*u+m*v)+[0,0,(k-9)*height]
        grid_errors.append(float(np.linalg.norm(np.asarray(r['xyz_m'])-expected)))
        ref=transforms['a_0_0_9' if odd else 'a_0_0_8'][:3,:3]
        orientation_errors.append(float(np.max(abs(transforms[r['id']][:3,:3]-ref))))
    checks['fixed_spacing_layer_centers']=max(grid_errors)<=GRID_ATOL_M
    checks['parity_orientations_preserved']=max(orientation_errors)<=ROTATION_ATOL
    relative=transforms['a_0_0_9'][:3,:3].T@transforms['a_0_0_8'][:3,:3]
    parity_angle=float(Rotation.from_matrix(relative).magnitude())
    checks['alternating90_degrees']=abs(parity_angle-np.pi/2)<=ROTATION_ATOL
    checks['anchor_record3_exact_xyz']=byid['point_03']['xyz_m']==byid['a_0_0_9']['xyz_m']
    joints=[j for j in usd['joints'] if j['name']=='fr3_hand_joint']
    if len(joints)!=1 or joints[0]['type']!='fixed':raise ValueError('Unique USD flange-hand fixed joint required')
    j=joints[0];fh=np.asarray(j['T_parent_joint'])@np.linalg.inv(np.asarray(j['T_child_joint']))
    checks['USD_fixed_named_frames']=j['parent'].endswith('/fr3_link8') and j['child'].endswith('/fr3_hand')
    uh=urdf_fixed(files['urdf'],'fr3_hand_joint');ue=urdf_fixed(files['urdf'],'fr3_hand_tcp_joint')
    grip=np.eye(4);grip[:3,3]=science['tool_frames']['T_hand_grip_translation_m']
    grip[:3,:3]=Rotation.from_quat(np.asarray(science['tool_frames']['T_hand_grip_quaternion_wxyz'])[[1,2,3,0]]).as_matrix()
    checks['USD_URDF_flange_hand']=bool(np.allclose(fh,uh,atol=ROTATION_ATOL,rtol=0))
    frame_bridges={};derived=[]
    for name,tool in data['tool_frames'].items():
        fe=matrix(tool['F_T_EE']);_,_,he=bridge_pose(np.eye(4),fh,fe,grip)
        checks[name+'_rigid_tool_frames']=all(proper(matrix(tool[k])) for k in ('F_T_EE','F_T_NE','NE_T_EE','EE_T_K'))
        checks[name+'_configured_route']=bool(np.allclose(fh@ue,fe,atol=ROTATION_ATOL,rtol=0))
        checks[name+'_nominal_route']=bool(np.allclose(matrix(tool['F_T_NE'])@matrix(tool['NE_T_EE']),fe,atol=ROTATION_ATOL,rtol=0))
        frame_bridges[name]={'T_flange_hand_USD':fh.tolist(),'T_hand_configured_EE':he.tolist(),
                            'T_hand_current_MODEL_grip':grip.tolist(),'T_EE_current_MODEL_grip':(np.linalg.inv(he)@grip).tolist()}
    for r in rows:
        bh,bg,_=bridge_pose(transforms[r['id']],fh,matrix(data['tool_frames'][r['tool_frame_id']]['F_T_EE']),grip)
        derived.append({'id':r['id'],'T_base_hand':bh.tolist(),'T_base_current_MODEL_grip':bg.tolist(),
                        'source_export_flags':{k:v for k,v in r.items() if k.endswith('_validated')}})
    # Nearest exported XYZ is descriptive correspondence, not an accuracy/fit claim.
    neighbors=[]
    for r in recorded:
        distances=[float(np.linalg.norm(np.asarray(r['xyz_m'])-np.asarray(a['xyz_m']))) for a in inferred]
        index=int(np.argmin(distances));a=inferred[index]
        neighbors.append({'recorded_id':r['id'],'nearest_inferred_id':a['id'],'translation_residual_m':distances[index],
            'rotation_residual_rad':float(Rotation.from_matrix(transforms[r['id']][:3,:3]@transforms[a['id']][:3,:3].T).magnitude()),
            'correspondence':'Explicit XYZ anchor' if r['id']=='point_03' else 'Nearest exported XYZ only; not asserted same physical brick'})
    flags={key:dict(Counter(str(r.get(key,'ABSENT')) for r in rows)) for key in ('motion_validated','grasp_physically_validated')}
    offset=width['model_width_relations']['nominal_custom_face_offset_sum_m'];user=registry['later_user_report']
    widths={'source':'Existing source-derived gap=q1+q2+offset; not physical calibration','custom_gap_intercept_m':offset,
        'reported':user,'conditional_assumptions':['Desk displayed width equals SDK q1+q2','Same physical custom-pad mounting as current model'],
        'if_display_equals_joint_sum':[{ 'display_width_m':user[key],'predicted_MODEL_pad_gap_m':user[key]+offset} for key in
            ('approach_display_width_m','commanded_display_width_m','loaded_display_readback_m')],
        'current_nominal14mm_MODEL_command_q_each_m':(.014-offset)/2,'inferred_physical_gap_offset_m':None,
        'inference':'Loaded15.8mm would imply18.61338mm MODEL gap under both assumptions; this challenges their joint validity, not a fitted correction.'}
    report={'data_checks_passed':all(checks.values()),'checks':checks,'input_sha256':hashes,'pose_counts':{'total':len(rows),'recorded':len(recorded),'inferred':len(inferred)},
        'exported_flag_counts':flags,'later_user_report':user,'maximum_grid_residual_m':max(grid_errors),'parity_angle_rad':parity_angle,
        'grid_basis_from_named_top_layer_anchors':{'u':u.tolist(),'v':v.tolist()},'recorded_inferred_descriptive_residuals':neighbors,
        'frame_bridges':frame_bridges,'width_comparison':widths,'unknowns':registry['unknowns'],
        'upper_reference_not_assumed_brick_top':True,'offset_applied_again':False,'physical_registration_verified':False,
        'hardware_execution_authorized':False,'simulation_or_grasp_success_claim':False,'runtime_versions':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__},
        'wall_seconds':time.monotonic()-start}
    (output/'authoritative_poses.json').write_text(raw+'\n')
    (output/'transformed_reference_poses.json').write_text(json.dumps({'scope':'CURRENT MODEL frame comparison only','poses':derived},indent=2,allow_nan=False)+'\n')
    (output/'comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument('--inputs',type=Path,default=HERE/'protocol.json');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run(args.inputs,args.output)
    raise SystemExit(0 if result['data_checks_passed'] else 1)

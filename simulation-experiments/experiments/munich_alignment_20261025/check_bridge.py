"""Pinned data-only FR3/calibration bridge check; no hardware, images or refit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
import yaml

LIMITS={'fk_translation_m':.002,'fk_rotation_rad':.01,'algebra_atol':1e-5,
        'rotation_orthogonality_atol':1e-5,'board_translation_rms_m':.003,
        'board_translation_max_m':.006,'board_rotation_rms_deg':.8,'board_rotation_max_deg':1.5}


def rigid(matrix):
    m=np.asarray(matrix,float)
    if m.shape!=(4,4) or not np.isfinite(m).all():raise ValueError('Invalid finite4x4 transform')
    return m


def residual(a,b):
    return {'translation_m':float(np.linalg.norm(a[:3,3]-b[:3,3])),
            'rotation_rad':float(Rotation.from_matrix(a[:3,:3]@b[:3,:3].T).magnitude())}


def urdf_chain(path):
    incoming={}
    for joint in ET.parse(path).getroot().findall('joint'):
        child=joint.find('child').attrib['link']
        if child in incoming:raise ValueError('Ambiguous URDF parent')
        incoming[child]=joint
    chain=[];child='fr3_hand_tcp';seen=set()
    while child!='fr3_link0':
        if child in seen:raise ValueError('Cyclic URDF chain')
        seen.add(child);j=incoming[child];origin=j.find('origin');axis=j.find('axis')
        m=np.eye(4)
        if origin is not None:
            m[:3,3]=list(map(float,origin.attrib.get('xyz','0 0 0').split()))
            m[:3,:3]=Rotation.from_euler('xyz',list(map(float,origin.attrib.get('rpy','0 0 0').split()))).as_matrix()
        kind=j.attrib['type']
        if kind not in ('fixed','revolute'):raise ValueError('Unsupported arm-chain joint')
        chain.append({'name':j.attrib['name'],'type':kind,'parent':j.find('parent').attrib['link'],
                      'child':child,'T_parent_joint':m.tolist(),'T_child_joint':np.eye(4).tolist(),
                      'axis_vector':list(map(float,axis.attrib['xyz'].split())) if axis is not None else None})
        child=chain[-1]['parent']
    return list(reversed(chain))


def fk(chain,q):
    """BASE-relative column-vector FK; identity denotes its own coordinate origin."""
    frames={'fr3_link0':np.eye(4)}
    for j in chain:
        parent,child=j['parent'].split('/')[-1],j['child'].split('/')[-1]
        motion=np.eye(4)
        if j['type']=='revolute':motion[:3,:3]=Rotation.from_rotvec(np.asarray(j['axis_vector'])*q[j['name']]).as_matrix()
        frames[child]=frames[parent]@rigid(j['T_parent_joint'])@motion@np.linalg.inv(rigid(j['T_child_joint']))
    return frames


def run(inputs,output):
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Numeric bridge check requires default Pueue')
    start=time.monotonic();inputs=Path(inputs);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    protocol=json.loads(inputs.read_text());hashes={};paths={}
    if protocol.get('execution_authorized') is not True:raise RuntimeError('Bridge execution is not authorized')
    if protocol['tolerances']!=LIMITS or protocol['maximum_active_seconds']!=10 or protocol['expected_observations']!=12:
        raise RuntimeError('Frozen compatibility limits or budget changed')
    def checked(key,item):
        p=(inputs.parent/item['path']).resolve();digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest!=item['sha256']:raise RuntimeError('Input SHA mismatch: '+key)
        hashes[key]=digest;return p
    for key,item in protocol['files'].items():paths[key]=checked(key,item)
    pairings=[(item['id'],checked(item['id'],item)) for item in protocol['pairings']]
    acquisitions={item['id']:checked(item['id']+'_original',item) for item in protocol['acquisitions']}
    read=lambda key:json.loads(paths[key].read_text())
    frames,camera,board,validation,index,usd,science=map(read,('frames','camera','board_points','validation','index','usd_chain','grip_science'))
    result=yaml.safe_load(paths['result'].read_text());urdf=urdf_chain(paths['urdf'])
    checks={};matrices={row['name']:rigid(row['matrix']) for row in frames['transforms']}
    checks['named_robot_frames']=(frames['robot_base']=='fr3_link0' and frames['flange']=='fr3_link8' and frames['configured_ee']=='fr3_hand_tcp')
    for row in frames['transforms']:
        checks[row['name']+'_meters']=row['translation_units']=='m'
    def check_matrix(name,m):
        checks[name+'_rigid']=bool(np.max(abs(m[3]-[0,0,0,1]))<=1e-5 and
            np.max(abs(m[:3,:3].T@m[:3,:3]-np.eye(3)))<=1e-5 and abs(np.linalg.det(m[:3,:3])-1)<=1e-5)
    def equal(name,a,b):checks[name]=bool(np.max(abs(a-b))<=LIMITS['algebra_atol'])
    for name,m in matrices.items():check_matrix(name,m)
    for a,b in [('T_tcp_color','T_color_tcp'),('T_tcp_depth','T_depth_tcp'),('T_color_depth','T_depth_color'),('T_base_board','T_board_base')]:
        equal(a+'_inverse',matrices[a]@matrices[b],np.eye(4))
    expected=['fr3_joint'+str(i) for i in range(1,8)]
    checks['actual_arm_names_match']=([j['name'] for j in usd['joints'] if j['type']=='revolute']==expected and
                                      [j['name'] for j in urdf if j['type']=='revolute']==expected)
    fixed={}
    for label,chain,parent,child in [('USD_hand',usd['joints'],'fr3_link8','fr3_hand'),
            ('URDF_hand',urdf,'fr3_link8','fr3_hand'),('URDF_tcp',urdf,'fr3_hand','fr3_hand_tcp')]:
        matches=[j for j in chain if j['child'].split('/')[-1]==child]
        if len(matches)!=1 or matches[0]['type']!='fixed' or matches[0]['parent'].split('/')[-1]!=parent:raise ValueError('Ambiguous fixed tool-frame route')
        j=matches[0];fixed[label]=rigid(j['T_parent_joint'])@np.linalg.inv(rigid(j['T_child_joint']))
    flange_hand,hand_tcp=fixed['USD_hand'],fixed['URDF_tcp']
    equal('USD_URDF_flange_hand',flange_hand,fixed['URDF_hand'])
    equal('configured_EE_fixed_route',flange_hand@hand_tcp,matrices['T_flange_tcp'])
    hand_color=np.linalg.inv(flange_hand)@matrices['T_flange_color']
    equal('hand_color_two_routes',hand_color,hand_tcp@matrices['T_tcp_color'])
    equal('depth_factory_route',matrices['T_tcp_color']@matrices['T_color_depth'],matrices['T_tcp_depth'])
    equal('YAML_handeye_matches_frames',rigid(result['T_tcp_color']),matrices['T_tcp_color'])
    equal('YAML_board_matches_frames',rigid(result['T_base_board']),matrices['T_base_board'])
    observations=result['diagnostics']['observations'];ids=[r['id'] for r in index['observations']]
    checks['exact_twelve_actual_pairings']=len(pairings)==len(ids)==len(observations)==12 and len(set(ids))==12 and [p[0] for p in pairings]==ids
    checks['exact_original_acquisitions']=set(acquisitions)==set(ids)
    by_stem={Path(o['path']).stem:o for o in observations}
    per_pose=[];translations=[];angles=[];complete=True
    for identity,path in pairings:
        if time.monotonic()-start>=9.:complete=False;break
        pair=json.loads(path.read_text());entry=next(r for r in index['observations'] if r['id']==identity)
        checks[identity+'_identity']=pair['id']==identity and Path(entry['pairing']).name==path.name
        positions=pair['actual_joint_positions'];checks[identity+'_names']=positions['names']==expected
        q=dict(zip(positions['names'],positions['positions_rad']))
        if len(q)!=7 or not np.isfinite(list(q.values())).all():raise ValueError('Invalid actual seven-joint sample')
        measured={name:rigid(pair[name]['matrix']) for name in ('T_base_tcp','T_base_flange','T_flange_tcp')}
        acquisition_path=acquisitions[identity];original=json.loads(acquisition_path.read_text())['robot_after']
        checks[identity+'_original_filename']=Path(pair['original_acquisition_json']).name==acquisition_path.name
        checks[identity+'_actual_after_q']=np.array_equal(positions['positions_rad'],original['q'])
        for raw_key,named in [('O_T_EE','T_base_tcp'),('F_T_EE','T_flange_tcp')]:
            # ONLY raw libfranka16-vectors need this one column-major reshape.
            decoded=rigid(np.asarray(original[raw_key],float).reshape(4,4,order='F'))
            checks[identity+'_actual_after_'+raw_key]=np.array_equal(decoded,measured[named])
        for name,m in measured.items():check_matrix(identity+'_'+name,m)
        equal(identity+'_actual_flange_route',measured['T_base_flange']@measured['T_flange_tcp'],measured['T_base_tcp'])
        equal(identity+'_configured_F_T_EE',measured['T_flange_tcp'],matrices['T_flange_tcp'])
        uf,rf=fk(usd['joints'],q),fk(urdf,q);record={'id':identity,'actual_q':positions,'errors':{}}
        for label,estimate,reference in [('USD_flange',uf['fr3_link8'],measured['T_base_flange']),
                ('USD_configured_EE',uf['fr3_hand']@hand_tcp,measured['T_base_tcp']),
                ('URDF_flange',rf['fr3_link8'],measured['T_base_flange']),('URDF_configured_EE',rf['fr3_hand_tcp'],measured['T_base_tcp'])]:
            error=residual(estimate,reference);record['errors'][label]=error
            checks[identity+'_'+label]=error['translation_m']<=.002 and error['rotation_rad']<=.01
        observation=by_stem[Path(pair['rgbd_file']).stem.split('_',1)[1]]
        equal(identity+'_actual_pose_YAML_pairing',rigid(observation['T_base_tcp']),measured['T_base_tcp'])
        color_board=rigid(observation['T_color_board']);check_matrix(identity+'_T_color_board',color_board)
        closure=measured['T_base_tcp']@matrices['T_tcp_color']@color_board
        error=residual(closure,matrices['T_base_board']);record['fixed_board_error']=error
        translations.append(error['translation_m']);angles.append(float(np.rad2deg(error['rotation_rad'])));per_pose.append(record)
    checks['completed_twelve']=complete and len(per_pose)==12
    stats={}
    if translations:
        stats={'translation_rms_m':float(np.sqrt(np.mean(np.square(translations)))),'translation_max_m':max(translations),
               'rotation_rms_deg':float(np.sqrt(np.mean(np.square(angles)))),'rotation_max_deg':max(angles)}
        checks['board_translation_rms']=stats['translation_rms_m']<=.003;checks['board_translation_max']=stats['translation_max_m']<=.006
        checks['board_rotation_rms']=stats['rotation_rms_deg']<=.8;checks['board_rotation_max']=stats['rotation_max_deg']<=1.5
    checks['accepted_RealSense_only']=validation['realsense']['numerical_handeye_passed'] is True and validation['wrist_webcam']['accepted'] is False
    checks['SDK_device_profile']=camera['sdk_identified_model']=='RealSense D435' and camera['serial']=='943222073921' and camera['rgb']['resolution']==[1280,720]
    checks['aligned_depth_convention']=(camera['aligned_depth']['aligned_to']=='RGB' and camera['aligned_depth']['use_transform']=='T_tcp_color' and camera['aligned_depth']['invalid_zero_value']==0.)
    equal('aligned_RGB_K',np.asarray(camera['rgb']['K']),np.asarray(camera['aligned_depth']['K']))
    checks['unknown_frames_still_unknown']=all(frames.get(k) is None for k in ('T_isaac_world_base','T_base_input_plate','T_base_output_plate','T_base_opposite_c920'))
    checks['board_object_frame']=board['frame']=='charuco_board' and board['units']=='m' and len(board['charuco_corners_m'])==24
    grip=np.eye(4);grip[:3,3]=science['tool_frames']['T_hand_grip_translation_m'];grip[:3,:3]=Rotation.from_quat(np.asarray(science['tool_frames']['T_hand_grip_quaternion_wxyz'])[[1,2,3,0]]).as_matrix()
    bridge={'T_flange_hand_USD':flange_hand.tolist(),'T_hand_configured_EE_URDF':hand_tcp.tolist(),'T_hand_color':hand_color.tolist(),
            'T_grip_color':(np.linalg.inv(grip)@hand_color).tolist(),'T_hand_custom_grip_model':grip.tolist()}
    report={'gate_passed':bool(checks and all(checks.values())),'auto_use_allowed':bool(checks and all(checks.values())),
            'checks':checks,'source_sha256':hashes,'accepted_calibration_frames_retained':frames,'bridge_matrices':bridge,
            'per_pose':per_pose,'board_closure_statistics':stats,'device':camera,
            'unknown':dict.fromkeys(('T_isaac_world_base','T_base_input_plate','T_base_output_plate','T_base_bowl','T_base_opposite_c920')),
            'is_not_grip_calibration':True,'physical_alignment_accuracy_verified':False,'hardware_execution_authorized':False,
            'auto_use_scope':'Calibration frame bridge only; no physical plate registration or motion permission.',
            'base_relative_FK_identity':'Coordinate origin fr3_link0 only; NOT an estimate of T_isaac_world_base.',
            'data_convention':'T_A_B maps B into A, meters, column vectors. Aligned depth meters/0invalid uses color optical frame; no extra scale.',
            'wall_seconds':time.monotonic()-start,'truncated':not complete}
    (output/'bridge_registry.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument('--inputs',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();run(args.inputs,args.output)

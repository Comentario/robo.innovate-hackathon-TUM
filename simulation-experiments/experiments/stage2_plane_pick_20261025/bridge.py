"""Startup-only physical-control reuse and nominal joint/plane gap derivation."""
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def model_gap(state,inner_planes):
    """Signed separation of known pad-plane references along measured hand +Y."""
    q=np.asarray(state['tcp_pose_world_wxyz'][3:],float)
    hand_rotation=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
    points={}
    for side in ('left','right'):
        pose=np.asarray(state['finger_poses_world_wxyz'][side],float)
        rotation=Rotation.from_quat(pose[3:][[1,2,3,0]]).as_matrix()
        points[side]=pose[:3]+rotation@np.array([0.,inner_planes[side],0.])
    return float((points['left']-points['right'])@hand_rotation[:,1])


def endpoint(stage,robot,controller,initial,geometry,plan):
    from pxr import UsdPhysics
    names={side:'fr3_finger_joint'+str(i) for side,i in (('left',1),('right',2))}
    hand='/World/envs/env_0/Robot/fr3_hand';axes={};records={}
    for side,name in names.items():
        prims=[p for p in stage.Traverse() if p.GetName()==name and p.IsA(UsdPhysics.PrismaticJoint)]
        if len(prims)!=1:raise RuntimeError('Actual prismatic joint mapping ambiguous')
        joint=UsdPhysics.PrismaticJoint(prims[0]);parent=joint.GetBody0Rel().GetTargets();child=joint.GetBody1Rel().GetTargets()
        if list(map(str,parent))!=[hand] or list(map(str,child))!=[geometry['fingers'][side]['body_path']]:raise RuntimeError('Finger joint body relations differ')
        axis=str(joint.GetAxisAttr().Get());q=joint.GetLocalRot0Attr().Get()
        if axis not in 'XYZ' or len(axis)!=1:raise RuntimeError('Unknown finger joint axis')
        vector=Rotation.from_quat([*q.GetImaginary(),q.GetReal()]).apply(np.eye(3)['XYZ'.index(axis)])
        expected=np.array([0.,1. if side=='left' else -1.,0.])
        if np.max(abs(vector-expected))>1e-6:raise RuntimeError('Actual finger opening axis differs')
        axes[side]=float(vector[1]);records[side]={'joint':name,'path':str(prims[0].GetPath()),'opening_axis_hand':vector.tolist()}
    inner={s:geometry['fingers'][s]['inner_plane_y_m'] for s in names}
    gap=model_gap(initial,inner);actual={s:initial['q'][robot.joint_names.index(n)] for s,n in names.items()}
    intercept=gap-axes['left']*actual['left']+axes['right']*actual['right']
    value=(plan['nominal_pad_gap_m']-intercept)/(axes['left']-axes['right'])
    limits=robot.data.joint_pos_limits[0].cpu().numpy();q0=np.mean(list(actual.values()))
    if not np.isfinite(value) or abs(value-plan['expected_finger_endpoint_m'])>plan['endpoint_derived_match_tolerance_m']:raise RuntimeError('Derived nominal endpoint differs')
    for side,name in names.items():
        lo,hi=limits[robot.joint_names.index(name)]
        if not lo<=value<=hi or not 0<=q0-value<=.004+2e-6:raise RuntimeError('Endpoint violates existing joint/travel limits')
        records[side].update(initial_q_m=float(actual[side]),inner_plane_finger_y_m=float(inner[side]),endpoint_q_m=float(value),limits_m=[float(lo),float(hi)])
    return {'frame':'fr3_hand','nominal_gap_m':plan['nominal_pad_gap_m'],'initial_actual_gap_m':gap,
            'gap_intercept_m':float(intercept),'gap_per_symmetric_q':float(axes['left']-axes['right']),
            'endpoint_q_m':float(value),'inner_planes_finger_y_m':inner,'fingers':records,
            'physical_Desk_command_mapping':'UNMEASURED; this is nominal model plane separation only'}


def verify_control(plan,current,initial,observer,output):
    """Require exact unchanged physical settings/q/normal reporting; no sensor equivalence claim."""
    hashes={}
    def read(name,item):
        p=Path(item['path']);digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest!=item['sha256']:raise RuntimeError('Pinned evidence changed: '+name)
        hashes[name]=digest;return json.loads(p.read_text())
    control={k:read('control_'+k,v) for k,v in plan['control_evidence'].items() if isinstance(v,dict) and 'sha256' in v}
    diagnostic={k:read('diagnostic_'+k,v) for k,v in plan['diagnostic_evidence'].items() if isinstance(v,dict) and 'sha256' in v}
    screen=read('screen_audit',plan['screen_evidence']['audit'])
    checks={'passed_full_duration_control':control['audit']['stationary_guard_passed'] is True and control['audit']['proceed_gate_passed'] is True and control['supervisor']['proceed_gate_passed'] is True and control['metadata']['steps_executed']==3600,
        'screen_stays_counterfactual':screen['evaluation_complete'] is True and screen['counterfactual_only'] is True and screen['proceed_gate_passed'] is False and all(screen['checks'].values())}
    for label,packet in (('control',control),('diagnostic',diagnostic)):
        meta=packet['metadata'];observed=packet['observer_metadata']
        checks[label+'_science']=meta['protocol_sha256']==plan['source_science_sha256']
        checks[label+'_physical_settings']=meta['settings_initial']==current
        checks[label+'_actual_initial_q']=meta['initial_joint_positions']==initial['q']
        checks[label+'_reporting_setting']=observed['observation_setting']['after'] is False and observer['observation_setting']['after'] is False
        checks[label+'_reporting_capacity']=observed['normal_and_friction_capacity_per_view']==observer['normal_and_friction_capacity_per_view']
        checks[label+'_reporting_filters']=observed['resolved_views']==observer['resolved_views']
    report={'passed':all(checks.values()),'checks':checks,'input_sha256':hashes,
        'reuse_scope':'Stationary physical/source/q/tool/contact-processing identity. RGB-D and native callbacks are passive observations, not identical control-mode sensors.',
        'prior_full_diagnostic_not_promoted':True}
    Path(output).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    if not report['passed']:raise RuntimeError('Startup control reuse bridge failed')
    return report

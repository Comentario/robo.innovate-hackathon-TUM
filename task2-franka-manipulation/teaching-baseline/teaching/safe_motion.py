"""Plan and certify a continuous joint realization of the requested Cartesian arc."""
import copy
import json
import math
from pathlib import Path
import numpy as np
import pinocchio as pin
from scipy.interpolate import CubicSpline
from scipy.spatial.transform import Rotation
from audit_kinematics import catalog_signature,yaw_variant
from kinematics import Kinematics

HERE=Path(__file__).resolve().parent


def blend(x):return x*x*x*(10+x*(-15+6*x))


def curve(control,u):
    p=control.copy()
    for size in range(5,0,-1):p[:size]=(1-u)*p[:size]+u*p[1:size+1]
    return p[0]


def target_path(start,target,control,u,long_rotation=False):
    a=np.array(start).reshape((4,4),order='F');b=np.array(target).reshape((4,4),order='F')
    rotation=Rotation.from_matrix(a[:3,:3].T@b[:3,:3]).as_rotvec()
    magnitude=np.linalg.norm(rotation)
    if long_rotation and magnitude>1e-6:rotation*=1-2*math.pi/magnitude
    xyz=curve(control,u)
    result=np.eye(4);result[:3,:3]=Rotation.from_matrix(a[:3,:3]).as_matrix()@Rotation.from_rotvec(rotation*blend(u)).as_matrix();result[:3,3]=xyz
    return result.reshape(-1,order='F').tolist()


def spline_bounds(spline):
    c=spline.c;h=np.diff(spline.x)[:,None]
    a,b,d,e=c[0],c[1],c[2],c[3]
    # Bernstein hulls bound each cubic and its derivatives on every interval.
    values=np.stack([e,e+d*h/3,e+2*d*h/3+b*h*h/3,e+d*h+b*h*h+a*h**3])
    first=np.stack([d,d+b*h,d+2*b*h+3*a*h*h])
    second=np.stack([2*b,2*b+6*a*h])
    return dict(lower=values.min(axis=(0,1)),upper=values.max(axis=(0,1)),
                d1=np.abs(first).max(axis=(0,1)),d2=np.abs(second).max(axis=(0,1)),
                d3=np.abs(6*a).max(axis=0))


def fixed_parameters(model):
    ee=model.model.frames[model.ee]
    if any(model.model.joints[i].shortname()!='JointModelRZ' for i in range(1,8)):
        raise RuntimeError('Unsupported actual robot joint type')
    return dict(joint_origins=[v.homogeneous.reshape(-1,order='F').tolist() for v in model.model.jointPlacements[1:]],
                joint7_to_ee=ee.placement.homogeneous.reshape(-1,order='F').tolist(),
                model_sha256=model.model_sha256)


def certify(model,spline,start,target,control,planner,long_rotation=False):
    bounds=spline_bounds(spline);policy=model.policy
    if np.any(bounds['lower']<model.lower-1e-8) or np.any(bounds['upper']>model.upper+1e-8):
        raise RuntimeError('Joint spline violates a continuous joint-limit bound')
    if policy['min_abs_joint2_rad']>0 and (min(abs(bounds['lower'][1]),abs(bounds['upper'][1]))<policy['min_abs_joint2_rad'] or bounds['lower'][1]*bounds['upper'][1]<=0):
        raise RuntimeError('Joint spline approaches/crosses the shoulder singularity margin')
    extension=-.467002423653011
    if bounds['lower'][3]<extension+policy['min_elbow_extension_margin_rad'] and bounds['upper'][3]>extension-policy['min_elbow_extension_margin_rad']:
        raise RuntimeError('Joint spline approaches the elbow-extension margin')
    reach=sum(np.linalg.norm(v.translation) for v in model.model.jointPlacements[1:])+np.linalg.norm(model.model.frames[model.ee].placement.translation)
    jacobian_lipschitz=math.sqrt(7)*math.sqrt((4*reach/policy['characteristic_length_m'])**2+1)
    speed_sum=float(bounds['d1'].sum())
    count=max(1000,math.ceil(jacobian_lipschitz*speed_sum/(2*planner['jacobian_certificate_slack'])))
    if count>planner['maximum_certificate_intervals']:
        raise RuntimeError('Joint path changes too sharply to certify within configured resolution')
    metric_uncertainty=jacobian_lipschitz*speed_sum/(2*count)
    min_full=min_fixed=math.inf;max_condition=0;max_position_error=0;max_angle_error=0;max_full=max_fixed=0
    parameters=np.linspace(0,1,count+1)
    # Bound Jacobian variation between samples. External collision clearance
    # remains a separate physical requirement, not a consequence of these bounds.
    for u,q in zip(parameters,spline(parameters)):
        metrics=model.metrics(q)
        min_full=min(min_full,metrics['full_sigma_min']);min_fixed=min(min_fixed,metrics['fixed_elbow_sigma_min'])
        max_condition=max(max_condition,metrics['full_condition'],metrics['fixed_elbow_condition'])
        max_full=max(max_full,metrics['full_condition']*metrics['full_sigma_min'])
        max_fixed=max(max_fixed,metrics['fixed_elbow_condition']*metrics['fixed_elbow_sigma_min'])
        if min_full-metric_uncertainty<policy['min_full_sigma'] or min_fixed-metric_uncertainty<policy['min_fixed_elbow_sigma']:
            raise RuntimeError('Continuous Jacobian singularity margin cannot be certified')
    certified_condition=max((max_full+metric_uncertainty)/(min_full-metric_uncertainty),
                            (max_fixed+metric_uncertainty)/(min_fixed-metric_uncertainty))
    if certified_condition>policy['max_condition']:
        raise RuntimeError('Continuous Jacobian condition-number bound exceeds configured limit')
    for u,q in zip(np.linspace(0,1,501),spline(np.linspace(0,1,501))):
        expected=model.target(target_path(start,target,control,float(u),long_rotation));actual=model.fk(q)
        max_position_error=max(max_position_error,float(np.linalg.norm(actual.translation-expected.translation)))
        max_angle_error=max(max_angle_error,float(np.linalg.norm(pin.log3(actual.rotation.T@expected.rotation))))
    if max_position_error>planner['maximum_arc_deviation_m'] or max_angle_error>planner['maximum_arc_angle_deviation_rad']:
        raise RuntimeError('Joint spline does not follow the Cartesian arc within tolerance')
    h1,h2,h3=1.875,10/math.sqrt(3),60
    velocity=bounds['d1']*h1
    acceleration=bounds['d2']*h1*h1+bounds['d1']*h2
    jerk=bounds['d3']*h1**3+3*bounds['d2']*h1*h2+bounds['d1']*h3
    required=max(float(np.max(velocity))/(planner['joint_velocity_headroom']*planner['joint_velocity_limit']),
                 math.sqrt(float(np.max(acceleration))/planner['max_joint_acceleration_rad_s2']),
                 (float(np.max(jerk))/planner['max_joint_jerk_rad_s3'])**(1/3))
    return dict(certificate_intervals=count,jacobian_variation_bound=metric_uncertainty,
                certified_min_full_sigma=min_full-metric_uncertainty,
                certified_min_fixed_elbow_sigma=min_fixed-metric_uncertainty,
                maximum_sampled_condition=max_condition,certified_max_condition=certified_condition,maximum_arc_deviation_m=max_position_error,
                maximum_arc_angle_deviation_rad=max_angle_error,
                required_joint_duration_s=required,derivative_bounds={k:v.tolist() for k,v in bounds.items()})


def build_joint_plan(point_id,target,state,control,catalog_bytes,config,direct=False):
    policy=config['singularity_avoidance'];planner=copy.deepcopy(config['joint_planner'])
    planner['joint_velocity_limit']=config['max_joint_velocity_rad_s']
    model=Kinematics(state['F_T_EE'],policy);q0=np.array(state['q'])
    actual=model.fk(q0);measured=model.target(state['O_T_EE'])
    if np.linalg.norm(actual.translation-measured.translation)>.0001 or np.linalg.norm(pin.log3(actual.rotation.T@measured.rotation))>.001:
        raise RuntimeError('Robot model does not reproduce the current configured TCP')
    if not model.acceptable(q0):
        raise RuntimeError('Starting arm configuration is already inside the singularity margin; hand-guide to a regular configuration before motion')
    sign=(1 if q0[1]>0 else -1) if planner.get('constrain_shoulder_sign',False) else None
    cache_path=HERE/'kinematic_catalog.json';cached=None
    if cache_path.exists():
        candidate=json.loads(cache_path.read_text())
        if candidate['source_signature']==catalog_signature(catalog_bytes,policy,model.model_sha256):cached=candidate
    seeds=[q0]
    catalog=json.loads(catalog_bytes)
    taught=catalog['points'].get(f'point_{int(point_id):02d}') if str(point_id).isdecimal() else None
    if taught is None:
        taught=min(catalog['points'].values(),key=lambda p:np.linalg.norm(np.array(p['O_T_EE'][12:15])-np.array(target[12:15])))
    seeds.append(np.array(taught['q_rad']))
    for a in (-1,1):
        for b in (-1,1):
            mirrored=np.array(taught['q_rad']);mirrored[0]+=a*math.pi;mirrored[1]*=-1;mirrored[2]+=b*math.pi
            if np.all(mirrored>=model.lower) and np.all(mirrored<=model.upper):seeds.append(mirrored)
    seeds.extend(np.array(catalog['points'][f'point_{i:02d}']['q_rad']) for i in (3,15,1))
    for elbow in (-1.8,-.8,.8,1.8):
        for wrist in (-2,2):
            seed=q0.copy();seed[0]=-.5 if elbow>0 else .5;seed[2]=elbow;seed[4]=wrist;seed[5]=3.9;seeds.append(seed)
    variants=[0] if direct or str(point_id)=='1' or not policy['allow_yaw180_for_bricks'] else [0,180]
    failures=[];plans=[]
    for yaw in variants:
        effective=yaw_variant(target,yaw)
        goals=[]
        if cached and str(point_id) in cached['poses']:
            for solution in cached['poses'][str(point_id)]['candidates']:
                if solution['yaw_variant_deg']==yaw and (sign is None or solution['shoulder_sign']==sign):
                    fit=model.solve(effective,solution['q'],sign,None,max_evaluations=80)
                    if fit:goals.append(fit)
        for seed in seeds:
            fit=model.solve(effective,seed,sign,None,max_evaluations=100)
            if fit and all(np.linalg.norm(np.array(fit['q'])-g['q'])>.15 for g in goals):goals.append(fit)
            if len(goals)>=6:break
        columns=[0,1,3,4,5,6]
        chart_sign=np.sign(np.linalg.det(model.jacobian(q0)[:,columns]))
        goals=[g for g in goals if np.sign(np.linalg.det(model.jacobian(g['q'])[:,columns]))==chart_sign]
        goals.sort(key=lambda g:np.linalg.norm(np.array(g['q'])-q0))
        relative=Rotation.from_matrix(np.array(state['O_T_EE']).reshape(4,4,order='F')[:3,:3].T@np.array(effective).reshape(4,4,order='F')[:3,:3]).magnitude()
        rotations=[False,True] if not direct and relative>math.pi/2 else [False]
        for elbow_schedule,long_rotation,goal in [(schedule,long,g) for schedule in ('early','uniform','late','posture') for long in rotations for g in goals[:2]]:
            print(f'KINEMATIC_PREFLIGHT yaw={yaw}; long_rotation={long_rotation}; elbow={elbow_schedule}; checking complete path',flush=True)
            qs=[q0.copy()];knots=np.linspace(0,1,planner['path_knots'])
            try:
                for u in knots[1:]:
                    desired=target_path(state['O_T_EE'],effective,control,float(u),long_rotation)
                    preferred=(1-blend(u))*q0+blend(u)*np.array(goal['q'])
                    fraction=blend(min(u/.5,1)) if elbow_schedule=='early' else blend(max((u-.5)/.5,0)) if elbow_schedule=='late' else blend(u)
                    elbow=(1-fraction)*q0[2]+fraction*goal['q'][2]
                    fit=(model.solve(desired,qs[-1],sign,None,max_evaluations=80,preferred=preferred) if elbow_schedule=='posture' else model.solve_elbow(desired,qs[-1],sign,elbow))
                    if not fit:raise RuntimeError(f'No margin-valid IK solution at arc fraction {u:.3f}')
                    q=np.array(fit['q'])
                    if np.max(np.abs(q-qs[-1]))>planner['max_knot_joint_step_rad']:
                        raise RuntimeError(f'Joint branch changes abruptly at arc fraction {u:.3f}')
                    qs.append(q)
                spline=CubicSpline(knots,np.array(qs),axis=0)
                certificate=certify(model,spline,state['O_T_EE'],effective,control,planner,long_rotation)
                plans.append(dict(effective_target=effective,yaw_variant_deg=yaw,long_rotation=long_rotation,elbow_schedule=elbow_schedule,
                    knots=knots.tolist(),coefficients=spline.c.transpose(1,2,0).tolist(),
                    initial_q=q0.tolist(),final_q=qs[-1].tolist(),certificate=certificate,
                    fixed_model=fixed_parameters(model),policy=policy,planner=planner,
                    model_sha256=model.model_sha256,
                    warning='Model validation does not certify camera/cable clearance or the proprietary Desk warning threshold.'))
                break
            except RuntimeError as exc:failures.append(f'yaw {yaw}: {exc}')
        if plans and yaw==0:break # Preserve canonical orientation whenever a full safe path exists.
    if not plans:
        raise RuntimeError('No singularity-margin-certified path. '+('; '.join(failures) or 'No endpoint candidate in the current shoulder family'))
    return min(plans,key=lambda p:p['certificate']['required_joint_duration_s'])

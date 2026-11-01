"""Plan a bounded continuous arc for a saved Cartesian pose; execute through libfranka."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np

HERE=Path(__file__).resolve().parent


def blend(t):
    return t*t*t*(10+t*(-15+6*t))


def bezier(control,u):
    n=len(control)-1
    basis=np.array([math.comb(n,k)*u**k*(1-u)**(n-k) for k in range(n+1)]).T
    return basis@control


def duration_bound(control,angle,config):
    # Bound all times, including between grid points, using derivative hulls
    # and the mean-value theorem. Time derivatives below use normalized time.
    n=10000
    tau=np.linspace(0,1,n+1)
    u=blend(tau)
    h1=30*tau*tau*(1-tau)**2
    h2=60*tau*(1-tau)*(1-2*tau)
    h3=60-360*tau+360*tau*tau
    derivatives=[control]
    for order in range(1,5):
        derivatives.append((6-order)*np.diff(derivatives[-1],axis=0))
    p1,p2,p3=[bezier(derivatives[k],u) for k in (1,2,3)]
    velocity=p1*h1[:,None]
    acceleration=p2*h1[:,None]**2+p1*h2[:,None]
    jerk=p3*h1[:,None]**3+3*p2*(h1*h2)[:,None]+p1*h3[:,None]
    d1,d2,d3,d4=[float(np.linalg.norm(derivatives[k],axis=1).max()) for k in (1,2,3,4)]
    h1max,h2max,h3max,h4max=1.875,10/math.sqrt(3),60,360
    m2=d2*h1max**2+d1*h2max
    m3=d3*h1max**3+3*d2*h1max*h2max+d1*h3max
    m4=(d4*h1max**4+6*d3*h1max*h1max*h2max+3*d2*h2max*h2max
        +4*d2*h1max*h3max+d1*h4max)
    bounds=[float(np.linalg.norm(v,axis=1).max())+margin/(2*n)
            for v,margin in zip((velocity,acceleration,jerk),(m2,m3,m4))]
    # Orientation follows smootherstep(u), matching horizontal travel progress.
    angular=[angle*h1max**2,angle*(h2max*h1max*h1max+h1max*h2max),
             angle*(h3max*h1max**3+3*h2max*h1max*h2max+h1max*h3max)]
    linear_limits=[config['max_translation_velocity_m_s'],config['max_translation_acceleration_m_s2'],config['max_translation_jerk_m_s3']]
    angular_limits=[config['max_rotation_velocity_rad_s'],config['max_rotation_acceleration_rad_s2'],config['max_rotation_jerk_rad_s3']]
    distance=float(np.linalg.norm(control[-1]-control[0]))
    nominal=config['reference_move_duration_s']*(distance/config['workspace_reference_distance_m'])**(1/3)
    derivative_seconds=max([(b/l)**(1/(i+1)) for group,limits in ((bounds,linear_limits),(angular,angular_limits))
                            for i,(b,l) in enumerate(zip(group,limits))])
    seconds=max(config['minimum_move_duration_s'],nominal,derivative_seconds*1.05)
    return seconds,dict(nominal_distance_time_s=nominal,derivative_required_time_s=derivative_seconds*1.05,
                        straight_distance_m=distance,translation_derivative_bounds=bounds,angular_derivative_bounds=angular,
                        estimated_peak_velocity_m_s=bounds[0]/seconds,
                        estimated_peak_acceleration_m_s2=bounds[1]/seconds**2,
                        estimated_peak_jerk_m_s3=bounds[2]/seconds**3)


def write_joint_input(directory,plan,start,target,tool,control,config,seconds):
    from kinematics import Kinematics
    model=Kinematics(tool,plan['policy']);p=plan['planner']
    margin=plan['policy']['joint_limit_margin_rad']-p['live_joint_limit_margin_rad']
    values=([2,len(plan['knots'])]+start+target+tool+plan['initial_q']+control.reshape(-1).tolist()
        +config['workspace_bounds_m']['min']+config['workspace_bounds_m']['max']
        +[seconds,config['max_callback_gap_s'],config['max_translation_velocity_m_s'],
          config['max_rotation_velocity_rad_s'],config['max_joint_velocity_rad_s'],
          config['endpoint_position_tolerance_m'],config['endpoint_orientation_tolerance_rad'],
          config['stationary_start_stable_time_s'],config['stationary_start_timeout_s'],config['control_cpu'],
          plan['policy']['characteristic_length_m'],p['min_live_full_sigma'],p['min_live_fixed_elbow_sigma'],
          p['max_live_condition'],p['min_live_abs_joint2_rad'],p['min_live_elbow_extension_margin_rad'],int(plan['long_rotation']),int(config.get('joint_rate_limiting_enabled',False))]
        +(model.lower-margin).tolist()+(model.upper+margin).tolist()
        +np.array(plan['fixed_model']['joint_origins']).reshape(-1).tolist()+plan['fixed_model']['joint7_to_ee'])
    for u,coefficients in zip(plan['knots'][:-1],plan['coefficients']):
        values+=[u]+np.array(coefficients).reshape(-1).tolist()
    values+=[plan['knots'][-1]]
    destination=directory/'joint_input.txt'
    destination.write_text('\n'.join(format(x,'.17g') for x in values)+'\n')
    (directory/'robot_model.urdf').write_bytes((HERE/'robot_model.urdf').read_bytes())
    return destination


def run_arc(point_id,target,capture,catalog_bytes,point,execute,overrides):
    from safe_motion import build_joint_plan
    config=json.loads((HERE/'motion_config.json').read_text())
    state=capture['state'];start=state['O_T_EE'];height=config['vertical_standoff_m']
    direct=overrides.get('relative_z_mm') is not None or overrides.get('direct_saved_grasp',False) or overrides.get('direct_vertical',False)
    grasp_requested=overrides.get('target_kind')=='grasp_reference'
    start_xyz=np.array(start[12:15]);target_xyz=np.array(target[12:15])
    lower=np.array(config['workspace_bounds_m']['min']);upper=np.array(config['workspace_bounds_m']['max'])
    departure=0 if direct else min(height,float(upper[2]-start_xyz[2]))
    arrival=0 if direct else min(height,float(upper[2]-target_xyz[2]))
    directory=HERE/'moves'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');directory.mkdir(parents=True)
    request=dict(point=point_id,trajectory='certified_joint_arc',execute=execute,
                 canonical_target_O_T_EE=target,temporary_overrides=overrides,motion_config=config,
                 taught_point=point,catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),grasp_offset_executed=bool(execute and grasp_requested))
    (directory/'start_capture.json').write_text(json.dumps(capture,indent=2)+'\n')
    (directory/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    print('Motion log:',directory/'execution.log',flush=True)
    try:
        if execute and not config.get('verified_joint_plans_enabled'):
            raise RuntimeError('Singularity-checked execution is disabled in motion_config.json')
        if departure<0 or arrival<0:raise RuntimeError('Current or target height is above the cleared workspace ceiling')
        up=np.array([0,0,1]);control=np.array([start_xyz,start_xyz+departure*up,start_xyz+departure*up,
                                           target_xyz+arrival*up,target_xyz+arrival*up,target_xyz])
        if not np.isfinite(control).all() or np.any(control<lower-1e-9) or np.any(control>upper+1e-9):
            raise RuntimeError('Arc control points exceed the operator-cleared workspace envelope')
        if max(abs(a-b) for a,b in zip(state['F_T_EE'],point['tool_frames']['F_T_EE']))>1e-6:
            raise RuntimeError('Tool frame differs from the saved pose')
        plan=build_joint_plan(point_id,target,state,control,catalog_bytes,config,direct=direct)
        target=plan['effective_target']
        trace=sum(start[c*4+r]*target[c*4+r] for c in range(3) for r in range(3))
        angle=math.acos(max(-1,min(1,(trace-1)/2)))
        if plan['long_rotation'] and angle>1e-6:angle=2*math.pi-angle
        seconds,bounds=duration_bound(control,angle,config)
        seconds=max(seconds,plan['certificate']['required_joint_duration_s']*1.05)
        bounds.update(base_duration_s=seconds,time_scale=overrides.get('time_scale',1))
        seconds*=overrides.get('time_scale',1)
        request.update(target_xyz_m=target[12:15],target_O_T_EE=target,yaw_variant_deg=plan['yaw_variant_deg'],
                       long_rotation=plan['long_rotation'],
                       control_points_m=control.tolist(),duration_s=seconds,derivative_bounds=bounds,
                       actual_guide_offsets_m=dict(departure=departure,arrival=arrival),certificate=plan['certificate'])
        (directory/'joint_plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        (directory/'request.json').write_text(json.dumps(request,indent=2)+'\n')
        frozen=write_joint_input(directory,plan,start,target,state['F_T_EE'],control,config,seconds)
        print(f'Certified arc: {seconds:.1f} s; equivalent yaw {plan["yaw_variant_deg"]} deg; target XYZ mm {target_xyz*1000}',flush=True)
        # Independent fixed-size FK/Jacobian implementation checks the frozen
        # joint curve before the executable is allowed to connect for motion.
        checked=subprocess.run([str(HERE/'joint_move'),str(frozen),str(directory/'model_check.csv'),'--check'],capture_output=True,text=True)
        (directory/'preflight.log').write_text(checked.stdout+checked.stderr)
        if checked.returncode:raise RuntimeError('Executable model check failed: '+checked.stdout+checked.stderr)
    except Exception as error:
        reason=str(error);print('STOP preflight:',reason,flush=True)
        (directory/'execution.log').write_text('PREFLIGHT_BLOCKED '+reason+'\nNO_MOTION_SENT\n')
        (directory/'outcome.json').write_text(json.dumps(dict(completed=False,preflight_blocked=True,motion_sent=False,reason=reason),indent=2)+'\n')
        return 1
    with (directory/'execution.log').open('w') as log:
        command=[str(HERE/'joint_move'),str(frozen),str(directory/'trace.csv'),'--execute' if execute else '--preview']
        if execute and config.get('performance_profile_hold',False):
            command=['powerprofilesctl','launch','--profile','performance','--reason','Franka FCI real-time motion','--appid','franka-teaching']+command
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            for line in process.stdout:
                log.write(line);log.flush()
                if line.startswith(('START_STATE ','FINAL_STATE ','LAST_STATE ')):
                    label,payload=line.split(' ',1);s=json.loads(payload)
                    print(label,'XYZ_m',s['O_T_EE'][12:15],'mode',s['robot_mode'],'errors',s['current_errors'],flush=True)
                else:print(line,end='',flush=True)
            status=process.wait()
        except KeyboardInterrupt:
            process.send_signal(2);process.wait();status=130
    launcher_status=status
    lines=(directory/'execution.log').read_text().splitlines()
    final=next((json.loads(line.split(' ',1)[1]) for line in reversed(lines) if line.startswith('FINAL_STATE ')),None)
    passed=final is not None and 'PASS certified joint arc' in lines
    if execute and status==0 and not passed:status=1
    (directory/'exit_status.json').write_text(json.dumps(dict(returncode=status,launcher_returncode=launcher_status,controller_pass_verified=passed))+'\n')
    summary=dict(completed=bool(execute and status==0),preview_only=not execute,requested_point=point_id,trajectory='certified_joint_arc',
                 returncode=status,launcher_returncode=launcher_status,controller_pass_verified=passed,yaw_variant_deg=plan['yaw_variant_deg'],
                 saved_catalog_unchanged=hashlib.sha256((HERE/'positions.json').read_bytes()).hexdigest()==request['catalog_sha256'],
                 grasp_offset_executed=bool(execute and passed and grasp_requested),grasp_reference_reached=bool(execute and passed and grasp_requested),execution_log=str(directory/'execution.log'))
    if final:
        actual=final['O_T_EE'];tr=sum(actual[c*4+r]*target[c*4+r] for c in range(3) for r in range(3))
        summary.update(actual_xyz_m=actual[12:15],target_xyz_m=target[12:15],position_error_mm=math.dist(actual[12:15],target[12:15])*1000,
                       orientation_error_deg=math.degrees(math.acos(max(-1,min(1,(tr-1)/2)))),completion_errors=final['current_errors'])
    (directory/'outcome.json').write_text(json.dumps(summary,indent=2)+'\n')
    return status

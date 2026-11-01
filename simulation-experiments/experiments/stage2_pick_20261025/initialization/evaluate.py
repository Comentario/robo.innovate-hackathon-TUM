"""Independent fixed-initialization FK/readback and measured-clearance audit."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
STARTED=time.monotonic()
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'evaluation'))
from safety_views import audit_safety

NAMES=['fr3_joint'+str(i) for i in range(1,8)]
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rotation(q):
    q=np.asarray(q,float)
    if q.shape!=(4,) or not np.isfinite(q).all() or np.linalg.norm(q)==0:raise ValueError('Invalid WXYZ')
    w,x,y,z=q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def transform(pose):
    p=np.asarray(pose,float)
    if p.shape!=(7,) or not np.isfinite(p).all():raise ValueError('Invalid XYZ/WXYZ pose')
    result=np.eye(4);result[:3,:3]=rotation(p[3:]);result[:3,3]=p[:3];return result

def error(a,b):
    return {'position_m':float(np.linalg.norm(a[:3,3]-b[:3,3])),'angle_rad':float(np.arccos(np.clip((np.trace(a[:3,:3].T@b[:3,:3])-1)/2,-1,1)))}
def within(e,position,angle):return e['position_m']<=position and e['angle_rad']<=angle

def forward(chain,q):
    world=np.asarray(chain['T_world_root'],float).copy();current=chain['root'];seen=set();revolute=[];index=0
    if world.shape!=(4,4) or not np.isfinite(world).all():raise ValueError('Invalid root matrix')
    for joint in chain['joints']:
        if joint['parent']!=current or joint['child'] in seen:raise ValueError('Disconnected/cyclic hand chain')
        seen.add(joint['child']);current=joint['child'];a=np.asarray(joint['T_parent_joint']);b=np.asarray(joint['T_child_joint'])
        for name,matrix in [('local0',a),('local1',b)]:
            local=joint[name];reference=transform([*local['position_m'],*local['quaternion_wxyz']])
            if matrix.shape!=(4,4) or not np.allclose(matrix,reference,atol=1e-12,rtol=0):raise ValueError('Local frame/matrix disagreement')
        motion=np.eye(4)
        if joint['type']=='revolute':
            revolute.append(joint['name']);axis=np.asarray(joint['axis_vector'],float);expected=np.eye(3)['XYZ'.index(joint['axis'])]
            if not np.array_equal(axis,expected):raise ValueError('USD joint-axis mismatch')
            cross=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
            motion[:3,:3]=np.eye(3)+math.sin(q[index])*cross+(1-math.cos(q[index]))*(cross@cross);index+=1
        elif joint['type']!='fixed':raise ValueError('Unsupported joint type')
        world=world@a@motion@np.linalg.inv(b)
    if current!=chain['hand'] or revolute!=NAMES or index!=7:raise ValueError('Actual seven-arm-joint chain differs')
    return world,world@np.asarray(chain['T_hand_grip'])

def audit(folder,p):
    chain=read(folder/'kinematic_chain.json');d=read(folder/'kinematic_derivation.json');r=read(folder/'robot_initialization.json');meta=read(folder/'diagnostic_metadata.json');marker=read(folder/'diagnostic_complete.json');graph=read(folder/'evaluation_truth/graph.json');science=read(HERE.parent/'protocol.json')
    nominal=read(HERE/'inputs/nominal_proprioception.json');original=read(HERE/'inputs/nominal_capture_metadata.json');old_robot=read(HERE/'inputs/nominal_robot_initialization.json');prior=read(HERE/'inputs/prior_supervisor.json');checks={};metrics={};tol=p['pose_readback'];k=p['kinematics']
    checks['full_prior_cost_bound']=sha(HERE/'inputs/prior_supervisor.json')==p['prior_supervisor_sha256'] and prior['cumulative_case_seconds']==p['prior_case_seconds'] and prior['within_budget'] is True and prior['proceed_gate_passed'] is False
    checks['science_unchanged']=sha(HERE.parent/'protocol.json')==meta['science_sha256']==p['existing_scientific_protocol_sha256']
    checks['diagnostic_protocol_bound']=meta['diagnostic_protocol_sha256']==sha(HERE/'protocol.json') and d['init_protocol_sha256']==hashlib.sha256(json.dumps(p,sort_keys=True,allow_nan=False).encode()).hexdigest()
    checks['nominal_input_provenance']=sha(HERE/'inputs/nominal_capture_metadata.json')==p['nominal_capture_metadata_sha256'] and nominal['q']==original['initial_proprioception']['q'] and nominal['tcp_pose_world_wxyz']==original['initial_proprioception']['tcp_pose_world_wxyz']
    names=nominal['joint_names'];checks['explicit_actual_name_mapping']=names==old_robot['joint_names']==r['joint_names'] and len(names)==len(nominal['q']) and all(names.count(n)==1 for n in NAMES) and chain['joint_names']==d['joint_names']==NAMES
    seed=np.array([nominal['q'][names.index(n)] for n in NAMES]);q=np.asarray(d['q']);limits=np.asarray(chain['limits_rad']);asset_limits=np.asarray([j['limits_rad'] for j in chain['joints'] if j['type']=='revolute'])
    checks['one_finite_inlimits_configuration']=q.shape==(7,) and np.isfinite(q).all() and limits.shape==(7,2) and np.isfinite(limits).all() and np.all(limits[:,0]<limits[:,1]) and np.array_equal(limits,asset_limits) and bool(np.all(q>=limits[:,0]) and np.all(q<=limits[:,1])) and d['seed_q']==seed.tolist() and d['state_writes']==0 and d['simulation_steps']==0
    checks['fixed_solver_and_goal']=d['target_tcp_pose_wxyz']==k['goal_tcp_pose_world_wxyz'] and 0<=d['iterations']<=k['maximum_iterations'] and d['solver']=={'damping':k['damping'],'maximum_iterations':k['maximum_iterations'],'maximum_update_rad':k['maximum_joint_update_rad'],'position_tolerance_m':k['position_tolerance_m'],'angle_tolerance_rad':k['angle_tolerance_rad']}
    offset=transform([*science['tool_frames']['T_hand_grip_translation_m'],*science['tool_frames']['T_hand_grip_quaternion_wxyz']]);checks['same_measured_grip_frame']=bool(np.allclose(chain['T_hand_grip'],offset,atol=1e-12,rtol=0))
    nominal_hand,nominal_tcp=forward(chain,seed);metrics['nominal_TCP_FK']=error(nominal_tcp,transform(nominal['tcp_pose_world_wxyz']));checks['nominal_FK_matches_measured_proprio']=within(metrics['nominal_TCP_FK'],k['nominal_position_tolerance_m'],k['nominal_angle_tolerance_rad'])
    hand,tcp=forward(chain,q);metrics['independent_goal_error']=error(tcp,transform(k['goal_tcp_pose_world_wxyz']));checks['fixed_goal_converged']=within(metrics['independent_goal_error'],k['position_tolerance_m'],k['angle_tolerance_rad'])
    checks['derivation_pose_export_consistent']=within(error(hand,transform(d['predicted_hand_pose_wxyz'])),2e-6,1e-4) and within(error(tcp,transform(d['predicted_tcp_pose_wxyz'])),2e-6,1e-4)
    indices=[r['joint_names'].index(n) for n in NAMES];requested=np.asarray(r['requested_joint_positions_native_units'])[indices];actual=np.asarray(r['actual_joint_positions_native_units'])[indices];metrics['q_max_error_rad']=float(np.max(abs(actual-q)))
    checks['configured_and_actual_q_matches_derivation']=bool(np.isfinite(actual).all() and np.max(abs(requested-q))<=tol['q_atol'] and np.max(abs(actual-q))<=tol['q_atol'])
    for label,key in [('PhysX','hand_physics_pose_wxyz'),('USD','hand_usd_pose_wxyz')]:
        metrics[label+'_hand_vs_derived']=error(hand,transform(r[key]));checks[label+'_hand_matches_derived']=within(metrics[label+'_hand_vs_derived'],tol['position_m'],tol['angle_rad'])
    actual_hand,actual_tcp=forward(chain,actual);metrics['actual_q_TCP_vs_actual_proprio']=error(actual_tcp,transform(meta['initial_proprioception']['tcp_pose_world_wxyz']));checks['actual_TCP_proprio_matches_FK']=within(metrics['actual_q_TCP_vs_actual_proprio'],tol['position_m'],tol['angle_rad'])
    checks['full_native_graph_initialized']=len(set(graph['parts']))==len(graph['parts'])==graph['part_count']==301 and len(set(graph['connections']))==len(graph['connections'])==graph['edge_count']==930
    checks['zero_postnative_physics_and_same_clock']=meta['post_native_physics_steps']==marker['post_native_physics_steps']==0 and meta['initial_time_s']==meta['terminal_time_s']==marker['initial_time_s']==marker['terminal_time_s'] and marker['no_motion'] is True
    checks['capture_marker_complete']=marker['capture_completed'] is True
    selection=read(folder/'online/selection.json');geometry=read(folder/'tool_geometry.json')
    checks['one_sensor_candidate_diagnostic_only']=selection['diagnostic_only'] is True and selection.get('candidate') is not None and marker['candidate_tested']==selection['candidate']['candidate_id']
    if selection['clearance'].get('evidence_file'):
        viewchecks,views=audit_safety(folder,selection,meta,geometry,science);checks.update(viewchecks)
    else:
        checks['complete_measured_clearance_evidence']=False;views={'status':'UNTESTED_NO_COMPLETE_POINT_EVIDENCE','reason':marker.get('reason')}
    checks['unresolved_points_still_stop']=selection['clearance']['passed'] is True and marker['sensor_clearance_passed'] is True
    return {'checks':{key:bool(value) for key,value in checks.items()},'metrics':metrics,'geometry_safety':views,'candidate_under_test':marker['candidate_tested'],'diagnostic_only':True,'fresh_matched_control_required':True,'old_control_compatible':False,'manipulation_authorized':False,'scope':p['scope']}

def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ['input','output']:parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    p=read(HERE/'protocol.json');sup=read(args.input/'supervisor.json');capture=float(sup['capture_wall_seconds']);prior=p['prior_case_seconds'];limit=p['maximum_diagnostic_active_seconds'];result={'gate_passed':False,'proceed_gate_passed':False,'diagnostic_only':True,'manipulation_authorized':False,'protocol_sha256':sha(HERE/'protocol.json')}
    def stop(*_):raise TimeoutError('Frozen initialization diagnostic budget exhausted')
    signal.signal(signal.SIGALRM,stop)
    try:
        remaining=min(limit-capture,p['aggregate_case_ceiling_seconds']-prior-capture)-(time.monotonic()-STARTED)
        if not math.isfinite(capture) or capture<0 or remaining<=0:raise ValueError('No diagnostic audit budget remains')
        signal.setitimer(signal.ITIMER_REAL,remaining)
        if sup['prior_case_wall_seconds']!=prior or sup['diagnostic_limit_seconds']!=limit or sup['aggregate_case_ceiling_seconds']!=p['aggregate_case_ceiling_seconds']:raise ValueError('Supervisor diagnostic budget binding mismatch')
        if sup['capture_completed'] is not True:result.update(status='INCOMPLETE_CAPTURE')
        else:
            result.update(audit(args.input,p));result['checks']['diagnostic_and_aggregate_budget']=capture+time.monotonic()-STARTED<=limit and prior+capture+time.monotonic()-STARTED<=p['aggregate_case_ceiling_seconds'];result['gate_passed']=result['proceed_gate_passed']=all(result['checks'].values());result['status']='scored_complete'
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result.update(capture_wall_seconds=capture,audit_wall_seconds=time.monotonic()-STARTED,prior_case_wall_seconds=prior,cumulative_case_seconds=prior+capture+time.monotonic()-STARTED);args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        (args.output/'complete.json').write_text(json.dumps({'completed':True,'proceed_gate_passed':result['proceed_gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')
if __name__=='__main__':main()

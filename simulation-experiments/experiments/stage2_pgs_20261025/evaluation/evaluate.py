"""Frozen round3 phase gate; existing captures only, no solve or physics rerun."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def angles(a, b):
    norms = np.linalg.norm(a, axis=1)*np.linalg.norm(b, axis=1)
    if np.any(norms < 1e-12):
        return np.full(len(a), np.inf)
    return 2*np.arccos(np.clip(abs(np.sum(a*b, axis=1))/norms,0,1))


def same_thresholds(value, expected):
    return all(value.get(k) == v for k,v in expected.items()) and set(value)-{'debug_dump'} == set(expected)


def scene_is_pgs(scenes):
    return bool(scenes) and all(s.get('solverType',s.get('physxScene:solverType')) == 'PGS' for s in scenes)


def audit_a(args, protocol, checks):
    for name, digest in protocol['copied_eccentric_helpers_sha256'].items():
        if sha(HERE/'eccentric'/name) != digest:
            raise ValueError('Frozen eccentric helper changed: '+name)
    if sha(args.baseline_audit) != protocol['A']['baseline_audit_sha256']:
        raise ValueError('Frozen TGS audit changed')
    baseline = read(args.baseline_audit)
    target = args.output/'eccentric'
    subprocess.run([sys.executable,str(HERE/'eccentric/evaluate.py'),'--input',str(args.input),'--output',str(target)],check=True)
    current = read(target/'evaluation.json')
    meta = read(args.input/'fixture_metadata.json')
    rows = [json.loads(s) for s in (args.input/'trace.jsonl').read_text().splitlines()]
    common = protocol['common']
    checks['eccentric_integrity'] = current['all_integrity_checks_pass']
    checks['exact_eight_aligned_records'] = [r['step'] for r in current['records']] == list(range(1,9)) == [r['step'] for r in baseline['records']]
    checks['no_failure'] = current['first_failure'] is None and all(not r['reasons'] and not r['break_events'] for r in rows)
    checks['actual_scene_PGS'] = scene_is_pgs([meta['physics_scene_attributes']])
    checks['configured_PGS'] = meta['protocol']['solver']['type'] == 'PGS'
    checks['same_initial_actual_state_hash'] = sha(args.input/'states_initial.npy') == protocol['A']['baseline_initial_states_sha256']
    checks['authored_actor_32_4'] = all(a['usd_physics_attributes'].get('physxRigidBody:solverPositionIterationCount') == 32 and a['usd_physics_attributes'].get('physxRigidBody:solverVelocityIterationCount') == 4 for a in meta['actors'].values())
    checks['same_native_physical_thresholds'] = same_thresholds(meta['thresholds_initial'],common['native_breakage'])
    checks['native_binary'] = meta['native_core_sha256'] == common['native_core_sha256']
    checks['old_pose_bounds'] = all(r['max_position_drift_m'] <= common['maximum_position_drift_m'] and r['max_orientation_drift_rad'] <= common['maximum_orientation_drift_rad'] for r in rows)
    pairs = []
    for row, old in zip(current['records'],baseline['records']):
        limit = protocol['A']['maximum_H_to_same_step_frozen_TGS_ratio']*old['H_norm_Nms']
        pairs.append({'step':row['step'],'J_residual_Ns':row['J_residual_norm_Ns'],'H_norm_Nms':row['H_norm_Nms'],'frozen_TGS_H_norm_Nms':old['H_norm_Nms'],'H_limit_Nms':limit,'H_screen_pass':row['H_norm_Nms'] <= limit,'J_screen_pass':row['J_residual_norm_Ns'] <= protocol['A']['maximum_J_minus_gravity_norm_Ns']})
    checks['all_eight_H_screen'] = len(pairs) == 8 and all(r['H_screen_pass'] for r in pairs)
    checks['all_eight_J_screen'] = len(pairs) == 8 and all(r['J_screen_pass'] for r in pairs)
    return {'comparison':pairs,'base_eccentric_evaluation':str(target/'evaluation.json'),'angular_velocity_delta_momentum':'Descriptive only; see unchanged base audit, not an additional acceptance gate.','iteration_evidence':'Authored USD32/4 for A; actual executed island count unmeasured.'}


def audit_idle(args, protocol, checks):
    common, phase = protocol['common'],protocol[args.phase]
    settings = read(args.input/'pgs_settings.json')
    report = read(args.input/'idle_report.json')
    rows = [json.loads(s) for s in (args.input/'idle_trace.jsonl').read_text().splitlines()]
    ids = read(args.input/'idle_source_ids.json')
    baseline_ids = read(args.baseline_idle/'idle_source_ids.json')
    if sha(args.baseline_idle/'idle_states_initial.npy') != protocol['idle_reference']['initial_states_sha256']:
        raise ValueError('Frozen baseline initial states changed')
    baseline = np.load(args.baseline_idle/'idle_states_initial.npy',allow_pickle=False)
    initial = np.load(args.input/'idle_states_initial.npy',allow_pickle=False)
    excluded = set(phase.get('removed_source_ids',[]))
    wanted = [name for name in baseline_ids if name not in excluded]
    checks['exact_source_inventory_order'] = ids == wanted and len(ids) == phase['source_parts'] and len(set(ids)) == len(ids)
    expected = baseline[[baseline_ids.index(name) for name in ids]]
    checks['finite_initial_states'] = initial.shape == expected.shape == (phase['source_parts'],13) and bool(np.isfinite(initial).all())
    checks['initial_positions'] = bool(np.max(np.linalg.norm(initial[:,:3]-expected[:,:3],axis=1)) <= common['initial_position_tolerance_m'])
    checks['initial_orientations'] = bool(np.max(angles(initial[:,3:7],expected[:,3:7])) <= common['initial_orientation_tolerance_rad'])
    checks['initial_velocities'] = bool(np.max(abs(initial[:,7:]-expected[:,7:])) <= common['initial_velocity_tolerance'])
    checks['actual_scene_PGS'] = all(scene_is_pgs(settings[when]['physics_scenes']) for when in ['initial','terminal'])
    checks['configured_PGS'] = settings['solver_type_configured'] == 'PGS'
    checks['native_binary'] = settings['native_core_sha256'] == common['native_core_sha256']
    checks['dt_epsilon_unchanged'] = settings['dt_s'] == common['dt_s'] and settings['OSQP_EPSILON'] == common['OSQP_EPSILON']
    for when in ['initial','terminal']:
        snapshot = settings[when]
        actors = {path:snapshot['actor_settings'][path] for path in settings['source_paths']}
        checks['runtime_actor_inventory_'+when] = {name.rsplit('/',1)[-1] for name in actors} == set(ids)-{'plate_source'}
        checks['runtime_32_4_'+when] = len(actors) == phase['source_bricks'] and all(a.get('runtime_position') == 32 and a.get('runtime_velocity') == 4 and a.get('authored_position') == 32 and a.get('authored_velocity') == 4 for a in actors.values())
        checks['physical_thresholds_'+when] = same_thresholds(snapshot['native_breakage'],common['native_breakage']) and snapshot['native_assembly'] == common['native_assembly']
        checks['scene_clamps_admit_32_4_'+when] = all(s['minPositionIterationCount'] <= 32 <= s['maxPositionIterationCount'] and s['minVelocityIterationCount'] <= 4 <= s['maxVelocityIterationCount'] for s in snapshot['physics_scenes'])
    before, after = settings['factory']['before'], settings['factory']['after']
    checks['factory_changes_solver_only'] = before['solver_type'] == 1 and after == {**before,'solver_type':0}
    checks['initial_terminal_readbacks_unchanged'] = all(settings['initial'][key] == settings['terminal'][key] for key in ['physics_scenes','actor_settings','native_breakage','native_assembly'])
    checks['intended_change_only_declared'] = settings['changed_fields'] == ['solver_type:TGS->PGS']
    checks['exact_step_sequence'] = [r['step'] for r in rows] == list(range(121))
    checks['no_events_or_failures'] = report['failure'] is None and all(not r['reasons'] and not r['broken_connections'] for r in rows)
    checks['counts_all_steps'] = all(r['source_parts'] == phase['source_parts'] and r['native_connections'] == phase['native_connections'] for r in rows)
    checks['finite_all_steps'] = all(r['finite'] and r['robot_finite'] for r in rows)
    checks['drift_all_steps'] = all(r['max_position_drift_m'] <= common['maximum_position_drift_m'] and r['max_orientation_drift_rad'] <= common['maximum_orientation_drift_rad'] for r in rows)
    checks['clock_association'] = all(abs(r['physics_time_s']-rows[0]['physics_time_s']-r['step']*common['dt_s']) <= common['simulation_clock_tolerance_s'] for r in rows)
    nominal = np.asarray(common['joint_positions'])
    checks['nominal_q_all_steps'] = all(r['joint_positions'] is not None and np.isfinite(r['joint_positions']).all() and np.max(abs(np.asarray(r['joint_positions'])-nominal)) <= common['joint_position_tolerance'] and r['joint_velocities'] is not None and np.isfinite(r['joint_velocities']).all() and np.max(abs(np.asarray(r['joint_velocities']))) <= common['joint_velocity_tolerance'] for r in rows)
    checks['reported_idle_pass'] = report['idle_validated'] and report['postassembly_physics_steps'] == 120
    final_path = args.input/'idle_states_final.npy'
    checks['terminal_states_available'] = final_path.exists()
    terminal = np.load(final_path,allow_pickle=False) if final_path.exists() else np.load(args.input/'idle_states_failed.npy',allow_pickle=False)
    checks['terminal_finite'] = bool(np.isfinite(terminal).all()) and terminal.shape == initial.shape
    checks['terminal_drift'] = bool(np.max(np.linalg.norm(terminal[:,:3]-initial[:,:3],axis=1)) <= common['maximum_position_drift_m'] and np.max(angles(terminal[:,3:7],initial[:,3:7])) <= common['maximum_orientation_drift_rad'])
    checks['final_speeds'] = bool(np.max(np.linalg.norm(terminal[:,7:10],axis=1)) <= common['maximum_final_linear_speed_m_s'] and np.max(np.linalg.norm(terminal[:,10:13],axis=1)) <= common['maximum_final_angular_speed_rad_s'])
    return {'postassembly_steps':report['postassembly_physics_steps'],'first_failure':report['failure'],'max_position_drift_m':max(r['max_position_drift_m'] for r in rows),'max_orientation_drift_rad':max(r['max_orientation_drift_rad'] for r in rows),'final_max_linear_speed_m_s':float(np.linalg.norm(terminal[:,7:10],axis=1).max()),'final_max_angular_speed_rad_s':float(np.linalg.norm(terminal[:,10:13],axis=1).max()),'iteration_evidence':'Actual actor32/4 readbacks; executed effective island iteration count unmeasured.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['A','B','C'],required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-audit',type=Path)
    parser.add_argument('--baseline-idle',type=Path)
    parser.add_argument('--predecessor-audit',type=Path)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Actual capture audit requires default Pueue')
    protocol=read(HERE/'protocol.json');checks={}
    if args.phase != 'A':
        if args.predecessor_audit is None:
            raise ValueError('B/C require the immediately preceding independent audit')
        previous=read(args.predecessor_audit)
        checks['preceding_phase_independently_passed'] = previous['phase'] == ('A' if args.phase == 'B' else 'B') and previous['proceed_gate_passed'] and previous['protocol_sha256'] == sha(HERE/'protocol.json')
    args.output.mkdir(parents=True,exist_ok=True)
    metrics=audit_a(args,protocol,checks) if args.phase=='A' else audit_idle(args,protocol,checks)
    result={'schema':'stage2-round3-phase-audit-v1','phase':args.phase,'protocol_sha256':sha(HERE/'protocol.json'),'input':str(args.input),'integrity_and_proceed_checks':checks,'proceed_gate_passed':all(checks.values()),'metrics':metrics,'limitations':protocol['unknowns'],'manipulation_validated':False,'physical_contact_validated':False}
    (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'proceed_gate_passed':result['proceed_gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')
    print(json.dumps({'phase':args.phase,'checks_passed':sum(checks.values()),'checks_total':len(checks),'proceed_gate_passed':result['proceed_gate_passed']}))


if __name__ == '__main__':
    main()

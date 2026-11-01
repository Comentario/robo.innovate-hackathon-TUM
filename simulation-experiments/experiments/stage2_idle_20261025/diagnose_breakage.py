"""Eight-step observation of unchanged physics; debug dumping is the only change."""
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from run_idle import assess_state

THRESHOLD_FIELDS = ('enabled', 'contact_regularization', 'clutch_axial_compliance',
    'clutch_radial_compliance', 'clutch_tangential_compliance', 'friction_coefficient',
    'preloaded_force', 'slack_fraction_warn', 'slack_fraction_b_floor', 'debug_dump',
    'breakage_cooldown_time')


def threshold_snapshot(value):
    return {name: getattr(value, name) for name in THRESHOLD_FIELDS}


def diagnostic(*, sim, scene, bricks, spec, output, robot):
    import hashlib
    import numpy as np
    from bricksim.core import (compute_connected_component, get_disassembled_connections,
        get_connection_utilization, get_physx_id_mappings, get_usd_id_mappings,
        get_assembly_thresholds, get_breakage_thresholds, set_breakage_thresholds)
    output = Path(output)
    protocol_path = Path(__file__).with_name('protocol.json')
    protocol = json.loads(protocol_path.read_text())
    debug_protocol = json.loads(Path(__file__).with_name('diagnostic_protocol.json').read_text())
    if (hashlib.sha256(protocol_path.read_bytes()).hexdigest() != debug_protocol['baseline_protocol_sha256']
        or debug_protocol['maximum_steps'] != 8 or debug_protocol['first_failure_stops'] is not True
        or debug_protocol['physics_changes'] is not False or debug_protocol['idle_validation_claim'] is not False
        or debug_protocol['only_changed_breakage_setting'] != 'BreakageThresholds.debug_dump False→True'):
        raise RuntimeError('Diagnostic protocol differs from the single unchanged-physics observation')
    for path, digest in protocol['frozen_input_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Unchanged-physics input pin differs: '+path)
    if not math.isclose(sim.get_physics_dt(), protocol['dt_s'], abs_tol=1e-12, rel_tol=0.):
        raise RuntimeError('Diagnostic dt differs from idle baseline')
    thresholds = get_breakage_thresholds()
    epsilon_raw = os.environ.get('OSQP_EPSILON')
    if epsilon_raw is not None and epsilon_raw not in ('1e-4','1e-6'):
        raise RuntimeError('Only declared default/precision epsilon variants are allowed')
    numerical = {'environment_raw':epsilon_raw, 'effective_requested':float(epsilon_raw) if epsilon_raw else 1e-4,
        'status':'Existing OsqpSolver constructor environment/default; value is not a serialized solver-setting getter',
        'coupling':['solver eps_abs and eps_rel','G >= -epsilon','stage2 Hx-Vv <= 1-epsilon'],
        'physical_thresholds_changed':False,'break_selection_changed':False}
    before = threshold_snapshot(thresholds)
    thresholds.debug_dump = True
    set_breakage_thresholds(thresholds)
    after = threshold_snapshot(get_breakage_thresholds())
    if before['debug_dump'] or after != {**before, 'debug_dump': True}:
        raise RuntimeError('Only debug_dump=False→True is allowed')
    if get_assembly_thresholds().enabled or not after['enabled']:
        raise RuntimeError('Assembly/breakage switches differ from baseline')
    source = '/World/envs/env_0/plate_source'
    names = ['plate_source']+[brick.name for brick in bricks]
    expected_parts = {f'/World/envs/env_0/{name}' for name in names}
    parts, connections = compute_connected_component(source)
    connections = sorted(connections)
    if len(bricks) != 300 or set(parts) != expected_parts or len(connections) != 930:
        raise RuntimeError('Diagnostic requires the unchanged full300 native component')
    mappings = {'physx': get_physx_id_mappings(), 'usd': get_usd_id_mappings()}
    (output/'native_id_mappings.json').write_text(json.dumps(mappings, indent=2)+'\n')
    (output/'debug_thresholds.json').write_text(json.dumps({'before': before, 'after': after}, indent=2)+'\n')

    def states():
        rows = []
        for name in names:
            view = scene[name].root_physx_view
            pose = view.get_transforms()[0].cpu().numpy()
            rows.append(np.r_[pose[:3], pose[6], pose[3:6], view.get_velocities()[0].cpu().numpy()])
        return np.asarray(rows, np.float64)

    initial = states()
    np.save(output/'diagnostic_states_initial.npy', initial)
    records = []
    observer = None
    if os.environ.get('ROBO_CONTACT_OBSERVER') == '1':
        from contact_observer import ContactObserver
        observer = ContactObserver(sim, scene, output)
    with (output/'diagnostic_trace.jsonl').open('w') as trace:
        for step in range(debug_protocol['maximum_steps']+1):
            if step:
                if observer is not None: observer.before_step()
                scene.write_data_to_sim(); sim.step(render=False); scene.update(sim.get_physics_dt())
            current = states()
            record = assess_state(initial, current, protocol)
            actual_parts, actual_connections = compute_connected_component(source)
            events = get_disassembled_connections(clear=True)
            utilization = {path: float(get_connection_utilization(path)) for path in connections}
            finite_utilization = {path: value for path, value in utilization.items() if math.isfinite(value)}
            q = robot.root_physx_view.get_dof_positions()[0].cpu().numpy()
            qd = robot.root_physx_view.get_dof_velocities()[0].cpu().numpy()
            robot_finite = bool(np.isfinite(q).all() and np.isfinite(qd).all()
                                and np.isfinite(robot.data.body_state_w.cpu().numpy()).all())
            record.update(step=step, physics_time_s=float(sim.current_time),
                source_parts=len(actual_parts), native_connections=len(actual_connections),
                broken_connections=[repr(event) for event in events], robot_finite=robot_finite,
                utilization={p: v if math.isfinite(v) else None for p, v in utilization.items()},
                top_utilization=sorted(finite_utilization.items(), key=lambda item: -item[1])[:10],
                watched_utilization={path: utilization[path] if math.isfinite(utilization[path]) else None
                    for path in connections if path.endswith(('Conn_836', 'Conn_837'))},
                joint_positions=q.tolist() if np.isfinite(q).all() else None,
                joint_velocities=qd.tolist() if np.isfinite(qd).all() else None)
            if events or set(actual_parts) != expected_parts or set(actual_connections) != set(connections):
                record['reasons'].append('native_component_changed_or_broken')
            if not robot_finite: record['reasons'].append('nonfinite_robot_state')
            if observer is not None: record['contact_observation'] = observer.sample(step)
            trace.write(json.dumps(record, allow_nan=False)+'\n'); trace.flush()
            records.append(record)
            print('DIAGNOSTIC_STEP', step, record['reasons'], flush=True)
            if record['reasons']: break
    np.save(output/'diagnostic_states_last.npy', current)
    dumps = sorted(str(p.relative_to(output)) for p in (output/'native_debug_tmp').rglob('breakage_debug_*.json'))
    report = {'diagnostic_completed': True, 'idle_validated': False, 'capture_validated': False,
        'maximum_steps': debug_protocol['maximum_steps'], 'steps_executed': records[-1]['step'],
        'thresholds_before': before, 'thresholds_after': after, 'numerical_epsilon':numerical, 'source_ids': names,
        'contact_observer_enabled': observer is not None,
        'first_failure': records[-1] if records[-1]['reasons'] else None,
        'native_debug_dumps': dumps, 'protocol': debug_protocol,
        'interpretation': 'Observation only; first breakage or reaching8steps does not establish idle stability or a cause. Cooldown delays selection; it is not inferred as the cause.'}
    (output/'diagnostic_report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    (output/'diagnostic_complete.json').write_text(json.dumps({'diagnostic_completed': True,
        'idle_validated': False, 'capture_validated': False, 'steps_executed': records[-1]['step']})+'\n')


if __name__ == '__main__':
    import argparse
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Native breakage diagnostics require default Pueue')
    # Set std::filesystem's temporary directory before importing core/native code.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output', type=Path, required=True)
    args, _ = parser.parse_known_args()
    temporary = args.output.resolve()/'native_debug_tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary)
    from experiments.final_workcell_20261024 import render_core
    render_core.main(postassembly_hook=diagnostic)

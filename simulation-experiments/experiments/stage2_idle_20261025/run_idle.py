"""One bounded native full-stack idle smoke test, through the existing initializer."""
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def assess_state(initial, current, protocol, final=False):
    import numpy as np
    if not np.isfinite(current).all():
        return {'finite': False, 'reasons': ['nonfinite_source_state']}
    q0, q = initial[:, 3:7], current[:, 3:7]
    norms = np.linalg.norm(q, axis=1)*np.linalg.norm(q0, axis=1)
    if np.any(norms < 1e-12):
        return {'finite': False, 'reasons': ['invalid_source_quaternion']}
    displacement = np.linalg.norm(current[:, :3]-initial[:, :3], axis=1)
    angles = 2*np.arccos(np.clip(np.abs(np.sum(q*q0, axis=1)/norms), 0., 1.))
    speed = np.linalg.norm(current[:, 7:10], axis=1)
    spin = np.linalg.norm(current[:, 10:13], axis=1)
    result = {'finite': True, 'max_position_drift_m': float(displacement.max()),
        'position_drift_part_index': int(displacement.argmax()),
        'max_orientation_drift_rad': float(angles.max()),
        'orientation_drift_part_index': int(angles.argmax()),
        'max_linear_speed_m_s': float(speed.max()), 'max_angular_speed_rad_s': float(spin.max()),
        'reasons': []}
    for field, bound, reason in (
        ('max_position_drift_m', 'maximum_position_drift_m', 'position_drift'),
        ('max_orientation_drift_rad', 'maximum_orientation_drift_rad', 'orientation_drift')):
        if result[field] > protocol[bound]:
            result['reasons'].append(reason)
    if final:
        if result['max_linear_speed_m_s'] > protocol['maximum_final_linear_speed_m_s']:
            result['reasons'].append('final_linear_speed')
        if result['max_angular_speed_rad_s'] > protocol['maximum_final_angular_speed_rad_s']:
            result['reasons'].append('final_angular_speed')
    return result


def run_idle(*, sim, scene, bricks, spec, output, robot, protocol_override=None):
    import hashlib
    import numpy as np
    from bricksim.core import (compute_connected_component, get_disassembled_connections,
        get_assembly_thresholds, get_breakage_thresholds)
    protocol = json.loads(Path(__file__).with_name('protocol.json').read_text()) if protocol_override is None else protocol_override
    output = Path(output)
    for relative, digest in protocol['frozen_input_hashes'].items():
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen idle input changed: '+relative)
    if not math.isclose(sim.get_physics_dt(), protocol['dt_s'], rel_tol=0., abs_tol=1e-12):
        raise RuntimeError('Physics dt differs from frozen idle protocol')
    if len(bricks) != protocol['expected_source_bricks']:
        raise RuntimeError('Idle smoke requires the unchanged full300 source')
    source = '/World/envs/env_0/plate_source'
    names = ['plate_source']+[b.name for b in bricks]
    expected_parts = {f'/World/envs/env_0/{name}' for name in names}
    initial_parts, initial_connections = compute_connected_component(source)
    if (set(initial_parts) != expected_parts or len(initial_parts) != protocol['expected_source_parts']
        or len(initial_connections) != protocol['expected_native_connections']):
        raise RuntimeError('Initial full native component differs from protocol')
    initial_connections = set(initial_connections)
    if get_assembly_thresholds().enabled or not get_breakage_thresholds().enabled:
        raise RuntimeError('Automatic assembly/breakage settings differ from protocol')

    def source_states():
        states = []
        for name in names:
            view = scene[name].root_physx_view
            raw = view.get_transforms()[0].cpu().numpy()
            velocities = view.get_velocities()[0].cpu().numpy()
            states.append(np.r_[raw[:3], raw[6], raw[3:6], velocities])
        return np.asarray(states, np.float64)

    initial = source_states()
    np.save(output/'idle_states_initial.npy', initial)
    (output/'idle_source_ids.json').write_text(json.dumps(names, indent=2)+'\n')
    start_time = float(sim.current_time)
    report = {'schema': 'stage2-idle-result-v1', 'idle_validated': False, 'capture_validated': False,
        'protocol': protocol, 'postassembly_physics_steps': 0, 'initial_physics_time_s': start_time,
        'stock_collision_baseline': True, 'updated_tip_contact_geometry_validated': False,
        'source_ids': names, 'native_initial_connections': sorted(map(str, initial_connections)), 'failure': None}
    with (output/'idle_trace.jsonl').open('w') as trace:
        for step in range(protocol['steps']+1):
            if step:
                # Existing nominal targets are held; no state reset or task command.
                scene.write_data_to_sim()
                sim.step(render=False)
                scene.update(sim.get_physics_dt())
            current = source_states()
            record = assess_state(initial, current, protocol, final=step == protocol['steps'])
            parts, connections = compute_connected_component(source)
            events = get_disassembled_connections(clear=True)
            joint_positions = robot.root_physx_view.get_dof_positions()[0].cpu().numpy()
            joint_velocities = robot.root_physx_view.get_dof_velocities()[0].cpu().numpy()
            robot_bodies = robot.data.body_state_w.cpu().numpy()
            record.update(step=step, physics_time_s=float(sim.current_time),
                source_parts=len(parts), native_connections=len(connections),
                broken_connections=[repr(event) for event in events],
                joint_positions=joint_positions.tolist(), joint_velocities=joint_velocities.tolist(),
                robot_finite=bool(np.isfinite(robot_bodies).all() and np.isfinite(joint_positions).all()
                                  and np.isfinite(joint_velocities).all()))
            if (events or set(parts) != expected_parts or len(parts) != protocol['expected_source_parts']
                or set(connections) != initial_connections or len(connections) != protocol['expected_native_connections']):
                record['reasons'].append('native_component_changed_or_broken')
            if not record['robot_finite']:
                record['reasons'].append('nonfinite_robot_state')
            # Preserve nonfinite robot values in NPY, not invalid JSON.
            if not np.isfinite(joint_positions).all(): record['joint_positions'] = None
            if not np.isfinite(joint_velocities).all(): record['joint_velocities'] = None
            trace.write(json.dumps(record, allow_nan=False)+'\n')
            trace.flush()
            report['postassembly_physics_steps'] = step
            if record['reasons']:
                report['failure'] = record
                np.save(output/'idle_states_failed.npy', current)
                np.save(output/'idle_robot_bodies_failed.npy', robot_bodies)
                (output/'idle_report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
                print('IDLE_FIRST_FAILURE', json.dumps(record), flush=True)
                raise RuntimeError('Idle smoke first failure: '+','.join(record['reasons']))
            if step % 10 == 0:
                print('IDLE_STEP', json.dumps(record), flush=True)
    np.save(output/'idle_states_final.npy', current)
    report.update(idle_validated=True, final_physics_time_s=float(sim.current_time), final=record,
                  elapsed_simulation_s=float(sim.current_time)-start_time)
    (output/'idle_report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    (output/'idle_complete.json').write_text(json.dumps({'idle_validated': True, 'capture_validated': False,
        'postassembly_physics_steps': protocol['steps'],
        'report_sha256': hashlib.sha256((output/'idle_report.json').read_bytes()).hexdigest()})+'\n')
    print('IDLE_COMPLETE', flush=True)


def self_test():
    import numpy as np
    protocol = json.loads(Path(__file__).with_name('protocol.json').read_text())
    original = np.zeros((2, 13)); original[:, 3] = 1.
    assert not assess_state(original, original, protocol, True)['reasons']
    moved = original.copy(); moved[1, 0] = .0021
    assert 'position_drift' in assess_state(original, moved, protocol)['reasons']
    moving = original.copy(); moving[0, 7] = .021
    assert not assess_state(original, moving, protocol)['reasons']
    assert 'final_linear_speed' in assess_state(original, moving, protocol, True)['reasons']
    broken = original.copy(); broken[0, 0] = np.nan
    assert not assess_state(original, broken, protocol)['finite']
    print('Idle drift/final-speed/finite tiny contracts: PASS')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    else:
        from experiments.final_workcell_20261024 import render_core
        render_core.main(postassembly_hook=run_idle)

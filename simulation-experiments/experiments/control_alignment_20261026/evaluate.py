"""Independent Jacob/Isaac control contract audit; never imports hardware helpers."""
import argparse
import bisect
import csv
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMIT = '13f37dad1980bcbc4491b7f27d8962602e49fea0'
DT = .001


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip(): yield json.loads(line)


def near(a, b, atol):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return bool(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
        and np.allclose(a, b, atol=atol, rtol=0))


def matrix(values):
    a = np.asarray(values, float)
    if a.shape != (16,) or not np.isfinite(a).all(): raise ValueError('Finite column-major transform required')
    return a.reshape(4, 4, order='F')


def smoothstep(value):
    x = min(1., max(0., float(value)))
    return 10*x**3-15*x**4+6*x**5


def pose_error(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.linalg.norm(a[:3, 3]-b[:3, 3])), float(Rotation.from_matrix(a[:3, :3].T@b[:3, :3]).magnitude())


def parse_plan(path):
    values = list(map(float, Path(path).read_text().split())); index = 0
    def take(n):
        nonlocal index
        result = np.asarray(values[index:index+n], float); index += n
        if result.shape != (n,) or not np.isfinite(result).all(): raise ValueError('Missing/nonfinite plan values')
        return result
    version, count = take(2)
    if version != 2 or count != int(count) or not 2 <= count <= 2001: raise ValueError('Frozen version2 joint protocol required')
    plan = {key: take(n) for key, n in (('start', 16), ('target', 16), ('tool', 16), ('q0', 7), ('control', 18), ('lower', 3), ('upper', 3))}
    names = ('seconds', 'gap', 'speed', 'omega', 'q_speed', 'position_tolerance', 'angle_tolerance', 'stable', 'timeout', 'cpu',
        'length', 'min_full', 'min_fixed', 'max_condition', 'min_q2', 'min_extension', 'long_rotation', 'rate_limiting')
    plan.update((name, float(value)) for name, value in zip(names, take(len(names))))
    plan.update(lower_q=take(7), upper_q=take(7), origins=[matrix(take(16)) for _ in range(7)], ee=matrix(take(16)))
    knots, coefficients = [], []
    for _ in range(int(count)-1):
        knots.append(float(take(1)[0])); coefficients.append(take(28).reshape(7, 4))
    end = float(take(1)[0]); plan.update(knots=knots, coefficients=coefficients, control=plan['control'].reshape(6, 3))
    if index != len(values) or knots[0] != 0 or end != 1 or not all(a < b for a, b in zip(knots, [*knots[1:], 1.])):
        raise ValueError('Unexpected/trailing plan content or knot order')
    if not (1 <= plan['seconds'] <= 600 and 0 < plan['gap'] <= .0200001 and plan['stable'] >= .5
            and plan['stable'] <= plan['timeout'] <= 5 and plan['rate_limiting'] == 1):
        raise ValueError('Changed timing or official rate-limiter contract')
    return plan


def spline_q(plan, u):
    u = min(1., max(0., float(u))); index = max(0, bisect.bisect_right(plan['knots'], u)-1)
    x = u-plan['knots'][index]; c = plan['coefficients'][index]
    return c@np.array([x**3, x**2, x, 1.])


def model_fk(plan, q):
    q = np.asarray(q, float)
    if q.shape != (7,) or not np.isfinite(q).all(): raise ValueError('Finite measured/desired seven-joint state required')
    result = np.eye(4); axes, positions = [], []
    for origin, angle in zip(plan['origins'], q):
        result = result@origin; axes.append(result[:3, 2].copy()); positions.append(result[:3, 3].copy())
        r = np.eye(4); r[:3, :3] = Rotation.from_rotvec([0., 0., angle]).as_matrix(); result = result@r
    result = result@plan['ee']; jacobian = np.zeros((6, 7))
    for i, (axis, position) in enumerate(zip(axes, positions)):
        jacobian[:3, i] = np.cross(axis, result[:3, 3]-position); jacobian[3:, i] = axis
    return result, jacobian


def expected_pose(plan, u):
    u = float(u); a, b = matrix(plan['start']), matrix(plan['target'])
    ar = Rotation.from_matrix(a[:3, :3]).as_matrix(); br = Rotation.from_matrix(b[:3, :3]).as_matrix()
    vector = Rotation.from_matrix(ar.T@br).as_rotvec(); angle = np.linalg.norm(vector)
    if plan['long_rotation'] and angle > 1e-6: vector *= 1-2*math.pi/angle
    out = np.eye(4); out[:3, :3] = ar@Rotation.from_rotvec(vector*smoothstep(u)).as_matrix()
    out[:3, 3] = sum(math.comb(5, i)*(1-u)**(5-i)*u**i*point for i, point in enumerate(plan['control']))
    return out


def metrics(plan, q):
    q = np.asarray(q, float); jacobian = model_fk(plan, q)[1]
    scaled = jacobian.copy(); scaled[:3] /= plan['length']
    full = np.linalg.svd(scaled, compute_uv=False); fixed = np.linalg.svd(scaled[:, [0, 1, 3, 4, 5, 6]], compute_uv=False)
    return {'full': float(full[-1]), 'fixed': float(fixed[-1]),
        'condition': float(max(full[0]/max(full[-1], 1e-12), fixed[0]/max(fixed[-1], 1e-12))),
        'q2': abs(float(q[1])), 'extension': abs(float(q[3])+.467002423653011)}


def guard(plan, q):
    q = np.asarray(q, float); m = metrics(plan, q)
    return bool(np.all(q >= plan['lower_q']) and np.all(q <= plan['upper_q']) and m['full'] >= plan['min_full']
        and m['fixed'] >= plan['min_fixed'] and m['condition'] <= plan['max_condition']
        and m['q2'] >= plan['min_q2'] and m['extension'] >= plan['min_extension'])


def rebased_command(plan, elapsed, reference):
    u = smoothstep(elapsed/plan['seconds']); raw = spline_q(plan, u)
    rebased = raw+(np.asarray(reference)-plan['q0'])*(1-smoothstep(u))
    if elapsed == 0: rebased = np.asarray(reference).copy()
    return u, raw, rebased


def target_channels(state, limited, float32_acceptance=True):
    """Accepted PhysX targets are a distinct readback, not measured q or raw request."""
    checks = {'public_qd_readback': near(state['q_d'], state['joint_target_readback'], 0.),
        'accepted_limited_command': near(state['joint_target_readback'], np.asarray(limited, np.float32).astype(float) if float32_acceptance else limited, 1e-12),
        }
    if float32_acceptance: checks['raw_io_request'] = near(state['raw_requested_q'], limited, 1e-12)
    return checks


def velocity_parameters(urdf):
    tree = ET.parse(urdf).getroot(); result = []
    for i in range(1, 8):
        candidates = [j for j in tree.findall('joint') if j.attrib['name'] == f'joint{i}']
        if len(candidates) != 1 or candidates[0].attrib['type'] != 'revolute': raise ValueError('Actual seven-joint URDF mapping required')
        limit, dynamic = candidates[0].find('limit'), candidates[0].find('position_based_velocity_limits')
        result.append([float(limit.attrib['velocity']), float(dynamic.attrib['velocity_offset']),
            float(dynamic.attrib['deceleration_limit']), float(limit.attrib['upper']), float(limit.attrib['lower'])])
    return np.asarray(result)


def sdk_limit(parameters, command, q, velocity, acceleration):
    """Independent direct equations from pinned official0.20.0; no native wrapper call."""
    p = np.asarray(parameters, float); c, q, v, a = map(lambda x: np.asarray(x, float), (command, q, velocity, acceleration))
    if p.shape != (7, 5) or any(x.shape != (7,) or not np.isfinite(x).all() for x in (c, q, v, a)) or not np.isfinite(p).all():
        raise ValueError('Finite documented limiter inputs required')
    upper_distance = np.sqrt(np.maximum(0., 2*p[:, 2]*(p[:, 3]-q)))
    lower_distance = np.sqrt(np.maximum(0., 2*p[:, 2]*(q-p[:, 4])))
    upper = np.minimum(p[:, 0], np.maximum(0., -p[:, 1]+upper_distance))-.001
    lower = np.maximum(-p[:, 0], np.minimum(0., p[:, 1]-lower_distance))+.001
    max_acceleration, max_jerk = 9.999, 4999.999
    requested_jerk = (((c-q)/DT-v)/DT-a)/DT
    requested_acceleration = a+np.clip(requested_jerk, -max_jerk, max_jerk)*DT
    safe_upper = np.minimum(max_jerk/max_acceleration*(upper-v), max_acceleration)
    safe_lower = np.maximum(max_jerk/max_acceleration*(lower-v), -max_acceleration)
    accepted_velocity = v+np.maximum(np.minimum(requested_acceleration, safe_upper), safe_lower)*DT
    return q+accepted_velocity*DT


def clock_serialization_budget(steps):
    if type(steps) is not int or steps < 0: raise ValueError('Nonnegative observed step count required')
    return steps*abs(float(np.float32(DT))-DT)+1e-9


def source_clock_coverage(times, initial, final, steps):
    times = np.asarray(times, float); budget = clock_serialization_budget(steps)
    if steps <= 0 or times.shape != (steps,) or not np.isfinite(times).all(): return False
    return bool(near(np.diff(np.r_[initial, times]), np.full(steps, DT), 1e-8)
        and near(times, initial+np.arange(1, steps+1)*DT, budget)
        and abs(final-initial-steps*DT) <= budget)


def startup_getter_proof(proof, initial, initial_time):
    """Check raw startup equivalence and path permutation without importing the reader."""
    names = initial['names']; expected = ['/World/envs/env_0/'+name for name in names]
    actual = proof['actual_view_prim_paths']; indices = proof['row_indices_in_name_order']
    mapping = (len(names) == len(set(names)) == 300 and names == sorted(names)
        and proof['names'] == names and proof['expected_root_paths'] == expected
        and proof['count'] == len(actual) == len(set(actual)) == 300 and set(actual) == set(expected)
        and len(indices) == 300 and all(type(i) is int and 0 <= i < 300 for i in indices)
        and len(set(indices)) == 300 and [actual[i] for i in indices] == expected)
    version = proof.get('proof_version', 1)
    if type(version) is not int or version not in (1, 2): return False
    reference_ok = proof.get('old_reader') == 'scene[name].data.root_link_pose_w[0]'
    diagnostic_ok = True
    new = np.asarray(proof['new_poses_world_wxyz'], float)
    if version == 1:
        old = np.asarray(proof['old_poses_world_wxyz'], float)
    else:
        if not mapping: return False
        old = np.asarray(proof['direct_poses_world_wxyz'], float)
        direct_raw = np.asarray(proof['direct_raw_poses_world_xyzw'], float)
        batch_raw = np.asarray(proof['batch_raw_poses_world_xyzw'], float)
        cached = np.asarray(proof['cached_poses_world_wxyz'], float)
        arrays = (old, new, direct_raw, batch_raw, cached)
        if not all(a.shape == (300, 7) and np.isfinite(a).all()
                and np.all(np.linalg.norm(a[:, 3:], axis=1) > 0) for a in arrays): return False
        reference_ok = (proof['reference_reader'] == 'fresh_per_asset_PhysX_get_transforms'
            and 'old_reader' not in proof and 'old_poses_world_wxyz' not in proof
            and near(direct_raw[:, [0, 1, 2, 6, 3, 4, 5]], old, 0.)
            and near(batch_raw[indices][:, [0, 1, 2, 6, 3, 4, 5]], new, 0.))
        for right, key in [(old, 'cached_direct_comparison'), (new, 'cached_batch_comparison')]:
            cp = float(np.max(np.linalg.norm(cached[:, :3]-right[:, :3], axis=1)))
            ca = float(np.max((Rotation.from_quat(cached[:, [4, 5, 6, 3]]).inv()
                *Rotation.from_quat(right[:, [4, 5, 6, 3]])).magnitude()))
            recorded = proof[key]
            diagnostic_ok = diagnostic_ok and type(recorded['passed']) is bool \
                and recorded['passed'] == (cp <= 1e-9 and ca <= 1e-7) \
                and near(recorded['maximum_position_error_m'], cp, 1e-15) \
                and near(recorded['maximum_angle_error_rad'], ca, 1e-12)
    if old.shape != (300, 7) or new.shape != (300, 7) or not np.isfinite(old).all() or not np.isfinite(new).all(): return False
    norms_old = np.linalg.norm(old[:, 3:], axis=1); norms_new = np.linalg.norm(new[:, 3:], axis=1)
    if np.any(norms_old == 0) or np.any(norms_new == 0): return False
    position = float(np.max(np.linalg.norm(old[:, :3]-new[:, :3], axis=1)))
    rotations_old = Rotation.from_quat(old[:, [4, 5, 6, 3]])
    rotations_new = Rotation.from_quat(new[:, [4, 5, 6, 3]])
    angle = float(np.max((rotations_old.inv()*rotations_new).magnitude()))
    return bool(mapping and proof['subspace_roots'] == '/' and proof['frame'] == 'world'
        and proof['getter_layout'] == 'xyz_xyzw' and proof['returned_layout'] == 'xyz_wxyz'
        and proof['snapshot_copy'] is True and proof['no_step_called_by_reader'] is True
        and reference_ok and diagnostic_ok
        and proof['clock_before_s'] == proof['clock_after_s'] == initial_time
        and proof['position_tolerance_m'] == 1e-9 and proof['angle_tolerance_rad'] == 1e-7
        and position <= 1e-9 and angle <= 1e-7 and proof['equivalence_passed'] is True
        and 0 <= proof['maximum_position_error_m'] <= 1e-9
        and 0 <= proof['maximum_angle_error_rad'] <= 1e-7
        and (version == 1 or (near(proof['maximum_position_error_m'], position, 1e-15)
            and near(proof['maximum_angle_error_rad'], angle, 1e-12)))
        and near(new, initial['poses_world_wxyz'], 0.))


def callback_audit(path, plan, parameters, phase):
    failures = Counter(); n = 0; reference = None; warmed = False; startup = stable = elapsed = 0.; previous = None
    maximum_position = maximum_angle = maximum_tracking = 0.; first_motion = None; final = None
    for row in rows(path):
        n += 1; before, after = row['state_before'], row['state_after']; period = 0. if n == 1 else DT
        local = {'callback_index': row['step'] == n, 'period': abs(row['period_s']-period) <= 1e-12,
            'software_guard_passed': row['guard_status'] == 'PASS',
            'hardware_network_unavailable': row['hardware_network_feedback'] == 'UNAVAILABLE',
            'one_physics_tick': abs(after['time']-before['time']-DT) <= 1e-8,
            'before_readback': near(before['q_d'], before['joint_target_readback'], 0.)}
        if previous is not None:
            local['state_continuity'] = near(before['q'], previous['q'], 0.) and near(before['q_d'], previous['q_d'], 0.) \
                and abs(before['time']-previous['time']) <= 1e-12
        if reference is None:
            reference = np.asarray(before['q_d'], float)
            local['frozen_start_q'] = near(before['q'], plan['q0'], .001)
            local['initial_desired_rebase'] = near(reference, plan['q0'], .001)
            local['frozen_tool'] = near(before['F_T_EE'], plan['tool'], 1e-6)
            dp, da = pose_error(matrix(before['O_T_EE']), matrix(plan['start']))
            local['frozen_start_pose'] = dp <= .001 and da <= .005
        if not warmed:
            startup += period; stable = stable+period if period <= plan['gap'] else 0.
            if stable >= plan['stable']: warmed = True; elapsed = 0.
            local['startup_timeout'] = startup <= plan['timeout']
        else: elapsed += period
        u, raw, rebased = rebased_command(plan, elapsed, reference)
        limiter_reference = rebased if n == 1 else np.asarray(before['q_d'], float)
        limited = sdk_limit(parameters, rebased, limiter_reference, before['dq_d'], before['ddq_d'])
        local.update({'source_time_law': abs(row['startup_s']-startup) <= 1e-10 and abs(row['elapsed_s']-elapsed) <= 1e-10
                and row['warmed'] is warmed and abs(row['u']-u) <= 1e-12,
            'raw_spline': near(row['raw_spline_q'], raw, 2e-12),
            'desired_rebase': near(row['rebased_command_q'], rebased, 2e-12),
            'official_limiter': near(row['limited_command_q'], limited, 2e-12),
            'expected_cartesian_route': near(row['expected_O_T_EE'], expected_pose(plan, u).reshape(-1, order='F'), 1e-7)})
        local.update(target_channels(after, limited, phase == 'B'))
        accepted_velocity = (np.asarray(after['q_d'])-before['q_d'])/DT
        local['desired_derivatives_from_readback'] = near(after['dq_d'], accepted_velocity, 1e-9) \
            and near(after['ddq_d'], (accepted_velocity-before['dq_d'])/DT, 1e-6)
        for suffix, state in (('before', before), ('after', after)):
            q, qd, dq = map(lambda key: np.asarray(state[key], float), ('q', 'q_d', 'dq'))
            actual = matrix(state['O_T_EE']); predicted = model_fk(plan, q)[0]
            dp, da = pose_error(predicted, actual); maximum_position = max(maximum_position, dp); maximum_angle = max(maximum_angle, da)
            local[suffix+'_configured_EE_FK'] = dp <= .0001 and da <= .001
            local[suffix+'_measured_and_desired_guard'] = guard(plan, q) and guard(plan, qd)
            local[suffix+'_joint_tracking_velocity'] = bool(np.isfinite(dq).all() and np.max(abs(dq)) <= plan['q_speed'] and np.max(abs(q-qd)) <= .02)
            if phase == 'B': local[suffix+'_not_MODEL_grip'] = state['model_grip_frame_used'] is False
        measured = matrix(before['O_T_EE']); expected = expected_pose(plan, u); dp, da = pose_error(measured, expected)
        maximum_tracking = max(maximum_tracking, dp)
        local['cartesian_corridor'] = dp <= .005 and da <= .03491
        local['cleared_base_workspace'] = bool(np.all(measured[:3, 3] >= plan['lower']-.003) and np.all(measured[:3, 3] <= plan['upper']+.003))
        velocity = np.asarray(before['O_dP_EE_c'], float)
        local['commanded_cartesian_speed'] = bool(np.linalg.norm(velocity[:3]) <= plan['speed']*1.5+.002 and np.linalg.norm(velocity[3:]) <= plan['omega']*1.5+.002)
        if elapsed > 0 and first_motion is None: first_motion = n
        for key, value in local.items():
            if not value: failures[key] += 1
        previous = final = after
    if final is None: raise ValueError('Missing callback coverage')
    endpoint_position, endpoint_angle = pose_error(matrix(final['O_T_EE']), matrix(plan['target']))
    checks = {'all_callback_checks': not failures, 'nonempty_callbacks': n > 0, 'startup_completed': warmed and startup >= .5,
        'full_duration_plus_settle': plan['seconds']+.8-1e-9 <= elapsed <= plan['seconds']+.8+DT+1e-9,
        'measured_endpoint': endpoint_position <= plan['position_tolerance'] and endpoint_angle <= plan['angle_tolerance'],
        'end_stationary': bool(max(abs(np.asarray(final['dq']))) <= .01)}
    return checks, {'callbacks': n, 'first_motion_callback': first_motion, 'elapsed_s': elapsed, 'startup_s': startup,
        'maximum_FK_position_error_m': maximum_position, 'maximum_FK_angle_error_rad': maximum_angle,
        'maximum_measured_arc_tracking_m': maximum_tracking, 'endpoint_position_error_m': endpoint_position,
        'endpoint_angle_error_rad': endpoint_angle, 'callback_failure_counts': dict(failures), 'final_state': final}


def evaluate(phase, folder, predecessor):
    folder = Path(folder).resolve(); meta = read(folder/'metadata.json'); marker = read(folder/'run_complete.json')
    protocol = read(HERE/'protocol.json')
    artifact = lambda name: (folder/meta[name]).resolve()
    manifest_path = artifact('source_manifest_file'); vendor = manifest_path.parent; source = read(manifest_path)
    checks = {'phase': meta['phase'] == marker['phase'] == phase,
        'pinned_commit': meta['upstream_commit'] == source['commit'] == COMMIT,
        'source_only_vendor': source['executable_hardware_helpers_included'] is False
            and not any((vendor/'teaching'/n).exists() for n in ('read_pose', 'joint_move', 'gripper_width', 'arc_move', 'move_xyz')),
        'completed_capture': marker['completed'] is True and not (folder/'failure.json').exists(),
        'no_hardware_or_grasp': marker['hardware_commands'] == meta['hardware_commands'] == 0 and meta['grasp_or_placement_claim'] is False,
        'shared_process_completion': meta['move_returncode'] == meta['width_returncode'] == 0,
        'configured_EE_model_fidelity': meta['model_fidelity']['position_error_m'] <= .0001 and meta['model_fidelity']['orientation_error_rad'] <= .001,
        'one_ms_backend': meta['physics_dt_s'] == DT}
    checks['frozen_protocol'] = (protocol['upstream_commit'] == COMMIT
        and protocol['phase_A_maximum_seconds'] == 90 and protocol['phase_B_maximum_seconds'] == 180
        and protocol['aggregate_maximum_seconds'] == 270 and protocol['hardware_execution'] is False
        and protocol['source_limits'] == {'maximum_position_drift_m': .0005, 'maximum_angle_drift_rad': .005,
            'native_graph_changes': 0, 'external_robot_contact_points': 0})
    for relative, digest in source['sha256'].items(): checks['vendor_'+relative] = sha(vendor/relative) == digest
    sdk = ROOT/'vendor/libfranka_0_20'; sdk_source = read(sdk/'SOURCE.json')
    checks['SDK_scope'] = sdk_source['tag'] == '0.20.0' and sdk_source['exact_real_patch_version'] == 'UNKNOWN'
    for relative, digest in sdk_source['sha256'].items(): checks['SDK_'+relative] = sha(sdk/relative) == digest
    build_path = artifact('native_build_file'); build = read(build_path)
    checks['offline_oracle_scope'] = build['robot_or_network_code_linked'] is False and build['libfranka_tag'] == '0.20.0'
    checks['cpp_upstream_pin'] = build['source_joint_move_sha256'] == source['sha256']['teaching/joint_move.cpp']
    for name, digest in build['sha256'].items(): checks['native_'+name] = sha(build_path.parent/name) == digest
    original = (vendor/'teaching/joint_move.cpp').read_text().split('void check(const franka::RobotState&', 1)[0]
    checks['unchanged_CPP_oracle_core'] = (build_path.parent/'plan_core.hpp').read_text() == original.replace('#include <franka/robot.h>\n', '')
    checks['limiter_library_bound'] = artifact('limiter_library') == (build_path.parent/'libjoint_limiter.so').resolve()
    plan = parse_plan(artifact('joint_input_file')); shared = read(artifact('plan_file'))
    checks['frozen_plan_coefficients'] = (near(shared['initial_q'], plan['q0'], 1e-12)
        and near(shared['knots'], [*plan['knots'], 1.], 1e-12) and near(shared['coefficients'], plan['coefficients'], 1e-12)
        and near(shared['fixed_model']['joint7_to_ee'], plan['ee'].reshape(-1, order='F'), 1e-12)
        and near(shared['fixed_model']['joint_origins'], [o.reshape(-1, order='F') for o in plan['origins']], 1e-12))
    checks['configured_tool'] = near(meta['tool_F_T_EE'], plan['tool'], 1e-12)
    a, b = matrix(plan['start']), matrix(plan['target'])
    checks['one_mm_base_Z_jog_only'] = near(b[:3, 3]-a[:3, 3], [0., 0., .001], 1e-9) and pose_error(a, b)[1] <= 1e-6
    checks['direct_no_standoff'] = near(plan['control'], [a[:3, 3]]*3+[b[:3, 3]]*3, 1e-10)
    config = read(vendor/'teaching/motion_config.json')
    checks['upstream_joint_rate_limit_policy'] = config['joint_rate_limiting_enabled'] is True and plan['rate_limiting'] == 1
    outcome = read(artifact('outcome_file'))
    checks['not_preview_or_grasp_success'] = (outcome['completed'] is True and outcome['preview_only'] is False
        and outcome['controller_pass_verified'] is True and outcome['returncode'] == 0 and outcome['saved_catalog_unchanged'] is True
        and outcome['grasp_offset_executed'] is False and outcome['grasp_reference_reached'] is False)
    width_logs = list((vendor/'teaching/gripper_moves').glob('*/outcome.json'))
    checks['one_NOOP_release_artifact'] = len(width_logs) == 1
    if len(width_logs) == 1:
        width_result = read(width_logs[0]); request = read(width_logs[0].parent/'request.json')
        log = (width_logs[0].parent/'execution.log').read_text().splitlines()
        final_width = [json.loads(line.split(' ', 1)[1]) for line in log if line.startswith('FINAL_GRIPPER ')]
        checks['NOOP_release20_verified'] = (request['action'] == 'release' and request['target_width_m'] == .02
            and width_result['completed'] is True and width_result['returncode'] == 0
            and width_result['pick_verified'] is False and width_result['contact_width_accepted'] is False
            and len(final_width) == 1 and abs(final_width[0]['width']-.02) <= .001
            and final_width[0]['is_grasped'] is None and 'PASS gripper width' in log
            and any(line.startswith('WIDTH_VERIFIED ') and line.endswith('moved 0') for line in log))
    parameters = velocity_parameters(vendor/'teaching/robot_model.urdf')
    with artifact('cpp_check_csv').open() as stream: oracle = list(csv.DictReader(stream))
    oracle_failures = Counter(); maximum_cpp_position = 0.
    checks['cpp_oracle_1001_samples'] = len(oracle) == 1001
    for i, row in enumerate(oracle):
        u = float(row['u']); q = spline_q(plan, u); pose = model_fk(plan, q)[0]; metric = metrics(plan, q)
        error = float(np.linalg.norm(pose[:3, 3]-[float(row[k]) for k in ('x', 'y', 'z')])); maximum_cpp_position = max(maximum_cpp_position, error)
        if abs(u-i/1000.) > 1e-12: oracle_failures['u_grid'] += 1
        if error > 1e-9: oracle_failures['FK_position'] += 1
        for column, key in (('full_sigma', 'full'), ('fixed_sigma', 'fixed'), ('condition', 'condition'), ('q2', 'q2'), ('extension', 'extension')):
            if abs(float(row[column])-metric[key]) > 1e-7: oracle_failures['metric_'+key] += 1
        if not guard(plan, q): oracle_failures['joint_guard'] += 1
        dp, da = pose_error(pose, expected_pose(plan, u))
        if dp > .001 or da > .005: oracle_failures['Cartesian_curve'] += 1
    checks['independent_CPP_model_curve_parity'] = not oracle_failures
    callback_checks, metrics_out = callback_audit(artifact('trace_file'), plan, parameters, phase); checks.update(callback_checks)
    limiter_maximum = None; source_metrics = None
    if phase == 'A':
        checks['ideal_fixture_only'] = meta['io_provenance']['plant'] == 'IDEAL OFFLINE REPLAY ONLY' and marker['physics_steps'] == 0
        checks['real_joint_names'] = meta['joint_names'] == [f'joint{i}' for i in range(1, 8)]
        cases = read(folder/meta['limiter_cases_file']); limiter_maximum = 0.
        checks['twelve_limiter_vectors'] = len(cases) == 12
        for row in cases:
            predicted = sdk_limit(row['parameters'], row['command'], row['q_d'], row['dq_d'], row['ddq_d'])
            limiter_maximum = max(limiter_maximum, float(np.max(abs(predicted-row['limited']))))
            checks['limiter_parameters'] = checks.get('limiter_parameters', True) and near(row['parameters'], parameters, 0.)
        checks['independent_SDK_vectors'] = limiter_maximum <= 2e-12
        guards = read(folder/meta['guard_cases_file'])
        checks['frozen_three_guard_cases'] = (len(guards) == 3 and {r['case'] for r in guards} == {'stale_start', 'changed_tool', 'unknown_process'}
            and all(r['blocked'] is True and r['advance_count'] == 0 for r in guards))
    else:
        if predecessor is None: raise ValueError('Phase A proof required before the one Isaac smoke')
        proof = read(predecessor)
        checks['accepted_phase_A'] = proof['phase'] == 'A' and proof['control_alignment_passed'] is True \
            and proof['upstream_commit'] == COMMIT and proof['source_manifest_sha256'] == sha(manifest_path) \
            and proof['native_build_sha256'] == sha(build_path)
        checks['Isaac_joint_names'] = meta['joint_names'] == [f'fr3_joint{i}' for i in range(1, 8)]
        checks['actual_qd_provenance'] = meta['io_provenance']['q_d'] == 'public get_dof_position_targets, float32 accepted target readback'
        checks['no_gripper_move_or_pose_writes'] = meta['gripper_move_calls'] == meta['post_initialization_pose_writes'] == 0
        checks['physics_scope'] = meta['physics']['dt_s'] == DT and meta['physics']['solver'] == 'PGS'
        checks['callback_errors_absent'] = meta['contact_callback_errors'] == []
        initial = read(folder/meta['source_initial_file']); initial_poses = np.asarray(initial['poses_world_wxyz'], float)
        checks['source_initial_inventory'] = (len(initial['names']) == len(set(initial['names'])) == 300 and initial_poses.shape == (300, 7)
            and len(initial['native_parts']) == len(set(initial['native_parts'])) == meta['native_initial_parts'] == 301
            and len(initial['native_connections']) == len(set(initial['native_connections'])) == meta['native_initial_connections'] == 930)
        checks['batched_source_getter_startup_equivalence'] = startup_getter_proof(meta['source_pose_getter_proof'], initial, meta['initial_time_s'])
        with np.load(folder/meta['source_trace_file'], allow_pickle=False) as raw: data = {k: raw[k].copy() for k in raw.files}
        n = meta['simulation_steps_observed']; times = data['time_s']
        expected_shapes = {'positions_world_m': (n, 300, 3), 'quaternions_wxyz': (n, 300, 4), 'native_parts_count': (n,),
            'native_connections_count': (n,), 'native_graph_unchanged': (n,), 'robot_external_contact_points': (n,), 'time_s': (n,)}
        checks['all_observed_source_steps'] = (n > 0 and set(data) == set(expected_shapes)
            and all(data[k].shape == shape and np.isfinite(data[k]).all() for k, shape in expected_shapes.items()))
        checks['source_clock_coverage'] = source_clock_coverage(times, meta['initial_time_s'], meta['final_time_s'], n)
        drift = float(np.max(np.linalg.norm(data['positions_world_m']-initial_poses[None, :, :3], axis=2)))
        q = data['quaternions_wxyz']; q0 = initial_poses[:, 3:]
        norms = np.linalg.norm(q, axis=2); norms0 = np.linalg.norm(q0, axis=1)
        angles = 2*np.arccos(np.clip(abs(np.sum(q*q0[None], axis=2)/(norms*norms0[None])), 0, 1))
        source_angle = float(angles.max())
        checks['stationary_full_source'] = drift <= .0005 and source_angle <= .005
        checks['unchanged_native_graph_all_steps'] = bool(np.all(data['native_parts_count'] == 301) and np.all(data['native_connections_count'] == 930) and np.all(data['native_graph_unchanged'] == 1))
        checks['no_external_robot_contact_all_steps'] = bool(np.all(data['robot_external_contact_points'] == 0))
        source_metrics = {'source_samples': n, 'maximum_translation_m': drift, 'maximum_rotation_rad': source_angle,
            'clock_serialization_budget_s': clock_serialization_budget(n), 'per_step_clock_tolerance_s': 1e-8}
    passed = bool(all(checks.values()))
    return {'phase': phase, 'control_alignment_passed': passed, 'passed': passed, 'checks': checks,
        'failed_checks': [k for k, v in checks.items() if not v], 'upstream_commit': COMMIT,
        'source_manifest_sha256': sha(manifest_path), 'metadata_sha256': sha(folder/'metadata.json'),
        'native_build_sha256': sha(build_path),
        'protocol_sha256': sha(HERE/'protocol.json'),
        'joint_input_sha256': sha(artifact('joint_input_file')), 'metrics': metrics_out,
        'CPP_oracle_failure_counts': dict(oracle_failures), 'maximum_CPP_FK_position_difference_m': maximum_cpp_position,
        'maximum_SDK_case_difference_rad': limiter_maximum, 'source_metrics': source_metrics,
        'scope': 'Shared source/planned command and healthy 1kHz backend alignment only; ideal phase A is not physics.',
        'hardware_dynamics_verified': False, 'hardware_network_or_CPU_timing_verified': False,
        'exact_hardware_libfranka_patch': 'UNKNOWN; official0.20.0 math pinned',
        'physical_pad_gap_calibrated': False, 'grasp_or_native_extraction_passed': False, 'transfer_authorized': False}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--phase', choices=['A', 'B'], required=True)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--predecessor-A', type=Path); args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    start = time.monotonic(); result = evaluate(args.phase, args.input, args.predecessor_A); result['wall_seconds'] = time.monotonic()-start
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    raise SystemExit(0 if result['control_alignment_passed'] else 1)


if __name__ == '__main__': main()

"""Independent no-step pose-reader diagnostic. No simulator or reader imports."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

POSITION_M = 1e-9
ANGLE_RAD = 1e-7
INITIALIZER = 'runs/20261026T010941.404058Z-control-alignment-b'


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copied_sources_match(snapshot, hashes):
    snapshot = Path(snapshot).resolve(); matches = bool(hashes)
    for relative, expected in hashes.items():
        source = (snapshot/relative).resolve()
        valid = source.is_relative_to(snapshot) and source.is_file() and digest(source) == expected
        matches = matches and valid
    return bool(matches)


def close(a, b, tolerance=0.):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return bool(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
        and np.allclose(a, b, atol=tolerance, rtol=0.))


def pair_errors(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    position = float(np.max(np.linalg.norm(a[:, :3]-b[:, :3], axis=1)))
    ra = Rotation.from_quat(a[:, [4, 5, 6, 3]])
    rb = Rotation.from_quat(b[:, [4, 5, 6, 3]])
    angle = float(np.max((ra.inv()*rb).magnitude()))
    return {'maximum_position_error_m': position, 'maximum_angle_error_rad': angle,
        'passed': position <= POSITION_M and angle <= ANGLE_RAD}


def evaluate(data):
    proof = data['pose_readers']; before = data['scene_before']; after = data['scene_after']
    names = proof['names']; expected = ['/World/envs/env_0/'+name for name in names]
    actual = proof['actual_view_prim_paths']; indices = proof['row_indices_in_name_order']
    checks = {
        'schema': proof['schema'] == 'pose-reader-startup-v1',
        'full_source_names': len(names) == len(set(names)) == 300 and names == sorted(names)
            and all(isinstance(name, str) and name.startswith('brick_') for name in names),
        'exact_actor_paths': proof['count'] == len(actual) == len(set(actual)) == 300
            and proof['expected_root_paths'] == expected and set(actual) == set(expected),
        'world_frame': proof['frame'] == 'world' and proof['subspace_roots'] == '/',
        'frozen_limits': proof['limits'] == {'position_m': POSITION_M, 'angle_rad': ANGLE_RAD},
        'no_step_or_control': proof['no_step_called'] is True and data['control_commands'] == 0
            and proof['snapshot_copy'] is True and data['initialized_bricks'] == 300,
        'unchanged_clock': type(before['physics_time_s']) in (int, float)
            and np.isfinite(before['physics_time_s']) and before['physics_time_s'] == after['physics_time_s'],
        'unchanged_step_index': type(before['physics_step_index']) is int
            and type(after['physics_step_index']) is int
            and before['physics_step_index'] == after['physics_step_index'],
        'unchanged_arm': close(before['arm_joint_positions'], after['arm_joint_positions'])
            and np.asarray(before['arm_joint_positions']).shape == (7,),
        'initializer_snapshot': data['initializer_source_snapshot'] == INITIALIZER,
    }
    valid_indices = (len(indices) == 300 and all(type(i) is int and 0 <= i < 300 for i in indices)
        and len(set(indices)) == 300)
    checks['exact_row_permutation'] = bool(valid_indices and len(actual) == 300
        and [actual[i] for i in indices] == expected)
    for field, count in [('native_parts_paths', 301), ('native_connections_paths', 930)]:
        original = before[field]; terminal = after[field]
        checks['unchanged_'+field] = (len(original) == len(set(original)) == count
            and len(terminal) == len(set(terminal)) == count and set(original) == set(terminal)
            and all(isinstance(path, str) and path.startswith('/') for path in original))
    poses = {}; arrays_valid = True
    for name, layout in [('cached', 'xyz_wxyz'), ('direct', 'xyz_xyzw'), ('batch', 'xyz_xyzw')]:
        channel = proof['channels'][name]
        raw = np.asarray(channel['raw_poses'], float); pose = np.asarray(channel['poses_world_wxyz'], float)
        finite = bool(raw.shape == pose.shape == (300, 7) and np.isfinite(raw).all() and np.isfinite(pose).all()
            and np.all(np.linalg.norm(raw[:, 3:], axis=1) > 0) and np.all(np.linalg.norm(pose[:, 3:], axis=1) > 0))
        checks[name+'_finite_nonzero_poses'] = finite
        checks[name+'_layout_dtype_clock'] = (channel['raw_layout'] == layout and channel['raw_dtype'] == 'float32'
            and channel['clock_before_s'] == channel['clock_after_s'] == before['physics_time_s'])
        converted = raw if name == 'cached' else raw[:, [0, 1, 2, 6, 3, 4, 5]] if finite else None
        if name == 'batch' and finite and valid_indices: converted = converted[indices]
        checks[name+'_conversion_and_order'] = bool(finite and (name != 'batch' or valid_indices)
            and close(converted, pose))
        arrays_valid = arrays_valid and finite
        poses[name] = pose
    comparisons = {}
    if arrays_valid:
        for name, a, b in [('cached_direct', 'cached', 'direct'), ('cached_batch', 'cached', 'batch'), ('direct_batch', 'direct', 'batch')]:
            measured = pair_errors(poses[a], poses[b]); recorded = proof['comparisons'][name]
            checks[name+'_summary_verified'] = (type(recorded['passed']) is bool and recorded['passed'] == measured['passed']
                and close(recorded['maximum_position_error_m'], measured['maximum_position_error_m'], 1e-15)
                and close(recorded['maximum_angle_error_rad'], measured['maximum_angle_error_rad'], 1e-12))
            comparisons[name] = measured
    checks = {key: bool(value) for key, value in checks.items()}
    complete = bool(all(checks.values()))
    status = 'UNKNOWN'
    if complete:
        passed = {key: value['passed'] for key, value in comparisons.items()}
        if all(passed.values()): status = 'ALL_READERS_EQUIVALENT'
        elif not passed['direct_batch']: status = 'DIRECT_BATCH_MISMATCH'
        elif not passed['cached_direct'] and not passed['cached_batch']: status = 'CACHE_ONLY_DISCREPANCY'
    return {'schema': 'pose-reader-independent-audit-v1', 'diagnostic_complete': complete,
        'checks': checks, 'failed_checks': [key for key, value in checks.items() if not value],
        'reader_status': status, 'comparisons': comparisons,
        'all_readers_equivalent': bool(complete and all(value['passed'] for value in comparisons.values())),
        'fresh_direct_batch_equivalent': bool(complete and comparisons['direct_batch']['passed']),
        'initializer_source_snapshot': data['initializer_source_snapshot'],
        'absolute_pose_accuracy_verified': False, 'physical_control_alignment_verified': False,
        'grasp_or_hardware_parity_verified': False, 'corrected_check_automatically_authorized': False}


def confirmation_checks(data, confirmation, startup_verifier):
    proof = confirmation['proof']; initial = confirmation['initial']; scene = data['scene_after']
    channels = data['pose_readers']['channels']
    return {
        'confirmation_no_step_control': confirmation['control_commands'] == 0
            and confirmation['physics_time_before_s'] == confirmation['physics_time_after_s'] == scene['physics_time_s']
            and type(confirmation['physics_step_before']) is int and type(confirmation['physics_step_after']) is int
            and confirmation['physics_step_before'] == confirmation['physics_step_after'] == scene['physics_step_index'],
        'confirmation_actual_v2_class_proof': proof.get('proof_version') == 2
            and startup_verifier(proof, initial, confirmation['physics_time_before_s']),
        'confirmation_initial_matches_capture_batch': initial['names'] == data['pose_readers']['names']
            and close(initial['poses_world_wxyz'], channels['batch']['poses_world_wxyz']),
        'confirmation_class_bound_to_all_three_channels': proof['names'] == data['pose_readers']['names']
            and close(proof['direct_raw_poses_world_xyzw'], channels['direct']['raw_poses'])
            and close(proof['direct_poses_world_wxyz'], channels['direct']['poses_world_wxyz'])
            and close(proof['cached_poses_world_wxyz'], channels['cached']['poses_world_wxyz'])
            and close(proof['new_poses_world_wxyz'], channels['batch']['poses_world_wxyz']),
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required for saved pose evaluation')
    data = json.loads(args.input.read_text())
    result = evaluate(data)
    snapshot = args.input.resolve().parent.parent; manifest_path = snapshot/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    protocol = json.loads(Path(__file__).with_name('protocol.json').read_text())
    checks = result['checks']
    checks['capture_manifest_binding'] = digest(manifest_path) == data['manifest_sha256']
    checks['manifest_initializer_binding'] = (manifest['initializer_source_snapshot'] == INITIALIZER
        and protocol['initializer_source_snapshot'] == INITIALIZER)
    checks['copied_source_hashes'] = copied_sources_match(snapshot, manifest['source_sha256'])
    base_manifest = snapshot.parent.parent/INITIALIZER/'manifest.json'
    checks['initializer_base_manifest_binding'] = digest(base_manifest) == manifest['base_snapshot_manifest_sha256']
    if manifest['stage'] == 'confirm':
        confirmation_path = args.input.parent/'reader_confirmation.json'
        checks['reader_confirmation_present'] = confirmation_path.is_file()
        if confirmation_path.is_file():
            old_auditor = Path(__file__).resolve().parent.parent/'control_alignment_20261026/evaluate.py'
            spec = importlib.util.spec_from_file_location('confirmed_startup_audit', old_auditor)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            confirmation = json.loads(confirmation_path.read_text())
            checks.update(confirmation_checks(data, confirmation, module.startup_getter_proof))
            result['reader_confirmation_sha256'] = digest(confirmation_path)
            result['startup_proof_auditor_sha256'] = digest(old_auditor)
        result['reader_confirmation_verified'] = bool(all(value for key, value in checks.items()
            if key == 'reader_confirmation_present' or key.startswith('confirmation_')))
    result['diagnostic_complete'] = bool(all(checks.values()))
    result['failed_checks'] = [key for key, value in checks.items() if not value]
    if not result['diagnostic_complete']:
        result.update(reader_status='UNKNOWN', all_readers_equivalent=False, fresh_direct_batch_equivalent=False)
    result.update(capture_sha256=digest(args.input), evaluator_sha256=digest(__file__))
    result.update(manifest_sha256=digest(manifest_path), source_commit=manifest['source_commit'],
        base_snapshot_manifest_sha256=manifest['base_snapshot_manifest_sha256'])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    raise SystemExit(0 if result['diagnostic_complete'] else 1)


if __name__ == '__main__': main()

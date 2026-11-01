"""Independent nominal destination geometry/state audit; no production planner calls."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import time
import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
ZONES = ('B', 'C', 'D')
PITCH = .032
HEIGHT = .0096
ATOL = 1e-9


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def near(actual, expected, atol=ATOL):
    a, b = np.asarray(actual, float), np.asarray(expected, float)
    return bool(a.shape == b.shape and np.isfinite(a).all() and np.allclose(a, b, atol=atol, rtol=0))


def body_height_metadata(value):
    return math.isfinite(value) and abs(value-HEIGHT) <= math.ulp(HEIGHT)


def raw_rotation(pose):
    return np.asarray(pose['O_T_EE'], float).reshape(4, 4, order='F')[:3, :3]


def frame(reference):
    poses = {r['id']: r for r in reference['poses']}
    origin = np.asarray(poses['a_0_0_9']['xyz_m'], float)
    u = np.asarray(poses['a_0_1_9']['xyz_m'], float)-origin
    v = np.asarray(poses['a_1_0_9']['xyz_m'], float)-origin
    u /= np.linalg.norm(u); v /= np.linalg.norm(v)
    if not near([u[2], v[2], u@v], [0., 0., 0.]): raise ValueError('Horizontal orthogonal reference grid required')
    rotations = []
    for axis, name in ((v, 'a_0_0_8'), (u, 'a_0_0_9')):
        raw = raw_rotation(poses[name]); candidates = []
        for sign in (1., -1.):
            x = sign*axis; z = np.array([0., 0., -1.]); y = np.cross(z, x)
            candidates.append(np.column_stack((x, y, z)))
        rotations.append(max(candidates, key=lambda r: float(np.trace(raw.T@r))))
    return poses, u, v, rotations


def expected_slot(poses, u, v, rotations, zone, count):
    k, rem = divmod(count, 12); n, m = divmod(rem, 3)
    anchor = np.asarray(poses[dict(zip(ZONES, ('point_11', 'point_14', 'point_15')))[zone]]['xyz_m'], float)
    center = anchor[:2]+PITCH*(1.5*u[:2]+v[:2])
    long, across = (v, u) if k % 2 == 0 else (u, v)
    xy = center+PITCH*((m-1)*long[:2]+(n-1.5)*across[:2])
    z = poses['point_03']['xyz_m'][2]-9*HEIGHT+k*HEIGHT
    position = np.array([*xy, z]); rotation = rotations[k % 2]
    matrix = np.eye(4); matrix[:3, :3] = rotation; matrix[:3, 3] = position
    corners = np.array([position+dl*long+da*across for dl, da in ((-.016, -.008), (.016, -.008), (.016, .008), (-.016, .008))])
    return {'id': f'{zone.lower()}_{n}_{m}_{k}', 'n': n, 'm': m, 'k': k, 'position': position,
        'matrix': matrix, 'rotation': rotation, 'corners': corners, 'long': long, 'across': across,
        'center': np.array([*center, z])}


def slot_checks(row, expected, zone, count, assumptions):
    q = np.asarray(row['quaternion_wxyz'], float)
    quaternion_ok = q.shape == (4,) and bool(np.isfinite(q).all()) and abs(np.linalg.norm(q)-1) <= ATOL
    quaternion_rotation = Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix() if quaternion_ok else np.zeros((3, 3))
    return {'index': row['id'] == expected['id'] and row['destination'] == zone and row['count'] == count
            and all(row[key] == expected[key] for key in ('n', 'm', 'k')),
        'frames': row['reference_frame'] == 'robot_base_O' and row['pose_frame'] == 'configured_end_effector_EE',
        'position': near(row['position_m'], expected['position']),
        'matrix': near(row['T_base_EE'], expected['matrix']),
        'column_major': near(row['O_T_EE'], expected['matrix'].reshape(-1, order='F')),
        'quaternion': quaternion_ok and near(quaternion_rotation, expected['rotation']),
        'axes': near(row['long_axis_base'], expected['long']) and near(row['across_axis_base'], expected['across']),
        'corners': near(row['footprint_corners_base_m'], expected['corners']),
        'individual_center': near(np.mean(np.asarray(row['footprint_corners_base_m']), axis=0), expected['position']),
        'common_center': near(row['footprint_center_base_m'], expected['center']),
        'native_pitch_height': row['pitch_m'] == PITCH and body_height_metadata(row['body_height_m']),
        'assumptions': row['assumptions'] == assumptions,
        'no_authorization': row['hardware_authorized'] is False}


def expected_route(label, requested, palette, rejects):
    if label is None or label == 'UNKNOWN': return {'decision': 'abstain', 'destination': None, 'reason': 'unknown_color'}
    if label in rejects: return {'decision': 'reject', 'destination': 'REJECT', 'reason': 'configured_reject_color'}
    if label not in palette: return {'decision': 'abstain', 'destination': None, 'reason': 'unrecognized_color'}
    other = [color for color in palette if color not in requested]
    zone = 'B' if label in requested else ('C', 'D')[other.index(label)]
    return {'decision': 'route', 'destination': zone, 'reason': 'configured_color_route'}


def route_checks(rows, preferences, palette, rejects):
    requests = [tuple(v) for size in (1, 2, 3) for v in itertools.combinations(palette, size)]
    labels = [*palette, *rejects, None, 'UNKNOWN', 'bright_red', 'ochre']
    wanted = {(r, json.dumps(label)) for r in requests for label in labels}
    observed = [(tuple(r['requested']), json.dumps(r['label'])) for r in rows]
    wanted_preferences = {(r, count) for r in requests for count in range(6)}
    actual_preferences = [(tuple(r['requested']), r['count']) for r in preferences]
    return {'all_routing_cases': len(observed) == len(set(observed)) == len(wanted) and set(observed) == wanted,
        'routing_results': all(tuple(r['requested']) in requests
            and r['result'] == expected_route(r['label'], r['requested'], palette, rejects) for r in rows),
        'all_preference_cases': len(actual_preferences) == len(set(actual_preferences)) == len(wanted_preferences)
            and set(actual_preferences) == wanted_preferences,
        'preference_cycle': all(r['result'] == r['requested'][r['count'] % len(r['requested'])] for r in preferences)}


def overlap(corners_a, corners_b, u, v):
    axes = np.column_stack((u, v))
    a, b = np.asarray(corners_a)@axes, np.asarray(corners_b)@axes
    common = np.minimum(a.max(axis=0), b.max(axis=0))-np.maximum(a.min(axis=0), b.min(axis=0))
    return bool(np.all(common > ATOL))


def angle_deg(a, b):
    return math.degrees(math.acos(float(np.clip((np.trace(np.asarray(a).T@np.asarray(b))-1)/2, -1, 1))))


def line_angle_deg(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return math.degrees(math.acos(float(np.clip(abs(a@b)/(np.linalg.norm(a)*np.linalg.norm(b)), 0, 1))))


def confirmation_checks(rows, rejects):
    zero = dict.fromkeys(ZONES, 0)
    b = lambda value: {**zero, 'B': value}
    expected = {'proposal_no_change': (zero, zero, 'ok', 'b_0_0_0'),
        'abstention_reject_no_change': (zero, zero, 'ok', [
            {'decision': 'abstain', 'destination': None, 'reason': 'unknown_color'},
            {'decision': 'reject', 'destination': 'REJECT', 'reason': 'configured_reject_color'}]),
        'confirm_0_to_1': (zero, b(1), 'ok', 1), 'stale_0_rejected': (b(1), b(1), 'ValueError', None),
        'confirm_11_to_12': (b(11), b(12), 'ok', 12), 'confirm_299_to_300': (b(299), b(300), 'ok', 300),
        'capacity_rejected': (b(300), b(300), 'OverflowError', None)}
    names = [r['case'] for r in rows]
    checks = {'confirmation_case_inventory': len(names) == len(set(names)) == len(expected) and set(names) == set(expected)}
    for row in rows:
        target = expected.get(row['case'])
        checks['confirmation_'+row['case']] = target is not None and (row['before'], row['after'], row['outcome'], row['result']) == target
    return checks


def orientation_checks(rows, poses, slots, rotations, u, v):
    checks = {'eight_raw_orientation_records': len(rows) == 8 and {r['recorded_id'] for r in rows} == {f'point_{i:02d}' for i in range(8, 16)}}
    summaries = []
    for row in rows:
        name = row['recorded_id']; number = int(name.split('_')[-1]); raw = raw_rotation(poses[name])
        zone = {14: 'C', 15: 'D'}.get(number, 'B'); anchor = number in (11, 14, 15)
        prefix = name+'_'
        checks[prefix+'raw_retained'] = near(row['raw_R_base_EE'], raw, 0.)
        checks[prefix+'source_not_rewritten'] = row['original_export_modified'] is False and row['raw_Z_reused'] is False
        checks[prefix+'anchor_semantics'] = row['anchor_destination'] == (zone if anchor else None)
        proposals = {r['parity']: r for r in row['proposed']}
        neighbors = {r['parity']: r for r in row['nearest_slot_xy_by_parity']}
        checks[prefix+'two_parity_diagnostics'] = len(proposals) == len(row['proposed']) == 2 and set(proposals) == {0, 1} \
            and len(neighbors) == len(row['nearest_slot_xy_by_parity']) == 2 and set(neighbors) == {0, 1}
        expected_nearest = []
        for parity in (0, 1):
            proposal = proposals[parity]; long = v if parity == 0 else u
            change = angle_deg(raw, rotations[parity]); line = line_angle_deg(raw[:, 0], long)
            checks[prefix+f'parity{parity}_geometry'] = near(proposal['rotation_matrix'], rotations[parity]) \
                and abs(proposal['orientation_change_deg']-change) <= 1e-4 \
                and abs(proposal['long_axis_line_error_deg']-line) <= 1e-4
            candidates = [slots[(zone, count)] for count in range(parity*12, parity*12+12)]
            distances = [float(np.linalg.norm(np.asarray(r['position_m'])[:2]-poses[name]['xyz_m'][:2])) for r in candidates]
            index = int(np.argmin(distances)); expected_nearest.append(distances[index]); observed = neighbors[parity]
            checks[prefix+f'parity{parity}_nearest_descriptive'] = observed['slot_id'] == candidates[index]['id'] \
                and abs(observed['residual_m']-distances[index]) <= ATOL
        recommendation = 0 if anchor else int(np.argmin(expected_nearest))
        checks[prefix+'recommendation_not_old_layer_claim'] = row['recommended_parity'] == recommendation and row['recommendation_scope'] == (
            'Operator first-slot anchor' if anchor else 'Nearest nominal XY grid only; old layer identity and measured placement are not verified')
        summaries.append({'recorded_id': name, 'anchor_destination': zone if anchor else None,
            'derived_first_parity_change_deg': angle_deg(raw, rotations[0]), 'old_layer_identity_verified': False})
    return checks, summaries


def evaluate(protocol_path, predictions):
    protocol_path = Path(protocol_path); protocol = read(protocol_path); files = {}; checks = {}
    for name, descriptor in protocol['files'].items():
        path = (protocol_path.parent/descriptor['path']).resolve()
        checks['input_pin_'+name] = sha(path) == descriptor['sha256']; files[name] = path
    reference, config = read(files['references']), read(files['config'])
    exported = read(Path(predictions)/'destinations.json')
    checks['exact_export_config'] = exported['config'] == config
    checks['reference_hash_binding'] = exported['source_reference_hash'] == protocol['files']['references']['sha256']
    checks['source_conventions'] = reference['reference_frame'] == 'robot_base_O' and reference['pose_frame'] == 'configured_end_effector_EE' \
        and reference['position_units'] == 'm' and reference['matrix_storage'] == 'column_major'
    checks['frozen_geometry_config'] = (config['anchor_ids'] == {'B': 'point_11', 'C': 'point_14', 'D': 'point_15'}
        and config['source_anchor_id'] == 'point_03' and config['source_anchor_layer_zero_based'] == 9
        and config['body_height_m'] == HEIGHT and config['center_pitch_m'] == PITCH and config['stud_pitch_m'] == .008
        and config['ridges_per_layer'] == 4 and config['bricks_per_ridge'] == 3 and config['max_layers'] == 25)
    checks['explicit_palette_reject_contract'] = config['accepted_colors'] == ['dark_red', 'brown', 'tan'] \
        and config['reject_labels'] == ['reject_4211201', 'reject_6135191']
    checks['operator_geometry_confirmation'] = all(config['operator_confirmed'][key] is True for key in (
        'two_empty_stud_rows_between_parallel_ridges', 'shared_center_between_alternating_layers',
        'destination_layer0_long_axis_points_away_from_image_bottom', 'destination_support_plane_matches_input'))
    checks['scope_honesty'] = (exported['reference_frame'] == 'robot_base_O' and exported['pose_frame'] == 'configured_end_effector_EE_nominal'
        and exported['hardware_authorized'] is False and exported['physical_held_brick_transform'] is None
        and exported['native_attachment_verified'] is False and exported['simulator_truth_used'] is False
        and exported['counts_advance_only_on_caller_confirmation'] is True and config['hardware_authorized'] is False)
    assumptions = {'alternating_layers_share_center': 'USER_CONFIRMED', 'cross_ridge_gap_two_studs': 'USER_CONFIRMED',
        'anchors_are_first_brick_EE_centers': 'ASSUMED_UNCONFIRMED', 'physical_held_brick_T_EE': 'UNVERIFIED',
        'physical_mount_registration': 'UNVERIFIED'}
    poses, u, v, rotations = frame(reference); rows = exported['slots']; by_key = {(r['destination'], r['count']): r for r in rows}
    wanted = {(zone, count) for zone in ZONES for count in range(300)}
    checks['all_900_unique_slots'] = len(rows) == len(by_key) == 900 and set(by_key) == wanted
    failures = Counter(); examples = []
    for zone, count in sorted(wanted):
        row = by_key[(zone, count)]; expected = expected_slot(poses, u, v, rotations, zone, count)
        failed = [name for name, passed in slot_checks(row, expected, zone, count, assumptions).items() if not passed]
        failures.update(failed)
        if failed and len(examples) < 8: examples.append({'id': row['id'], 'failed': failed})
    checks['all_slot_fields'] = not failures
    checks['within_ridge_32mm'] = all(near(np.asarray(by_key[(z, c+1)]['position_m'])-by_key[(z, c)]['position_m'],
        PITCH*np.asarray(by_key[(z, c)]['long_axis_base'])) for z in ZONES for c in range(300) if c % 3 != 2)
    checks['between_ridge_32mm'] = all(near(np.asarray(by_key[(z, c+3)]['position_m'])-by_key[(z, c)]['position_m'],
        PITCH*np.asarray(by_key[(z, c)]['across_axis_base'])) for z in ZONES for c in range(300) if c % 12 < 9)
    checks['two_layer_repetition'] = all(near(by_key[(z, c+24)]['position_m'][:2], by_key[(z, c)]['position_m'][:2])
        and abs(by_key[(z, c+24)]['position_m'][2]-by_key[(z, c)]['position_m'][2]-2*HEIGHT) <= ATOL
        and near(np.asarray(by_key[(z, c+24)]['T_base_EE'])[:3, :3], np.asarray(by_key[(z, c)]['T_base_EE'])[:3, :3])
        for z in ZONES for c in range(276))
    checks['relative_native_stud_lattice'] = all(near((np.asarray(r['position_m'])[:2]-by_key[(r['destination'], 0)]['position_m'][:2])@np.column_stack((u[:2], v[:2]))/.008,
        np.rint((np.asarray(r['position_m'])[:2]-by_key[(r['destination'], 0)]['position_m'][:2])@np.column_stack((u[:2], v[:2]))/.008)) for r in rows)
    no_overlap = True; extents = True
    for k in range(25):
        layer = [by_key[(zone, 12*k+i)] for zone in ZONES for i in range(12)]
        no_overlap = no_overlap and not any(overlap(a['footprint_corners_base_m'], b['footprint_corners_base_m'], u, v) for a, b in itertools.combinations(layer, 2))
        for zone in ZONES:
            group = [by_key[(zone, 12*k+i)] for i in range(12)]
            corners = np.asarray([p for row in group for p in row['footprint_corners_base_m']])
            expected_extent = [.112, .096] if k % 2 == 0 else [.096, .112]
            extents = extents and near(np.ptp(corners@np.column_stack((u, v)), axis=0), expected_extent)
    checks['no_nominal_same_layer_overlap'] = no_overlap
    checks['nominal_layer_extents_both_parities'] = extents
    checks.update(route_checks(exported['routing_examples'], exported['preference_examples'], config['accepted_colors'], config['reject_labels']))
    checks.update(confirmation_checks(exported['confirmation_examples'], config['reject_labels']))
    orientation, summaries = orientation_checks(exported['orientation_review'], poses, by_key, rotations, u, v); checks.update(orientation)
    return {'nominal_plan_contract_passed': bool(all(checks.values())), 'checks': checks,
        'failed_checks': [name for name, passed in checks.items() if not passed], 'slot_failure_counts': dict(failures),
        'failed_slot_examples': examples, 'slots_evaluated': len(rows), 'routing_examples': len(exported['routing_examples']),
        'preference_examples': len(exported['preference_examples']), 'confirmation_examples': len(exported['confirmation_examples']),
        'raw_orientation_review': summaries, 'common_first_layer_EE_z_m': poses['point_03']['xyz_m'][2]-9*HEIGHT,
        'native_center_pitch_m': PITCH, 'preserved_A_reference_center_pitch_m': .0318,
        'nominal_per_layer_footprint_extent_m': {'even': [.112, .096], 'odd': [.096, .112]},
        'physical_plate_tape_clearance_status': 'UNKNOWN; no registered plate/tape boundaries supplied',
        'actual_held_brick_T_EE': None, 'hardware_authorized': False, 'placement_verified': False,
        'native_attachment_verified': False, 'manipulation_success_claim': False,
        'confirmation_scope': 'Pure caller-acknowledgment/state-interface examples only; no observed physical placement.',
        'reject_scope': 'Configured symbolic labels only; this audit supplies no reject classifier or quality evidence.',
        'source_reference_sha256': protocol['files']['references']['sha256'], 'config_sha256': protocol['files']['config']['sha256'],
        'export_sha256': sha(Path(predictions)/'destinations.json')}


def self_test():
    one_ulp = math.nextafter(HEIGHT, math.inf)
    two_ulps = math.nextafter(one_ulp, math.inf)
    assert body_height_metadata(HEIGHT) and body_height_metadata(one_ulp)
    assert not body_height_metadata(two_ulps) and not body_height_metadata(float('nan'))
    # Invented reference, deliberately different destination Z values.
    points = {'a_0_0_9': [.4, .1, .1], 'a_0_1_9': [.3682, .1, .1], 'a_1_0_9': [.4, .0682, .1],
        'a_0_0_8': [.4159, .0841, .0904], 'point_03': [.4, .1, .1],
        'point_11': [.5, -.3, 12.], 'point_14': [.3, -.3, 13.], 'point_15': [.3, -.5, 14.]}
    poses = []
    for name, xyz in points.items():
        matrix = np.eye(4); matrix[:3, 3] = xyz
        matrix[:3, :3] = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]]) if name == 'a_0_0_8' else np.diag([1, -1, -1])
        poses.append({'id': name, 'xyz_m': xyz, 'O_T_EE': matrix.reshape(-1, order='F').tolist()})
    p, u, v, rotations = frame({'poses': poses})
    first = expected_slot(p, u, v, rotations, 'B', 0)
    assert near(first['position'], [.5, -.3, .0136])
    assert expected_slot(p, u, v, rotations, 'B', 11)['id'] == 'b_3_2_0'
    assert expected_slot(p, u, v, rotations, 'B', 299)['id'] == 'b_3_2_24'
    assert near(expected_slot(p, u, v, rotations, 'B', 12)['position'], [.484, -.284, .0232])
    assert near(expected_slot(p, u, v, rotations, 'B', 1)['position']-first['position'], [0, -.032, 0])
    assert not overlap(first['corners'], expected_slot(p, u, v, rotations, 'B', 1)['corners'], u, v)
    assert overlap(first['corners'], first['corners']+[.001, 0, 0], u, v)
    assert expected_route('bright_red', ['tan'], ['dark_red', 'brown', 'tan'], ['reject_4211201'])['decision'] == 'abstain'
    assert expected_route('dark_red', ['tan'], ['dark_red', 'brown', 'tan'], ['reject_4211201'])['destination'] == 'C'
    zero = dict.fromkeys(ZONES, 0)
    bad = [{'case': 'stale_0_rejected', 'before': {**zero, 'B': 1}, 'after': {**zero, 'B': 2}, 'outcome': 'ValueError', 'result': None}]
    assert not confirmation_checks(bad, ['reject_4211201'])['confirmation_stale_0_rejected']
    print('PASS: invented anchor/height/index/parity, no-overlap, abstention and stale-count counterexample')


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--inputs', type=Path, default=HERE/'protocol.json')
    parser.add_argument('--predictions', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true'); args = parser.parse_args()
    if args.self_test: self_test(); return
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required for reference/900-slot evaluation')
    if args.predictions is None or args.output is None: parser.error('--predictions and --output required')
    start = time.monotonic(); result = evaluate(args.inputs, args.predictions); result['wall_seconds'] = time.monotonic()-start
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    raise SystemExit(0 if result['nominal_plan_contract_passed'] else 1)


if __name__ == '__main__': main()

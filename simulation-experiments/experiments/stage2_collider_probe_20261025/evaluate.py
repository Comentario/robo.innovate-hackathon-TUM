"""Independent observation-only collider/tensor correspondence; never a pick gate."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_native(value):
    """Preserve numeric/boolean meaning while removing NumPy JSON scalar types."""
    if isinstance(value, np.generic):
        return json_native(value.item())
    if isinstance(value, np.ndarray):
        return json_native(value.tolist())
    if isinstance(value, dict):
        return {key: json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(item) for item in value]
    return value


def load_helpers():
    path = ROOT/'experiments/stage2_exploratory_20261025/evaluation/contact_helpers.py'
    spec = importlib.util.spec_from_file_location('frozen_contact_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compatible(tensor, event, rules):
    """One fixed force-on-sensor convention; no sign selection or shape fitting."""
    close = lambda a, b, atol: bool(np.all(np.abs(np.asarray(a)-b) <= atol))
    return (tensor['partner'] == event['partner']
            and np.linalg.norm(np.asarray(tensor['position'])-event['position']) <= rules['position_atol_m']
            and abs(tensor['separation']-event['separation']) <= rules['separation_atol_m']
            and close(tensor['normal'], event['normal'], rules['normal_atol'])
            and bool(np.all(np.abs(np.asarray(tensor['impulse'])-event['impulse']) <=
                            rules['impulse_atol_Ns']+rules['impulse_rtol']*np.abs(event['impulse']))))


def map_points(tensors, events, rules):
    """Require unique edges both ways, rather than silently resolving ambiguous pairs."""
    adjacency = [[j for j, event in enumerate(events) if compatible(point, event, rules)]
                 for point in tensors]
    reverse = [[i for i, matches in enumerate(adjacency) if j in matches]
               for j in range(len(events))]
    passed = all(len(matches) == 1 for matches in adjacency+reverse)
    matches = [{'tensor_row': tensors[i]['row'], 'event': events[js[0]]['index'],
                'role': events[js[0]]['role'], 'collider': events[js[0]]['collider']}
               for i, js in enumerate(adjacency) if len(js) == 1 and len(reverse[js[0]]) == 1]
    return {'status': 'MAPPED' if passed else 'UNKNOWN', 'tensor_loaded_count': len(tensors),
            'event_loaded_count': len(events), 'tensor_match_counts': list(map(len, adjacency)),
            'event_match_counts': list(map(len, reverse)), 'matches': matches}


def event_points(record, views, roles, floor, checks):
    """Headers remain private; each sensor gets its own actor-order-oriented stream."""
    streams = {label: [] for label in views}
    for callback_index, callback in enumerate(record['callbacks']):
        count = callback['raw_contact_data_count']
        used = []
        checks[f'callback_{callback_index}_capacity'] = isinstance(count, int) and 0 <= count < 1024
        checks[f'callback_{callback_index}_clock'] = (record['time_before_s']-1e-7 <=
            callback['observed_clock_s'] <= record['time_after_s']+1e-7)
        for header_index, header in enumerate(callback['headers']):
            start, number = header['contact_data_offset'], header['num_contact_data']
            indices = [p['data_index'] for p in header['points']]
            valid = (isinstance(start, int) and isinstance(number, int) and number >= 0 and
                     (number == 0 and not indices or number > 0 and start >= 0 and
                      start+number <= count and indices == list(range(start, start+number))))
            checks[f'callback_{callback_index}_header_{header_index}_ranges'] = valid
            used.extend(indices)
            if not valid:
                continue
            if not number:
                continue
            for label, view in views.items():
                sensor = view['sensor_paths'][0]
                actors = [header['actor0'], header['actor1']]
                if actors.count(sensor) != 1:
                    continue
                side = actors.index(sensor)
                sign = 1 if side == 0 else -1
                robot_colliders = [c for c in (header['collider0'], header['collider1']) if c in roles]
                role = roles[robot_colliders[0]]['role'] if len(robot_colliders) == 1 else 'UNKNOWN'
                for slot in (0, 1):
                    collider = header['collider'+str(slot)]
                    if collider in roles:
                        checks[f'callback_{callback_index}_header_{header_index}_robot_{slot}'] = (
                            header['proto_index'+str(slot)] == 0xFFFFFFFF and
                            collider.startswith(actors[slot]+'/') and
                            roles[collider]['side'] == actors[slot].rsplit('/', 1)[-1].removeprefix('fr3_').removesuffix('finger'))
                for point in header['points']:
                    n, impulse = np.asarray(point['normal'], float), np.asarray(point['impulse'], float)
                    finite = (n.shape == impulse.shape == (3,) and np.isfinite(n).all() and
                              np.isfinite(impulse).all() and np.isfinite(point['position']).all() and
                              np.isfinite(point['separation']))
                    checks[f'event_{callback_index}_{header_index}_{point["data_index"]}_finite'] = bool(finite)
                    if not finite:
                        continue
                    length = np.linalg.norm(n)
                    checks[f'event_{callback_index}_{header_index}_{point["data_index"]}_unit_normal'] = bool(abs(length-1) <= 1e-3)
                    if not length:
                        continue
                    n = n/length
                    normal_impulse = float(impulse@n)
                    if abs(normal_impulse)/record['dt_s'] <= floor:
                        continue
                    streams[label].append({'index': [callback_index, header_index, point['data_index']],
                        'position': point['position'], 'normal': sign*n,
                        'impulse': sign*normal_impulse*n, 'separation': point['separation'],
                        'role': role, 'collider': robot_colliders[0] if len(robot_colliders) == 1 else None,
                        'partner': actors[1-side], 'raw_impulse': point['impulse'],
                        'tangential_impulse_Ns': (impulse-normal_impulse*n).tolist()})
        checks[f'callback_{callback_index}_all_ranges'] = (len(used) == len(set(used)) and
                                                         sorted(used) == list(range(count)))
    return streams


def tensor_points(data, paths, helper, dt, capacity, floor):
    points = []
    for pair_index, partner in enumerate(paths):
        for row in helper.pair_rows(data, pair_index, capacity):
            force = float(np.asarray(data['normal_forces_N'][row]).item())
            if abs(force) <= floor:
                continue
            points.append({'row': int(row), 'position': data['normal_points_world_m'][row],
                'separation': float(np.asarray(data['normal_separations_m'][row]).item()),
                'normal': np.sign(force)*data['normal_vectors_world'][row],
                'impulse': force*dt*data['normal_vectors_world'][row], 'partner': partner})
    return points


def public_packet(record, roles, actor_sides):
    """Independently reproduce the only allowed online fields, without partner IDs."""
    contacts, unknown = [], 0
    for callback in record['callbacks']:
        for h in callback['headers']:
            if not h['points']:
                continue
            for slot in (0, 1):
                actor, collider = h['actor'+str(slot)], h['collider'+str(slot)]
                if actor not in actor_sides:
                    continue
                known = roles.get(collider)
                if known is None or known['side'] != actor_sides[actor] or h['proto_index'+str(slot)] != 0xFFFFFFFF:
                    unknown += 1
                    continue
                sign = 1 if slot == 0 else -1
                for p in h['points']:
                    n, j = np.asarray(p['normal']), np.asarray(p['impulse'])
                    length = np.linalg.norm(n)
                    if not np.isfinite(length) or abs(length-1) > 1e-3:
                        unknown += 1
                        continue
                    n = n/length
                    projected = float(j@n)*n
                    contacts.append({'side': known['side'], 'role': known['role'],
                        'point_world_m': p['position'], 'normal_robot_world': (sign*n).tolist(),
                        'normal_impulse_on_robot_world_Ns': (sign*projected).tolist(),
                        'normal_force_on_robot_world_N': (sign*projected/record['dt_s']).tolist()})
    return {'step': record['step'], 'complete': bool(record['complete'] and not unknown),
            'unknown_robot_shapes': unknown, 'robot_contacts': contacts}


def audit(folder):
    started = time.monotonic()
    folder = Path(folder)
    protocol_path = HERE/'protocol.json'
    protocol, metadata = read(protocol_path), read(folder/'metadata.json')
    helper = load_helpers()
    contact_protocol = read(ROOT/'experiments/stage2_exploratory_20261025/evaluation/contact_protocol.json')
    manifest = read(folder.parent/'manifest.json')
    checks = {'execution_authorized': protocol['execution_authorized'] is True,
              'capture_protocol_pin': metadata['protocol_sha256'] == sha(protocol_path),
              'manifest_protocol_pin': manifest['protocol_sha256'] == sha(protocol_path),
              'source_manifest': all(sha(folder.parent/p) == h for p, h in manifest['sha256'].items()),
              'prior_clock_pin': sha(HERE/'prior_supervisor.json') == protocol['prior_supervisor_sha256'],
              'prior_clock_value': read(HERE/'prior_supervisor.json')['cumulative_case_seconds'] == protocol['prior_case_seconds'],
              'dt': metadata['dt_s'] == protocol['physics_dt_s']}
    marker = read(folder/'probe_complete.json')
    checks['capture_completed'] = (marker['capture_completed'] is True and
        marker['status'] == metadata['controller_status'] == 'observation_sequence_completed'
        and not marker['stop_reasons'] and not (folder/'failure.json').exists())
    checks['role_sequence_completed'] = ([v['id'] for v in metadata['roles']] == ['BODY', 'WHITE', 'HEAD']
        and all(v['retracted_unloaded'] is True for v in metadata['roles']))
    checks['aggregate_budget'] = (protocol['prior_case_seconds']+protocol['maximum_active_seconds'] <=
                                 protocol['aggregate_case_ceiling_seconds'])
    initial, terminal = metadata['settings_initial'], metadata['settings_terminal']
    baseline = protocol['source_metadata']
    checks['closed_pick_settings_pin'] = sha(baseline['path']) == baseline['sha256']
    checks['closed_pick_settings_unchanged'] = initial == read(baseline['path'])['settings_initial']
    checks['all_settings_unchanged'] = initial == terminal
    cook = read(folder/metadata['cook_file'])
    quantization = read(ROOT/'experiments/stage2_exposed_tip_20261025/model_config.json')['canonical_hash_quantization']
    cooked_hashes = {}
    for label, parts in cook['tips'].items():
        canonical = {}
        for kind, part in parts.items():
            checks['cook_'+label+'_'+kind] = (part['result_valid'] is True and part['hull_count'] == len(part['hulls']) == 1)
            hull = part['hulls'][0]
            vertices = np.asarray(hull['vertices_m']); planes = np.asarray([p['plane'] for p in hull['polygons']])
            lengths = np.linalg.norm(planes[:, :3], axis=1)
            checks['cook_arrays_'+label+'_'+kind] = bool(np.isfinite(vertices).all() and np.isfinite(planes).all()
                and np.all(lengths > 0) and len(vertices) == hull['vertex_count'] and len(planes) == hull['polygon_count']
                and 4 <= len(vertices) <= 255 and 4 <= len(planes) <= 255)
            planes = planes/lengths[:, None]
            rows = np.c_[np.rint(planes[:, :3]/quantization['unit_normal']),
                         np.rint(planes[:, 3]/quantization['plane_offset_m'])].astype(np.int64)
            canonical[kind] = {'vertices': sorted(map(tuple, np.rint(vertices/quantization['vertex_m']).astype(np.int64).tolist())),
                               'normalized_planes': sorted(map(tuple, rows.tolist()))}
        cooked_hashes[label] = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    checks['actual_cooked_identity'] = cooked_hashes == cook['canonical_sha256'] == initial['cooked_hashes']
    checks['PGS'] = bool(initial['physics_scenes']) and all(s['solverType'] == 'PGS' for s in initial['physics_scenes'])
    actors = initial['source_actor_settings']
    checks['source_32_4'] = len(actors) == 300 and all(v == [32, 4] for v in actors.values())
    checks['all_reporters_zero'] = bool(metadata['reporters']) and all(v == 0 for v in metadata['reporters'].values())
    inventory = read(folder/metadata['source_initial']['inventory_file'])
    ids, edges = inventory['ids'], inventory['initial_edges']
    checks['initial_source_inventory'] = (len(ids) == len(set(ids)) == 301 and len(edges) == 930
        and metadata['source_initial']['ids'] == ids and metadata['source_initial']['initial_edges'] == edges)
    source = metadata['source_terminal']
    checks['terminal_source_graph'] = (source['parts'] == 301 and source['connections'] == 930
                                       and source['stationary_watchdog_asserted'] is True)
    native = read(folder/metadata['native_observer_metadata'])
    observer = read(folder/metadata['observer_metadata'])
    views = observer['resolved_views']
    checks['three_tensor_views'] = set(views) == {'left', 'right', 'coupon'}
    checks['filter_coverage'] = all(not v['missing_requested_filter_paths'] and not v['extra_resolved_filter_paths']
                                    and v['max_contact_data_count'] == 1024 for v in views.values())
    checks['sensor_paths'] = (all(v['sensor_count'] == 1 and len(v['sensor_paths']) == 1 for v in views.values())
        and views['coupon']['sensor_paths'] == [metadata['fixture_path']])
    geometry = read(folder/'tool_geometry.json')
    expected_roles = {c['path']: {'side': label, 'role': ('BODY' if c['is_pad'] else
        'HEAD' if c.get('role') == 'head' else 'WHITE')}
        for label, finger in geometry['fingers'].items() for c in finger['colliders'] if c['enabled']}
    roles = metadata['role_paths']
    checks['role_inventory'] = ({p: {'side': v['side'], 'role': v['role'].upper()} for p, v in roles.items()} == expected_roles
                                and native['role_paths'] == roles)
    checks['actor_roles'] = native['actor_sides'] == {f['body_path']: label for label, f in geometry['fingers'].items()}
    checks['reporter_coverage'] = set(metadata['reporters']) == {v['sensor_paths'][0] for v in views.values()}
    checks['native_buffer_capacity'] = native['maximum_points_per_callback'] == 1024
    checks['native_api_pin'] = any(e['sha256'] == native['api_sha256'] for e in protocol['source_api_evidence'])
    checks['fixed_fixture_preflight'] = len(metadata['fixture_preflight']) == len(protocol['fixtures']) == 3
    for fixture, recorded in zip(protocol['fixtures'], metadata['fixture_preflight']):
        finger = geometry['fingers'][fixture['side']]
        path = finger['body_path']+'/'+fixture['collider_suffix']
        target = next(c for c in finger['colliders'] if c['path'] == path)
        distance = helper.surface_distance(np.asarray(fixture['point_finger_m']), target['points_finger_m'], target['triangle_indices'])
        normal, point = np.asarray(fixture['outward_finger']), np.asarray(fixture['point_finger_m'])
        centers = [point+(protocol['probe_size_m']/2+protocol['initial_clearance_m']-s)*normal
                   for s in (0., protocol['maximum_travel_m'])]
        low, high = np.min(centers, axis=0)-protocol['probe_size_m']/2, np.max(centers, axis=0)+protocol['probe_size_m']/2
        isolation = all(np.any(np.asarray(c['bounds_finger_m'])[1] < low) or
                        np.any(np.asarray(c['bounds_finger_m'])[0] > high) for c in finger['colliders'] if c['path'] != path)
        checks['fixture_'+fixture['id']] = (all(recorded[k] == v for k, v in fixture.items())
            and recorded['path'] == path and distance <= protocol['matching']['position_atol_m']
            and abs(distance-recorded['patch_surface_distance_m']) <= 1e-12
            and bool(isolation) and np.max(abs(np.asarray(recorded['swept_cube_bounds_finger_m'])-[low, high])) <= 1e-12
            and all(v['isolated_by_swept_AABB'] for v in recorded['other_colliders'])
            and {v['path'] for v in recorded['other_colliders']} == {c['path'] for c in finger['colliders'] if c['path'] != path})
    with np.load(folder/'evaluation_truth'/inventory['body_states_file'], allow_pickle=False) as raw:
        initial_states = raw['states'].copy()
    checks['initial_states'] = initial_states.shape == (301, 13) and bool(np.isfinite(initial_states).all())
    truth = {}
    with (folder/'evaluation_truth/trace.jsonl').open() as stream:
        for line in stream:
            r = json.loads(line)
            if r['step'] in truth:
                raise ValueError('Duplicate private native-state frame')
            truth[r['step']] = r
    totals = {role: {'loaded_frames': 0, 'mapped_points': 0, 'peak_force_N': 0., 'threshold_frames': 0}
              for role in ('BODY', 'WHITE', 'HEAD')}
    proprio = metadata['initial_proprioception']
    finger_initial = np.asarray(proprio['finger_poses_world_wxyz']['left'])
    fixed_rotation = helper.rotation(finger_initial[3:])
    finger_indices = [metadata['joint_names'].index('fr3_finger_joint'+str(i)) for i in (1, 2)]
    fixtures = {f['id']: f for f in protocol['fixtures']}
    frames, step, previous, raw_identities = [], 0, None, {}
    role_order, quiet_run, tails = [], 0, {r: [] for r in totals}
    with (folder/'trace.jsonl').open() as stream:
        for line in stream:
            if time.monotonic()-started >= 32:
                raise TimeoutError('Independent audit budget exhausted; no partial promotion')
            row = json.loads(line)
            step += 1
            private = truth[step]
            with np.load(folder/'evaluation_truth'/private['state_file'], allow_pickle=False) as raw:
                states = raw['states'].copy()
            q1, q0 = states[:, 3:7], initial_states[:, 3:7]
            q1 = q1/np.linalg.norm(q1, axis=1)[:, None]
            q0 = q0/np.linalg.norm(q0, axis=1)[:, None]
            angle = 2*np.arccos(np.clip(abs(np.sum(q1*q0, axis=1)), 0, 1))
            local = {'sequence': row['step'] == step,
                'role_phase': row['role'] in ('BODY', 'WHITE', 'HEAD', 'quiet') and row['phase'] in ('quiet', 'approach', 'retract', 'release'),
                'clock': row['physics_dt_s'] == metadata['dt_s'] and abs(row['time_s']-row['time_before_s']-metadata['dt_s']) <= 1e-7,
                'finite_robot': bool(np.isfinite(row['robot_q']).all() and np.isfinite(row['robot_qdot']).all()),
                'source': row['source_guard']['finite'] is True and row['source_guard']['parts'] == 301
                    and row['source_guard']['connections'] == 930 and row['source_guard']['stationary_watchdog_asserted'] is True
                    and row['source_guard']['break_events_asserted_empty'] is True,
                'fixture_travel': abs(row['fixture_travel_m']) <= protocol['maximum_travel_m']+2e-6}
            local['private_source_clock'] = private['time_s'] == row['time_s'] and not private['nonfinite']
            local['private_source_states'] = states.shape == initial_states.shape and bool(np.isfinite(states).all())
            local['private_source_graph'] = (len(private['edges']) == len(set(private['edges'])) == 930
                and set(private['edges']) == {e['id'] for e in edges} and not private['break_events']
                and len(private['components']) == 1 and sorted(private['components'][0]) == list(range(301)))
            local['private_source_drift'] = bool(np.max(np.linalg.norm(states[:, :3]-initial_states[:, :3], axis=1)) <= .002
                                                and np.max(angle) <= np.deg2rad(2))
            actual, command = np.asarray(row['fixture_pose_world_wxyz']), np.asarray(row['fixture_command_pose_world_wxyz'])
            p_error = float(np.linalg.norm(actual[:3]-command[:3]))
            a_error = helper.angle_between(actual[3:], command[3:])
            local['kinematic_readback'] = (bool(np.isfinite(actual).all() and np.isfinite(command).all())
                and p_error <= protocol['matching']['position_atol_m'] and a_error <= 1e-4
                and abs(p_error-row['fixture_command_readback_position_error_m']) <= 1e-12
                and abs(a_error-row['fixture_command_readback_angle_rad']) <= 1e-7)
            tcp = row['tcp_pose_world_wxyz']; initial_tcp = proprio['tcp_pose_world_wxyz']
            local['stationary_TCP'] = (np.linalg.norm(np.asarray(tcp[:3])-initial_tcp[:3]) <= .002
                                       and helper.angle_between(tcp[3:], initial_tcp[3:]) <= np.deg2rad(2))
            local['finger_velocity'] = bool(np.max(abs(np.asarray(row['robot_qdot'])[finger_indices])) <= .002)
            if row['role'] == 'quiet':
                quiet_run += 1
                local['parked_command'] = bool(np.linalg.norm(command[:3]-[2., 2., .5]) <= 1e-12)
            elif row['role'] in fixtures:
                fixture = fixtures[row['role']]
                local_point = np.asarray(fixture['point_finger_m'])+(protocol['probe_size_m']/2+
                    protocol['initial_clearance_m']-row['fixture_travel_m'])*np.asarray(fixture['outward_finger'])
                local['fixed_fixture_command'] = bool(np.linalg.norm(command[:3]-(finger_initial[:3]+fixed_rotation@local_point)) <= 1e-12)
                local['fixed_fixture_orientation'] = helper.angle_between(command[3:], finger_initial[3:]) <= 1e-7
                if previous is None or previous['role'] != row['role']:
                    local['role_order_and_unloaded_placement'] = (len(role_order) < 3 and row['role'] == list(totals)[len(role_order)]
                        and quiet_run == protocol['quiet_steps']//3 and previous is not None
                        and max(previous['forces_N'].values()) <= protocol['force_floor_N'])
                    role_order.append(row['role'])
                else:
                    command_step = np.linalg.norm(command[:3]-np.asarray(previous['fixture_command_pose_world_wxyz'])[:3])
                    actual_step = np.linalg.norm(actual[:3]-np.asarray(previous['fixture_pose_world_wxyz'])[:3])
                    local['command_speed'] = command_step <= protocol['maximum_speed_m_s']*metadata['dt_s']+1e-12
                    local['actual_motion_readback_bound'] = (actual_step <= protocol['maximum_speed_m_s']*metadata['dt_s']+
                                                            2*protocol['matching']['position_atol_m']+1e-12)
                quiet_run = 0
            if previous:
                local['continuous_clock'] = abs(row['time_before_s']-previous['time_s']) <= 1e-7
            event = read(folder/row['native_events_file'])
            local['native_record'] = (event['complete'] is True and not event['errors'] and event['step'] == step
                and event['time_before_s'] == row['time_before_s'] and event['time_after_s'] == row['time_s']
                and event['dt_s'] == metadata['dt_s'] and event['out_of_window_callbacks_total'] == 0)
            for callback in event['callbacks']:
                for h in callback['headers']:
                    local['native_stage_id'] = local.get('native_stage_id', True) and h['stage_id'] == native['stage_id']
                    if not h['points']:
                        continue
                    for key in ('actor0', 'actor1', 'collider0', 'collider1'):
                        path, identity = h[key], h['raw_'+key]
                        valid = isinstance(identity, int) and 0 <= identity < 2**64
                        valid = valid and raw_identities.get(path, identity) == identity
                        valid = valid and all(v != identity or p == path for p, v in raw_identities.items())
                        local['raw_identity_consistency'] = local.get('raw_identity_consistency', True) and valid
                        raw_identities[path] = identity
            events = event_points(event, views, roles, protocol['force_floor_N'], local)
            local['online_identity_quarantine'] = row['native_online'] == public_packet(event, roles, native['actor_sides'])
            local['no_unknown_online_shape'] = row['native_online']['unknown_robot_shapes'] == 0
            loaded, maps, forces, vectors = {}, {}, {}, {}
            for label, view in views.items():
                with np.load(folder/row['contacts'][label]['file'], allow_pickle=False) as npz:
                    data = {k: npz[k].copy() for k in npz.files}
                paths = helper.filter_paths(view)
                summary = helper.view_summary(data, paths, contact_protocol, metadata['dt_s'])
                local.update({label+'_'+k: bool(v) for k, v in summary['checks'].items()})
                local[label+'_fixed_tensor_sign'] = all(1 in p['possible_signs'] for p in summary['pairs'].values())
                loaded[label] = tensor_points(data, paths, helper, metadata['dt_s'], 1024, protocol['force_floor_N'])
                maps[label] = map_points(loaded[label], events[label], protocol['matching'])
                local[label+'_complete_bijection'] = maps[label]['status'] == 'MAPPED'
                local[label+'_expected_role'] = all(m['role'].upper() == row['role'] for m in maps[label]['matches'])
                expected_partner = views['coupon' if label in ('left', 'right') else 'left']['sensor_paths'][0]
                local[label+'_expected_partner'] = all(p['partner'] == expected_partner for p in loaded[label])
                if label == 'right' or row['role'] == 'quiet':
                    local[label+'_unloaded_control'] = not loaded[label] and not events[label]
                forces[label] = sum(p['normal_magnitude_N'] for p in summary['pairs'].values())
                vectors[label] = sum((np.asarray(p['matrix_force_N']) for p in summary['pairs'].values()), np.zeros(3))
                local[label+'_force_limit'] = forces[label] <= protocol['sampled_force_abort_N']
                local[label+'_force_readback'] = abs(forces[label]-row['forces_N'][label]) <= 1e-7
            local['reciprocal_normal_force'] = helper.close(vectors['left'], -vectors['coupon'],
                contact_protocol['contact_reporting']['reciprocal_absolute_tolerance_N'],
                contact_protocol['contact_reporting']['reciprocal_relative_tolerance'])
            if row['role'] in totals:
                total = totals[row['role']]
                total['peak_force_N'] = max(total['peak_force_N'], forces['left'])
                total['threshold_frames'] += int(forces['left'] >= protocol['positive_force_N'])
                if loaded['left'] and loaded['coupon'] and all(local.values()):
                    total['loaded_frames'] += 1
                    total['mapped_points'] += len(loaded['left'])
                tails[row['role']] = (tails[row['role']]+[max(forces.values()) <= protocol['force_floor_N']
                    and row['fixture_travel_m'] == 0. and row['phase'] == 'retract'])[-3:]
            frames.append({'step': step, 'role': row['role'], 'phase': row['phase'],
                           'checks': local, 'forces_N': forces, 'mapping': maps})
            previous = row
    checks['bounded_nonempty_steps'] = 0 < step <= protocol['maximum_physics_steps']
    checks['capture_step_count'] = step == metadata['steps_executed'] == marker['steps_executed']
    checks['private_steps_complete'] = sorted(truth) == list(range(1, step+1))
    checks['terminal_source_speeds'] = bool(np.max(np.linalg.norm(states[:, 7:10], axis=1)) <= .02
                                          and np.max(np.linalg.norm(states[:, 10:13], axis=1)) <= .2)
    checks['all_frame_checks'] = all(all(f['checks'].values()) for f in frames)
    checks['three_role_controls'] = all(v['loaded_frames'] >= protocol['minimum_loaded_frames_per_role'] for v in totals.values())
    checks['independent_unloaded_release'] = all(len(v) == 3 and all(v) for v in tails.values())
    passed = all(checks.values())
    return {'proceed_gate_passed': passed, 'observation_contract_passed': passed,
        'status': 'VALIDATED_OBSERVATION_ONLY' if passed else 'UNKNOWN', 'protocol_sha256': sha(protocol_path),
        'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v], 'roles': totals,
        'steps': step, 'frames': frames, 'wall_seconds': time.monotonic()-started,
        'grasp_retry_authorized': False, 'surface_ownership_guard_replaced': False,
        'interpretation': 'Known robot shape labels only; prior failures and point-surface guards remain unchanged.'}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Actual contact-array analysis requires default Pueue')
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = audit(args.input)
    except Exception as error:
        report = {'proceed_gate_passed': False, 'observation_contract_passed': False,
                  'status': 'UNKNOWN', 'error': str(error), 'grasp_retry_authorized': False}
    (args.output/'evaluation.json').write_text(json.dumps(json_native(report), indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()

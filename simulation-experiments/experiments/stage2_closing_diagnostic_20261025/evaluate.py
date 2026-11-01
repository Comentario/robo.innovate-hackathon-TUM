"""Private current-run collider attribution; never approves a grasp or old failure."""
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


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    return loaded


def rows(path):
    result = {}
    with Path(path).open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['step'] in result:
                raise ValueError('Duplicate step in '+str(path))
            result[row['step']] = row
    return result


def private_free(value):
    """The original public trace must acquire no callback, shape or partner IDs."""
    if isinstance(value, dict):
        forbidden = ('native', 'actor', 'collider', 'partner', 'source_id', 'bound_id')
        return all(not any(word in key.lower() for word in forbidden) and private_free(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return all(private_free(item) for item in value)
    return not isinstance(value, str) or not value.startswith('/World/')


def finite_body_extent(qualifier, role, white_extra):
    distances = [qualifier[k] for k in ('pad_distance_m', 'white_distance_m', 'head_distance_m')]
    return bool(role == 'body' and all(d is not None for d in distances)
        and qualifier['flat_face_compatible'] and qualifier['lateral_qualified']
        and distances[0] > qualifier['tolerance_m']
        and min(distances[1:]) > qualifier['tolerance_m']+white_extra)


def attribution(finger_match, source_matches, selected_partner, actual_partner, qualifier, white_extra):
    """A target-pad claim additionally needs the same event in its reciprocal view."""
    reciprocal = bool(finger_match and any(m['event'] == finger_match['event'] for m in source_matches))
    selected = selected_partner == actual_partner
    known = bool(finger_match and reciprocal and selected)
    return {'status': 'IDENTIFIED_CURRENT_POINT' if known else 'UNKNOWN',
            'robot_role': finger_match['role'] if known else None,
            'robot_collider': finger_match['collider'] if known else None,
            'event_role_evidence': finger_match['role'] if finger_match else None,
            'selected_source_partner': selected, 'same_event_reciprocal': reciprocal,
            'finite_surface_only_failure': bool(known and finite_body_extent(qualifier, finger_match['role'], white_extra))}


def spatial_match(point, candidate, upper):
    """Original sensor envelope, without a native pose or actor identity input."""
    x, y = np.asarray(point[:2])-candidate['table_xy_m']; yaw = candidate['yaw_table_rad']
    c, s = np.cos(yaw), np.sin(yaw); xy = [c*x+s*y, -s*x+c*y]
    margin = .0015+.0005+np.sin(np.deg2rad(1))*.016
    return bool(abs(xy[0]) <= .016+margin and abs(xy[1]) <= .008+margin
        and upper-.0017-.0096-.0015 <= point[2] <= upper+.0015)


def audit(folder):
    started = time.monotonic(); folder = Path(folder)
    protocol = read(HERE/'protocol.json'); science = read(HERE/'science.json')
    mapper_path = ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py'
    mapper = module('validated_private_mapping', mapper_path)
    helper = mapper.load_helpers()
    contact = read(ROOT/'experiments/stage2_exploratory_20261025/evaluation/contact_protocol.json')
    checks = {'execution_authorized': protocol['execution_authorized'] is True,
              'science_pin': sha(HERE/'science.json') == protocol['science_sha256']}
    pinned = {}
    for key in ('source_metadata', 'original_selection', 'original_binding', 'prior_supervisor'):
        item = protocol[key]; checks[key+'_pin'] = sha(item['path']) == item['sha256']; pinned[key] = read(item['path'])
    validation = protocol['observer_validation']; item = validation['audit']
    checks['observer_validation_pin'] = sha(item['path']) == item['sha256']
    checks['observer_previously_validated'] = read(item['path'])['observation_contract_passed'] is True
    checks['mapping_source_pin'] = sha(mapper_path) == validation['mapping_helpers_sha256']
    checks['observer_source_pin'] = sha(ROOT/'experiments/stage2_collider_probe_20261025/native_observer.py') == validation['native_observer_sha256']
    checks['prior_clock'] = pinned['prior_supervisor']['cumulative_case_seconds'] == protocol['prior_case_seconds']
    checks['aggregate_budget'] = protocol['prior_case_seconds']+protocol['maximum_active_seconds'] <= protocol['aggregate_case_ceiling_seconds']
    manifest = read(folder.parent/'manifest.json')
    checks['frozen_snapshot'] = all(sha(folder.parent/p) == digest for p, digest in manifest['sha256'].items())
    metadata, marker = read(folder/'capture_metadata.json'), read(folder/'closing_complete.json')
    checks['metadata_science_pin'] = metadata['science_sha256'] == metadata['protocol_sha256'] == protocol['science_sha256']
    checks['metadata_diagnostic_pin'] = metadata['diagnostic_protocol_sha256'] == sha(HERE/'protocol.json')
    checks['parent_source_pin'] = metadata['diagnostic_parent_runner_sha256'] == protocol['source_runner_sha256']
    checks['complete_capture'] = marker['capture_completed'] is True and not (folder/'failure.json').exists()
    checks['no_grasp_claim'] = marker['grasp_or_extraction_claim'] is False
    baseline = pinned['source_metadata']; initial = metadata['settings_initial']
    checks['physical_settings_unchanged'] = initial == metadata['settings_terminal'] == baseline['settings_initial']
    checks['cooked_identity_record'] = read(folder/metadata['cook_file'])['canonical_sha256'] == initial['cooked_hashes']
    checks['initial_joint_state_same'] = metadata['initial_joint_positions'] == baseline['initial_joint_positions']
    checks['table_frame_unchanged'] = metadata['T_world_table'] == baseline['T_world_table']
    checks['dt_epsilon'] = metadata['dt_s'] == protocol['physics_dt_s'] == science['physics']['dt_s'] and metadata['OSQP_EPSILON'] == '1e-4'
    selection = read(folder/'online/selection.json')
    checks['public_selection_quarantine'] = private_free(selection)
    if selection.get('candidate') is None:
        return {'observation_complete': False, 'proceed_gate_passed': False, 'status': 'NOT_REPRODUCED',
                'reason': 'NO_SENSOR_SELECTED_TARGET', 'checks': checks, 'grasp_retry_authorized': False,
                'old1809_reinterpreted': False}
    observer = read(folder/metadata['observer_metadata'])
    source_observer = read(folder/metadata['evaluation_observer_metadata'])
    native = read(folder/metadata['native_observer_metadata'])
    views = {**observer['resolved_views'], **source_observer['resolved_views']}
    checks['three_sensor_views'] = set(views) == {'left', 'right', 'source'}
    checks['filter_coverage'] = all(not v['missing_requested_filter_paths'] and not v['extra_resolved_filter_paths']
        and v['sensor_count'] == 1 and len(v['sensor_paths']) == 1 and v['max_contact_data_count'] == 1024 for v in views.values())
    target = views['source']['sensor_paths'][0]
    binding = read(folder/'evaluation_truth/initial_binding.json')
    checks['private_unique_binding'] = binding['unique'] is True and len(binding['matches']) == 1 and binding['matches'][0]['id'] == target
    comparison = {'same_candidate_id': selection['candidate']['candidate_id'] == pinned['original_selection']['candidate']['candidate_id'],
                  'same_private_target': target == pinned['original_binding']['matches'][0]['id']}
    geometry = read(folder/metadata['tool_geometry_file']); roles = native['role_paths']
    expected_roles = {c['path']: {'side': label, 'role': c['role']} for label, f in geometry['fingers'].items()
                      for c in f['colliders'] if c['enabled']}
    checks['robot_role_inventory'] = roles == expected_roles
    checks['actor_inventory'] = native['actor_sides'] == {f['body_path']: label for label, f in geometry['fingers'].items()}
    checks['native_capacity'] = native['maximum_points_per_callback'] == 1024
    source_probe_path = ROOT/'experiments/stage2_collider_probe_20261025/protocol.json'
    source_probe = read(source_probe_path)
    checks['validated_observer_protocol_pin'] = sha(source_probe_path) == validation['protocol_sha256']
    checks['matching_unchanged'] = protocol['matching'] == source_probe['matching']
    checks['native_API_pin'] = any(e['sha256'] == native['api_sha256'] for e in source_probe['source_api_evidence'])
    inventory = read(folder/metadata['truth_inventory']); ids, edges = inventory['ids'], inventory['initial_edges']
    checks['initial_source_inventory'] = len(ids) == len(set(ids)) == 301 and len(edges) == 930
    with np.load(folder/'evaluation_truth'/inventory['body_states_file'], allow_pickle=False) as raw:
        first = raw['states'].copy()
    public = rows(folder/metadata['online_trace']); truth = rows(folder/metadata['truth_trace'])
    index = rows(folder/metadata['native_contact_index']); steps = sorted(public)
    checks['all_step_sequences'] = steps == sorted(truth) == sorted(index) == list(range(1, metadata['steps_executed']+1))
    checks['marker_step_status'] = marker['steps_executed'] == metadata['steps_executed'] and marker['controller_status'] == metadata['controller_status']
    checks['bounded_steps'] = 0 < len(steps) <= protocol['maximum_physics_steps']
    evidence, frames, totals, previous = [], [], {v: 0 for v in views}, metadata['initial_proprioception']
    close_steps = 0; stop_trigger = None; raw_identities = {}
    layers = {p['id']: p['layer'] for p in inventory['projected_top_faces']}
    for step in steps:
        if time.monotonic()-started >= 32:
            raise TimeoutError('Audit time exhausted; no partial observation promotion')
        row, private = public[step], truth[step]
        dt = row['physics_dt_s']; local = {'phase': row['phase'] in ('approach', 'final_approach', 'close'),
            'clock': dt == metadata['dt_s'] and row['time_s'] == private['time_s'] == index[step]['time_s'],
            'online_identity_quarantine': private_free(row)}
        close_steps += int(row['phase'] == 'close')
        with np.load(folder/'evaluation_truth'/private['state_file'], allow_pickle=False) as raw:
            states = raw['states'].copy()
        qa, qb = states[:, 3:7], first[:, 3:7]; qa = qa/np.linalg.norm(qa, axis=1)[:, None]; qb = qb/np.linalg.norm(qb, axis=1)[:, None]
        angles = 2*np.arccos(np.clip(abs(np.sum(qa*qb, axis=1)), 0, 1))
        local['private_source'] = (bool(np.isfinite(states).all()) and not private['nonfinite']
            and len(private['edges']) == len(set(private['edges'])) == 930 and set(private['edges']) == {e['id'] for e in edges}
            and not private['break_events'] and len(private['components']) == 1 and sorted(private['components'][0]) == list(range(301))
            and np.max(np.linalg.norm(states[:, :3]-first[:, :3], axis=1)) <= .002 and np.max(angles) <= np.deg2rad(2))
        event = read(folder/index[step]['native_events_file'])
        local['native_record'] = (event['complete'] is True and not event['errors'] and event['step'] == step
            and event['time_after_s'] == row['time_s'] and abs(event['time_before_s']+dt-row['time_s']) <= 1e-7
            and event['dt_s'] == dt and event['out_of_window_callbacks_total'] == 0)
        for callback in event['callbacks']:
            for h in callback['headers']:
                local['native_stage'] = local.get('native_stage', True) and h['stage_id'] == native['stage_id']
                if not h['points']: continue
                for key in ('actor0', 'actor1', 'collider0', 'collider1'):
                    path, identity = h[key], h['raw_'+key]
                    consistent = (isinstance(identity, int) and 0 <= identity < 2**64
                        and raw_identities.get(path, identity) == identity
                        and all(v != identity or p == path for p, v in raw_identities.items()))
                    local['private_raw_ID_consistency'] = local.get('private_raw_ID_consistency', True) and consistent
                    raw_identities[path] = identity
        event_streams = mapper.event_points(event, views, roles, protocol['force_floor_N'], local)
        data, loaded, mapping, summaries = {}, {}, {}, {}
        for label, view in views.items():
            record = row['contacts'][label] if label != 'source' else private['contacts']['source']
            with np.load(folder/record['file'], allow_pickle=False) as raw:
                data[label] = {k: raw[k].copy() for k in raw.files}
            paths = helper.filter_paths(view); summary = helper.view_summary(data[label], paths, contact, dt); summaries[label] = summary
            local.update({label+'_'+k: bool(v) for k, v in summary['checks'].items()})
            local[label+'_fixed_sign'] = all(1 in p['possible_signs'] for p in summary['pairs'].values())
            loaded[label] = mapper.tensor_points(data[label], paths, helper, dt, 1024, protocol['force_floor_N'])
            mapping[label] = mapper.map_points(loaded[label], event_streams[label], protocol['matching'])
            local[label+'_complete_mapping'] = mapping[label]['status'] == 'MAPPED'; totals[label] += len(loaded[label])
            local[label+'_known_robot_roles'] = all(m['role'] in ('body', 'white', 'head') for m in mapping[label]['matches'])
        for label in ('left', 'right'):
            sensor_path = views[label]['sensor_paths'][0]
            forward = summaries[label]['pairs'][target]['matrix_force_N']
            reverse = summaries['source']['pairs'][sensor_path]['matrix_force_N']
            local[label+'_selected_source_reciprocal'] = helper.close(forward, -np.asarray(reverse),
                contact['contact_reporting']['reciprocal_absolute_tolerance_N'], contact['contact_reporting']['reciprocal_relative_tolerance'])
            local[label+'_force_readback'] = abs(sum(p['normal_magnitude_N'] for p in summaries[label]['pairs'].values())-row['normal_force_per_pad_N'][label]) <= 1e-7
            online_points = row['point_ownership'][label]; ordered = sorted(loaded[label], key=lambda p: p['row'])
            local[label+'_all_online_points'] = len(online_points) == len(ordered)
            by_row = {m['tensor_row']: m for m in mapping[label]['matches']}
            for tensor, online in zip(ordered, online_points):
                rawrow = tensor['row']; pose = row['finger_poses_world_wxyz'][label]
                qualifier = helper.classify_point(tensor['position'], tensor['separation'], pose,
                    geometry['fingers'][label]['colliders'], contact, outward_world=-tensor['normal'],
                    flat_face_y_m=geometry['fingers'][label]['inner_plane_y_m'],
                    expected_grip_normal_finger=[0, -1 if label == 'left' else 1, 0])
                same = (np.array_equal(tensor['position'], online['point_world_m']) and tensor['separation'] == online['separation_m']
                    and float(data[label]['normal_forces_N'][rawrow].item()) == online['force_signed_N']
                    and qualifier['unique_body_geometry'] == online['unique_body']
                    and qualifier['uniquely_pad_compatible'] == online['lateral_qualified']
                    and spatial_match(tensor['position'], selection['candidate'], selection['supported_upper_surface_m']) == online['spatial_candidate_association'])
                local[label+'_original_qualification_reproduced'] = local.get(label+'_original_qualification_reproduced', True) and same
                if not online['unique_body'] or not online['lateral_qualified'] or not online['spatial_candidate_association']:
                    identity = attribution(by_row.get(rawrow), mapping['source']['matches'], target, tensor['partner'],
                                           qualifier, contact['geometry']['white_extra_clearance_m'])
                    identity.update(step=step, side=label, tensor_row=rawrow, raw_index=int(data[label]['normal_indices'][rawrow]),
                        private_partner=tensor['partner'], force_signed_N=online['force_signed_N'], point_world_m=online['point_world_m'],
                        private_partner_layer=layers.get(tensor['partner']),
                        partner_scope='SELECTED_SOURCE' if tensor['partner'] == target else 'UNSELECTED_PARTNER',
                        original_point=online, independently_recomputed=qualifier)
                    identity['finite_surface_only_failure'] &= online['spatial_candidate_association']
                    match = by_row.get(rawrow)
                    reciprocal = next((m for m in mapping['source']['matches'] if match and m['event'] == match['event']), None)
                    if reciprocal:
                        source_point = next(p for p in loaded['source'] if p['row'] == reciprocal['tensor_row'])
                        source_qualifier = helper.classify_point(source_point['position'], source_point['separation'], pose,
                            geometry['fingers'][label]['colliders'], contact, outward_world=source_point['normal'],
                            flat_face_y_m=geometry['fingers'][label]['inner_plane_y_m'],
                            expected_grip_normal_finger=[0, -1 if label == 'left' else 1, 0])
                        identity['reciprocal_source_point'] = {'tensor_row': source_point['row'],
                            'point_world_m': np.asarray(source_point['position']).tolist(), 'recomputed': source_qualifier}
                        identity['finite_surface_only_failure'] &= bool(finite_body_extent(source_qualifier, identity['robot_role'],
                            contact['geometry']['white_extra_clearance_m']) and spatial_match(source_point['position'],
                                selection['candidate'], selection['supported_upper_surface_m']))
                    evidence.append(identity)
        forces = row['normal_force_per_pad_N']; original = row['stop_reasons']
        expected = set()
        for label in ('left', 'right'):
            if forces[label] > science['motion']['sampled_normal_force_abort_per_pad_N']: expected.add('sampled_force_abort_'+label)
            if any(not p['lateral_qualified'] for p in row['point_ownership'][label]): expected.add('unqualified_contact_'+label)
            if any(not p['spatial_candidate_association'] for p in row['point_ownership'][label]): expected.add('unassociated_contact_'+label)
        finger_indices = metadata['finger_joint_indices']
        if np.max(abs(np.asarray(row['qdot'])[finger_indices])) > .002: expected.add('finger_actual_speed')
        if np.max(abs(np.asarray(row['q'])[finger_indices]-np.asarray(metadata['initial_joint_positions'])[finger_indices])) > .004+2e-6: expected.add('finger_actual_travel')
        post = np.asarray(row['tcp_pose_table_wxyz']); command = np.asarray(row['tcp_target_table_wxyz'])
        position_error = np.linalg.norm(post[:3]-command[:3]); angle_error = helper.angle_between(post[3:], command[3:])
        speed = np.linalg.norm(post[:3]-np.asarray(previous['tcp_pose_table_wxyz'])[:3])/dt
        if speed > {'approach': .030, 'final_approach': .003, 'close': .003}.get(row['phase'], 0): expected.add('TCP_actual_speed')
        if row['phase'] in ('final_approach', 'close') and (position_error > .0005 or angle_error > np.deg2rad(1)): expected.add('TCP_tracking')
        if row['phase'] in ('approach', 'final_approach') and max(forces.values()) > 1e-6: expected.add('unexpected_early_contact')
        local['original_guard_reasons_preserved'] = expected.issubset(original)
        triggers = []
        if original: triggers.append('old_guard_abort')
        if max(forces.values()) >= protocol['sampled_force_stop_N']: triggers.append('diagnostic_force_cap')
        if close_steps >= protocol['maximum_close_steps']: triggers.append('diagnostic_close_step_cap')
        if step >= protocol['maximum_physics_steps']: triggers.append('diagnostic_total_step_cap')
        if triggers:
            if stop_trigger is None: stop_trigger = {'step': step, 'all_reasons': triggers, 'original': original}
            local['first_stop_is_final'] = step == steps[-1] and stop_trigger['step'] == step
        local['close_step_bound'] = close_steps <= protocol['maximum_close_steps']
        local['finite_motion'] = bool(np.isfinite(row['q']).all() and np.isfinite(row['qdot']).all())
        local['continuous_clock'] = abs(row['time_s']-(public[step-1]['time_s'] if step > 1 else inventory['measurement_time_s'])-dt) <= 1e-7
        frames.append({'step': step, 'phase': row['phase'], 'checks': local, 'mapping': mapping,
                       'original_guard_reasons': original, 'forces_N': forces})
        previous = row
    termination = metadata['diagnostic_termination']
    checks['termination_record'] = (stop_trigger is not None and termination == marker['diagnostic_termination']
        and termination['step'] == steps[-1] and termination['original_guard_reasons'] == sorted(set(stop_trigger['original']))
        and set(termination['diagnostic_stop_reasons']) == set(stop_trigger['all_reasons'])-{'old_guard_abort'}
        and termination['kind'] == stop_trigger['all_reasons'][0])
    checks['close_step_record'] = metadata['closing_steps'] == close_steps
    checks['all_frames_reviewed'] = len(frames) == len(steps) and all(all(f['checks'].values()) for f in frames)
    checks['terminal_source_speed'] = bool(np.max(np.linalg.norm(states[:, 7:10], axis=1)) <= .02 and np.max(np.linalg.norm(states[:, 10:13], axis=1)) <= .2)
    complete = all(checks.values())
    status = ('CURRENT_FAILURE_IDENTIFIED' if evidence and complete and all(e['status'] == 'IDENTIFIED_CURRENT_POINT' for e in evidence)
              else 'NOT_REPRODUCED' if not evidence and complete else 'UNKNOWN')
    return mapper.json_native({'observation_complete': complete, 'proceed_gate_passed': False,
        'status': status, 'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
        'steps': len(steps), 'close_steps': close_steps, 'termination': termination, 'loaded_observations': totals,
        'current_bad_points': evidence, 'comparison_to_1809': comparison, 'frames': frames,
        'original_guard_outcome': {'passed': not termination['original_guard_reasons'], 'reasons': termination['original_guard_reasons']},
        'old1809_reinterpreted': False, 'grasp_retry_authorized': False, 'wall_seconds': time.monotonic()-started,
        'scope': 'Private current-run attribution only. No source identity, native role or callback data enters task policy.'})


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required for captured-data audit')
    args.output.mkdir(parents=True, exist_ok=True)
    try: report = audit(args.input)
    except Exception as error:
        report = {'observation_complete': False, 'proceed_gate_passed': False, 'status': 'UNKNOWN',
                  'error': str(error), 'grasp_retry_authorized': False, 'old1809_reinterpreted': False}
    (args.output/'evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

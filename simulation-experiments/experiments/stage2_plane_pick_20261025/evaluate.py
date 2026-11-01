"""Independent native pick audit with explicitly retired finite-surface predicates."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RETIRED = ('all_loaded_points_body_flat_lateral', 'all_reciprocal_loaded_points_body_flat_lateral')


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_partner_category(partner, target, fingers, source_ids):
    if partner in fingers: return 'FINGER'
    if '/Robot/' in partner: return 'FORBIDDEN_OTHER_ROBOT'
    if partner in source_ids and partner != target: return 'OTHER_LEGO_INTERFACE'
    return 'UNKNOWN'


def nominal_gap(state, inner, rotation):
    axis = rotation(state['tcp_pose_world_wxyz'][3:])[:, 1]
    points = {s: np.asarray(state['finger_poses_world_wxyz'][s][:3])+
        rotation(state['finger_poses_world_wxyz'][s][3:])@np.array([0., inner[s], 0.]) for s in ('left', 'right')}
    return float((points['left']-points['right'])@axis)


def numeric_cad(finger, side):
    return {'inner_plane_y_m': finger['inner_plane_y_m'], 'expected_grip_normal_finger': [0, -1 if side == 'left' else 1, 0],
        **{kind+'_surfaces': [{'vertices_finger_m': c['points_finger_m'],
            'triangle_indices': np.asarray(c['triangle_indices'], int).reshape(-1, 3).tolist()}
            for c in finger['colliders'] if c['enabled'] and c['role'] == kind] for kind in ('white', 'head')}}


class ContactAudit:
    def __init__(self, folder, plan, science, legacy, mapper, screen, spatial, privacy):
        self.folder, self.plan, self.science = folder, plan, science
        self.legacy, self.mapper, self.screen, self.spatial = legacy, mapper, screen, spatial
        self.privacy = privacy; self.raw_identities = {}
        self.original = legacy.contact_frame
        self.helper = mapper.load_helpers()
        self.meta = read(folder/'capture_metadata.json')
        self.native = read(folder/self.meta['native_observer_metadata'])
        index_path = folder/self.meta['native_contact_index']
        self.index = iter(legacy.rows(index_path)) if index_path.exists() else iter(())
        self.ids = set(read(folder/self.meta['truth_inventory'])['ids'])
        self.selection = read(folder/'online/selection.json')
        self.old_failures, self.failures, self.labels, self.interfaces = Counter(), Counter(), Counter(), Counter()
        self.frames = 0; self.previous = self.meta['initial_proprioception']; self.lift_z = None
        self.positive = 0; self.confirmation = None; self.endpoint_count = 0; self.samples = []; self.interface_peak = 0.

    def independently_screen(self, point, side, outward, row, geometry, protocol, lift_delta):
        helper = self.helper; pose = row['finger_poses_world_wxyz'][side]
        cad = numeric_cad(geometry['fingers'][side], side)
        associated = self.spatial(point['position'], self.selection['candidate'], self.selection['supported_upper_surface_m']+lift_delta)
        result = self.screen(point['position'], point['separation'], outward, pose, cad, associated)
        local = helper.rotation(pose[3:]).T@(np.asarray(point['position'])-pose[:3])
        normal = helper.rotation(pose[3:]).T@np.asarray(outward); normal /= np.linalg.norm(normal)
        tolerance = abs(point['separation'])+protocol['geometry']['pad_distance_allowance_m']
        flat = float(abs(local[1]-cad['inner_plane_y_m'])); dot = float(normal@cad['expected_grip_normal_finger'])
        distances = {kind: min(helper.surface_distance(local, c['points_finger_m'], c['triangle_indices'])
            for c in geometry['fingers'][side]['colliders'] if c['enabled'] and c['role'] == kind) for kind in ('white', 'head')}
        expected = bool(flat <= tolerance and dot >= .9 and associated
            and min(distances.values()) > tolerance+protocol['geometry']['white_extra_clearance_m'])
        evidence = result['evidence']
        valid = (result['compatible'] == expected and result['body_ownership_established'] is False and result['pick_permission'] is False
            and all(abs(a-b) <= 1e-10 for a, b in [(evidence['flat_plane_distance_m'], flat),
                (evidence['tolerance_m'], tolerance), (evidence['outward_dot_grip_normal'], dot),
                (evidence['white_distance_m'], distances['white']), (evidence['head_distance_m'], distances['head'])]))
        return result, expected, valid

    def __call__(self, folder, row, gt, observer, geometry, protocol, target):
        checks, detail, data, summaries = self.original(folder, row, gt, observer, geometry, protocol, target)
        for name in RETIRED:
            if name in checks:
                self.old_failures[name] += int(not checks.pop(name))
        self.frames += 1; helper = self.legacy
        checks['online_native_identity_quarantine'] = self.privacy(row)
        index = next(self.index, None)
        checks['native_index_same_step'] = (index is not None and index['step'] == row['step'] and index['time_s'] == row['time_s'])
        if not checks['native_index_same_step']: raise ValueError('Missing or stale private native event index')
        event = read(folder/index['native_events_file'])
        checks['native_callback_complete'] = (event['complete'] is True and not event['errors'] and event['step'] == row['step']
            and event['time_after_s'] == row['time_s'] and abs(event['time_before_s']+row['physics_dt_s']-row['time_s']) <= 1e-7
            and event['dt_s'] == row['physics_dt_s'] and event['out_of_window_callbacks_total'] == 0)
        for callback in event['callbacks']:
            for header in callback['headers']:
                checks['native_stage_id'] = checks.get('native_stage_id', True) and header['stage_id'] == self.native['stage_id']
                if not header['points']: continue
                for field in ('actor0', 'actor1', 'collider0', 'collider1'):
                    path, identity = header[field], header['raw_'+field]
                    valid = (isinstance(identity, int) and 0 <= identity < 2**64
                        and self.raw_identities.get(path, identity) == identity
                        and all(value != identity or key == path for key, value in self.raw_identities.items()))
                    checks['native_raw_ID_consistency'] = checks.get('native_raw_ID_consistency', True) and valid
                    self.raw_identities[path] = identity
        views = observer['resolved_views']; roles = self.native['role_paths']
        events = self.mapper.event_points(event, views, roles, self.plan['force_floor_N'], checks)
        source_file = helper.contact_file(gt['contacts']['source'])
        with np.load(folder/source_file, allow_pickle=False) as raw:
            data['source'] = {k: raw[k].copy() for k in raw.files}
        loaded, mapped = {}, {}
        for label, view in views.items():
            loaded[label] = self.mapper.tensor_points(data[label], helper.filter_paths(view), self.helper,
                row['physics_dt_s'], 1024, self.plan['force_floor_N'])
            mapped[label] = self.mapper.map_points(loaded[label], events[label], self.plan['native_mapping_evidence']['matching'])
            checks[label+'_fresh_complete_native_bijection'] = mapped[label]['status'] == 'MAPPED'
        source_events = {tuple(m['event']) for m in mapped['source']['matches']}
        finger_events = {tuple(m['event']): side for side in ('left', 'right') for m in mapped[side]['matches']}
        fingers = {f['body_path']: side for side, f in geometry['fingers'].items()}
        if row['phase'] == 'lift' and self.lift_z is None: self.lift_z = self.previous['tcp_pose_table_wxyz'][2]
        lift_delta = 0. if self.lift_z is None else row['tcp_pose_table_wxyz'][2]-self.lift_z
        for label in ('left', 'right', 'source'):
            by_row = {m['tensor_row']: m for m in mapped[label]['matches']}
            ordered = sorted(loaded[label], key=lambda p: p['row'])
            online = row['point_ownership'][label] if label != 'source' else None
            if online is not None: checks[label+'_all_online_points'] = len(online) == len(ordered)
            for ordinal, point in enumerate(ordered):
                match = by_row.get(point['row']); key = tuple(match['event']) if match else None
                if label == 'source':
                    category = source_partner_category(point['partner'], target, fingers, self.ids)
                    if category != 'FINGER':
                        self.interfaces[category] += 1
                        self.interface_peak = max(self.interface_peak, abs(float(data['source']['normal_forces_N'][point['row']].item())))
                        checks['source_other_partner_is_LEGO'] = checks.get('source_other_partner_is_LEGO', True) and category == 'OTHER_LEGO_INTERFACE'
                        continue  # Not a robot surface; no BODY or grip-plane claim is made.
                    side = fingers[point['partner']]; outward = point['normal']
                    paired = key in finger_events and finger_events[key] == side
                else:
                    side = label; outward = -point['normal']; paired = key in source_events and point['partner'] == target
                owned = bool(match and match['role'] == 'body' and paired)
                checks['all_finger_pairs_private_BODY_selected_source'] = checks.get('all_finger_pairs_private_BODY_selected_source', True) and owned
                result, compatible, valid = self.independently_screen(point, side, outward, row, geometry, protocol, lift_delta)
                checks['independent_plane_screen_evidence'] = checks.get('independent_plane_screen_evidence', True) and valid
                checks['all_finger_and_reciprocal_plane_compatible'] = checks.get('all_finger_and_reciprocal_plane_compatible', True) and compatible
                self.labels[(label, match['role'] if match else 'UNKNOWN')] += 1
                if online is not None:
                    recorded = online[ordinal]
                    checks['online_plane_packet_matches_pure_function'] = checks.get('online_plane_packet_matches_pure_function', True) and result == recorded['plane_screen']
                if (not owned or not compatible or not valid) and len(self.samples) < 128:
                    self.samples.append({'step': row['step'], 'sensor': label, 'row': point['row'], 'partner': point['partner'],
                        'native_role': match['role'] if match else 'UNKNOWN', 'screen': result})
        self.closure(row, geometry, detail, checks)
        for name, passed in checks.items():
            if not passed: self.failures[name] += 1
        self.previous = row
        return checks, detail, data, summaries

    def closure(self, row, geometry, detail, checks):
        p, meta = self.plan, self.meta; endpoint = meta['endpoint_preflight']; scalar = row['finger_command_scalar_m']
        value = endpoint['endpoint_q_m']; tolerance = p['endpoint_command_tolerance_m']
        commanded = np.asarray(row['joint_commands'])[meta['finger_joint_indices']]
        float_allow = 2*np.finfo(np.float32).eps*max(float(abs(commanded).max()), abs(scalar), 1e-4)
        checks['symmetric_command_scalar'] = bool(np.max(abs(commanded-scalar)) <= float_allow)
        checks['endpoint_not_overclosed'] = scalar >= value-tolerance
        checks['nominal_command_gap_record'] = abs(row['nominal_commanded_pad_gap_m']-(endpoint['gap_intercept_m']+endpoint['gap_per_symmetric_q']*scalar)) <= 1e-10
        checks['actual_model_gap_readback'] = abs(row['actual_model_pad_gap_m']-nominal_gap(row, endpoint['inner_planes_finger_y_m'], self.helper.rotation)) <= 1e-10
        if row['phase'] == 'close' and abs(scalar-value) <= tolerance: self.endpoint_count += 1
        checks['endpoint_completed_command_counter'] = row['endpoint_settle_completed_commands'] == self.endpoint_count
        both = row['phase'] == 'close' and all(v >= p['grasp_confirmation_N'] for v in detail['peak_N'].values())
        self.positive = self.positive+1 if both else 0
        if self.positive >= p['grasp_confirmation_consecutive_steps'] and self.confirmation is None:
            self.confirmation = {'step': row['step'], 'command_q_m': float(commanded[0]), 'at_endpoint': abs(scalar-value) <= tolerance}
        if self.confirmation:
            checks['last_command_frozen_after_confirmation'] = bool(np.all(commanded == self.confirmation['command_q_m']))
        else:
            checks['no_lift_before_confirmation'] = row['phase'] not in ('lift', 'hold')
            checks['settle_budget_before_confirmation'] = self.endpoint_count <= p['endpoint_settle_steps']


def endpoint_checks(meta, plan, geometry, helper):
    record = meta['endpoint_preflight']; initial = meta['initial_proprioception']
    inner = {s: geometry['fingers'][s]['inner_plane_y_m'] for s in ('left', 'right')}
    gap = nominal_gap(initial, inner, helper.rotation)
    q = np.asarray(meta['initial_joint_positions'])[meta['finger_joint_indices']]
    axes = {s: np.asarray(record['fingers'][s]['opening_axis_hand']) for s in ('left', 'right')}
    intercept = gap-axes['left'][1]*q[0]+axes['right'][1]*q[1]
    gain = axes['left'][1]-axes['right'][1]
    derived = (plan['nominal_pad_gap_m']-intercept)/gain
    checks = {'actual_opening_axes': bool(np.max(abs(axes['left']-[0, 1, 0])) <= 1e-6 and np.max(abs(axes['right']-[0, -1, 0])) <= 1e-6),
        'endpoint_independent_gap_derivation': abs(derived-record['endpoint_q_m']) <= plan['endpoint_command_tolerance_m'],
        'endpoint_nominal_14mm': record['nominal_gap_m'] == plan['nominal_pad_gap_m'] and abs(derived-plan['expected_finger_endpoint_m']) <= plan['endpoint_derived_match_tolerance_m'],
        'endpoint_intercept_readback': abs(intercept-record['gap_intercept_m']) <= 1e-10 and abs(gain-record['gap_per_symmetric_q']) <= 1e-12,
        'initial_actual_gap_readback': abs(gap-record['initial_actual_gap_m']) <= 1e-10 and inner == record['inner_planes_finger_y_m']}
    for side, i in zip(('left', 'right'), meta['finger_joint_indices']):
        saved = record['fingers'][side]; bounds = meta['joint_limits'][i]
        checks[side+'_endpoint_joint_and_travel'] = (saved['joint'] == 'fr3_finger_joint'+str(1 if side == 'left' else 2)
            and saved['limits_m'] == bounds and bounds[0] <= derived <= bounds[1]
            and 0 <= np.mean(q)-derived <= .004002 and abs(saved['endpoint_q_m']-derived) <= plan['endpoint_command_tolerance_m'])
    return checks


def audit(folder, started):
    folder = Path(folder); plan = read(HERE/'protocol.json'); science = read(HERE/'source_science.json')
    old_dir = ROOT/'experiments/stage2_exploratory_20261025/evaluation'
    sys.path[:0] = [str(old_dir), str(ROOT)]
    legacy = load('immutable_full_pick_audit', old_dir/'evaluate.py')
    mapper = load('immutable_native_mapping', ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py')
    screen = load('immutable_plane_screen', ROOT/'experiments/stage2_contact_screen_20261025/screen.py')
    closing = load('immutable_spatial_rule', ROOT/'experiments/stage2_closing_diagnostic_20261025/evaluate.py')
    spatial = closing.spatial_match
    old_protocol = read(old_dir/'protocol.json'); meta = read(folder/'capture_metadata.json')
    marker = read(folder/'plane_pick_complete.json'); supervisor = read(folder/'supervisor.json')
    remaining = min(plan['audit_limit_seconds'], supervisor['remaining_audit_seconds'],
        plan['maximum_active_seconds']-supervisor['capture_wall_seconds'],
        plan['aggregate_case_ceiling_seconds']-plan['prior_case_seconds']-supervisor['capture_wall_seconds'])
    if remaining <= 1: raise TimeoutError('No independent audit budget remains')
    deadline = started+remaining-1
    checks = {'execution_authorized': plan['execution_authorized'] is True,
        'source_science_pin': sha(HERE/'source_science.json') == plan['source_science_sha256'],
        'current_policy_pin': meta['contact_policy_protocol_sha256'] == sha(HERE/'protocol.json'),
        'source_science_record': meta['source_science_sha256'] == meta['protocol_sha256'] == plan['source_science_sha256'],
        'only_I_pick': meta['case'] == marker['case'] == 'I' and meta['mode'] == marker['mode'] == 'pick',
        'capture_completed': marker['capture_completed'] is True and supervisor['capture_completed'] is True and not (folder/'failure.json').exists(),
        'retained_budget_readback': supervisor['prior_case_seconds'] == plan['prior_case_seconds'] and supervisor['maximum_active_seconds'] == plan['maximum_active_seconds']}
    proof = {}
    for group in ('control_evidence', 'diagnostic_evidence', 'screen_evidence'):
        proof[group] = {}
        for key, item in plan[group].items():
            if isinstance(item, dict) and 'path' in item and 'sha256' in item:
                checks[group+'_'+key+'_pin'] = sha(item['path']) == item['sha256']; proof[group][key] = read(item['path'])
    prior = plan['prior_supervisor']; checks['latest_clock_pin'] = sha(prior['path']) == prior['sha256']
    checks['latest_clock_value'] = read(prior['path'])['cumulative_case_seconds'] == plan['prior_case_seconds']
    checks['screen_version_pin'] = sha(ROOT/'experiments/stage2_contact_screen_20261025/screen.py') == plan['screen_evidence']['screen_sha256']
    mapping = plan['native_mapping_evidence']
    checks['native_observer_pin'] = sha(ROOT/'experiments/stage2_collider_probe_20261025/native_observer.py') == mapping['observer_sha256']
    checks['native_mapper_pin'] = sha(ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py') == mapping['mapper_sha256']
    mp = ROOT/'experiments/stage2_collider_probe_20261025/protocol.json'
    checks['native_mapping_protocol_pin'] = sha(mp) == mapping['mapper_protocol_sha256'] and read(mp)['matching'] == mapping['matching']
    manifest = read(folder.parent/'manifest.json')
    checks['immutable_snapshot'] = all(sha(folder.parent/p) == digest for p, digest in manifest['sha256'].items())
    for name, digest in old_protocol['inputs_sha256'].items():
        checks['historical_input_'+name] = sha(old_dir.parent/'inputs'/name) == digest
    for name, digest in old_protocol['helpers_sha256'].items():
        checks['historical_helper_'+name] = sha(old_dir/name) == digest
    observer = read(folder/meta['observer_metadata']); control = proof['control_evidence']; diagnostic = proof['diagnostic_evidence']
    checks['matched_3600_control_passed'] = control['audit']['proceed_gate_passed'] is True and control['audit']['stationary_guard_passed'] is True and control['metadata']['steps_executed'] == 3600 and control['supervisor']['proceed_gate_passed'] is True
    for name, packet in (('control', control), ('diagnostic', diagnostic)):
        previous = packet['metadata']; old_observer = packet['observer_metadata']
        checks[name+'_physical_q_science_reporting_bridge'] = (previous['settings_initial'] == meta['settings_initial']
            and previous['initial_joint_positions'] == meta['initial_joint_positions']
            and previous['protocol_sha256'] == plan['source_science_sha256']
            and old_observer['resolved_views'] == observer['resolved_views']
            and old_observer['tensor_api_sha256'] == observer['tensor_api_sha256']
            and old_observer['observation_setting']['after'] is observer['observation_setting']['after'] is False
            and old_observer['normal_and_friction_capacity_per_view'] == observer['normal_and_friction_capacity_per_view'])
    checks['counterfactual_not_physical_evidence'] = proof['screen_evidence']['audit']['evaluation_complete'] is True and proof['screen_evidence']['audit']['counterfactual_only'] is True and proof['screen_evidence']['audit']['policy_installed'] is False
    checks['prior_current_diagnostic_not_grasp'] = diagnostic['audit']['observation_complete'] is True and diagnostic['audit']['proceed_gate_passed'] is False and diagnostic['audit']['original_guard_outcome']['passed'] is False
    bridge = read(folder/meta['control_bridge_file']); checks['startup_bridge_record'] = bridge['passed'] is True and all(bridge['checks'].values())
    original_provenance = legacy.provenance
    legacy.provenance = lambda args, p, s, m: {'historical_'+k: v for k, v in original_provenance(args, p, s, m).items()}
    adapter = ContactAudit(folder, plan, science, legacy, mapper, screen.screen_contact, spatial, closing.private_free)
    legacy.contact_frame = adapter
    args = SimpleNamespace(input=folder, case='I', mode='pick', deadline=deadline)
    result = legacy.audit(args, old_protocol, science, deadline)
    checks.update(result['checks'])
    geometry = read(folder/meta['tool_geometry_file']); checks.update(endpoint_checks(meta, plan, geometry, adapter.helper))
    native = adapter.native
    checks['private_native_role_inventory'] = native['role_paths'] == {c['path']: {'side': side, 'role': c['role']}
        for side, finger in geometry['fingers'].items() for c in finger['colliders'] if c['enabled']}
    checks['private_native_actor_inventory'] = native['actor_sides'] == {f['body_path']: side for side, f in geometry['fingers'].items()}
    checks['private_native_capacity'] = native['maximum_points_per_callback'] == 1024
    checks['private_native_API_pin'] = any(e['sha256'] == native['api_sha256'] for e in read(mp)['source_api_evidence'])
    checks['all_private_native_steps_consumed'] = next(adapter.index, None) is None and adapter.frames == result['steps']
    recorded = meta['grasp_confirmation']
    checks['confirmation_record'] = (recorded is None and adapter.confirmation is None or recorded is not None and adapter.confirmation is not None
        and all(recorded[k] == v for k, v in adapter.confirmation.items()))
    if recorded is not None:
        checks['last_actual_target_vector_record'] = recorded['commanded_finger_q_m'] == [recorded['command_q_m']]*2
    checks['endpoint_completed_commands_record'] = meta['endpoint_settle_completed_commands'] == adapter.endpoint_count
    checks['current_complete_marker_matches'] = meta['steps_executed'] == marker['steps_executed'] == result['steps'] and meta['controller_status'] == marker['controller_status']
    checks['current_case_wall'] = supervisor['capture_wall_seconds']+time.monotonic()-started <= plan['maximum_active_seconds']
    checks['aggregate_wall'] = plan['prior_case_seconds']+supervisor['capture_wall_seconds']+time.monotonic()-started <= plan['aggregate_case_ceiling_seconds']
    passed = all(checks.values())
    result.update(physics_extraction_passed=passed, proceed_gate_passed=passed, checks=checks,
        failed_checks=[k for k, v in checks.items() if not v], contact_policy='UNVERIFIED_GRIP_PLANE_COMPATIBILITY_ONLY',
        retired_reference_check_names=list(RETIRED), retired_reference_failure_counts=dict(adapter.old_failures),
        private_native_failures=dict(adapter.failures), private_robot_labels=[{'sensor': a, 'role': b, 'count': n} for (a, b), n in adapter.labels.items()],
        source_nonfinger_interface_counts=dict(adapter.interfaces), source_nonfinger_peak_N=adapter.interface_peak,
        private_contact_failure_samples=adapter.samples, endpoint_mapping=meta['endpoint_preflight'],
        force_confirmation=meta['grasp_confirmation'], endpoint_settle_completed_commands=adapter.endpoint_count,
        source_science_sha256=plan['source_science_sha256'], contact_policy_protocol_sha256=sha(HERE/'protocol.json'),
        old_failures_reinterpreted=False, online_held_identity='UNKNOWN', transfer_authorized=False,
        H_authorized=False, automatic_retry=False, wall_seconds=time.monotonic()-started)
    return mapper.json_native(result)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False); parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    args.output.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    try: result = audit(args.input, started)
    except Exception as error:
        result = {'physics_extraction_passed': False, 'proceed_gate_passed': False, 'error': str(error),
                  'transfer_authorized': False, 'H_authorized': False, 'automatic_retry': False}
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

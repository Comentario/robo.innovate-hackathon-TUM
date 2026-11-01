"""BODY-only contact-margin sensitivity; all retention checks remain authoritative."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import copy
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def fixture_bottom(state, size, rotation):
    corners = np.array(list(itertools.product(*[[-size[0]/2, size[0]/2],
        [-size[1]/2, size[1]/2], [0., size[2]]])))
    return float((corners@rotation(state[3:7]).T+state[:3])[:, 2].min())


def holding_error(tcp, state, reference, helper):
    position, orient = helper.relative_pose(tcp, state)
    return (float(np.linalg.norm(position-reference[0])),
        float(np.arccos(np.clip((np.trace(reference[1].T@orient)-1)/2, -1, 1))))


def force_confirmation_record(confirmation, row, finger_indices):
    """Reconstruct the full record from the independently detected raw-force step."""
    if confirmation is None: return None
    if row['step'] != confirmation['step']: raise ValueError('Force record requires its admission-step commands')
    commands = np.asarray(row['joint_commands'])[finger_indices]
    if commands.shape != (2,) or not np.isfinite(commands).all(): raise ValueError('Invalid finger command vector')
    return {'step': confirmation['step'], 'command_q_m': confirmation['command_q_m'],
        'at_endpoint': confirmation['at_endpoint'], 'commanded_finger_q_m': commands.tolist()}


class PositionAdmission:
    """Never advance on force; all samples derive from raw loads and serialized commands."""
    def __init__(self, plan, meta, parent, helper):
        self.plan, self.meta, self.parent, self.helper = plan, meta, parent, helper
        self.positive = self.endpoint_count = self.position_count = 0
        self.confirmation = self.position_candidate = self.admission = None
        self.window = []; self.force_record = None

    def closure(self, row, geometry, detail, checks):
        plan, meta = self.plan, self.meta
        commands = np.asarray(row['joint_commands'])[meta['finger_joint_indices']]
        scalar = row['finger_command_scalar_m']; endpoint = meta['endpoint_preflight']; value = endpoint['endpoint_q_m']
        at_endpoint = row['phase'] == 'close' and abs(scalar-value) <= plan['endpoint_command_tolerance_m']
        self.endpoint_count += int(at_endpoint)
        allowance = 2*np.finfo(np.float32).eps*max(float(abs(commands).max()), abs(scalar), 1e-4)
        checks['symmetric_command_scalar'] = bool(np.max(abs(commands-scalar)) <= allowance)
        checks['endpoint_not_overclosed'] = scalar >= value-plan['endpoint_command_tolerance_m']
        checks['nominal_command_gap_record'] = abs(row['nominal_commanded_pad_gap_m']-(endpoint['gap_intercept_m']+endpoint['gap_per_symmetric_q']*scalar)) <= 1e-10
        checks['actual_model_gap_readback'] = abs(row['actual_model_pad_gap_m']-self.parent.parent.nominal_gap(row, endpoint['inner_planes_finger_y_m'], self.helper.rotation)) <= 1e-10
        checks['endpoint_completed_command_counter'] = row['endpoint_settle_completed_commands'] == self.endpoint_count
        both = row['phase'] == 'close' and not row['stop_reasons'] and all(v >= plan['grasp_confirmation_N'] for v in detail['peak_N'].values())
        self.positive = self.positive+1 if both else 0
        if self.positive >= plan['grasp_confirmation_consecutive_steps'] and self.confirmation is None:
            self.confirmation = {'step': row['step'], 'command_q_m': float(commands[0]), 'at_endpoint': at_endpoint}
            self.force_record = force_confirmation_record(self.confirmation, row, meta['finger_joint_indices'])
        sample, errors, actual_gap, commanded_gap = self.parent.raw_position_sample(row, meta, plan, detail['peak_N'])
        self.position_count = self.position_count+1 if sample else 0
        checks['position_sample_matches_raw'] = (row['position_candidate_sample'] is sample
            and row['position_candidate_consecutive_steps'] == self.position_count
            and np.max(abs(np.asarray(row['finger_tracking_errors_m'])-errors)) <= 1e-12
            and abs(row['actual_joint_gap_m']-actual_gap) <= 1e-12 and abs(row['commanded_joint_gap_m']-commanded_gap) <= 1e-12)
        if at_endpoint:
            self.window = (self.window+[{'step': row['step'], 'endpoint_settle_completed_commands': self.endpoint_count,
                'sample_passed': sample, 'forces_N': row['normal_force_per_pad_N'],
                'actual_finger_q_m': np.asarray(row['q'])[meta['finger_joint_indices']].tolist(),
                'commanded_finger_q_m': commands.tolist(), 'finger_tracking_errors_m': errors.tolist(),
                'actual_joint_gap_m': actual_gap, 'commanded_joint_gap_m': commanded_gap}])[-plan['candidate_consecutive_steps']:]
        else: self.window = []
        if (self.admission is None and not row['stop_reasons'] and self.endpoint_count == plan['endpoint_settle_steps']
                and self.position_count >= plan['candidate_consecutive_steps']):
            self.position_candidate = {'status': 'GRASP_CANDIDATE', 'step': row['step'], 'command_q_m': float(commands[0]),
                'commanded_finger_q_m': commands.tolist(), 'consecutive_steps': self.position_count,
                'endpoint_settle_completed_commands': self.endpoint_count, 'window': list(self.window)}
            self.admission = {'kind': 'position_candidate', 'step': row['step'], 'command_q_m': float(commands[0])}
        checks['admission_before_lift'] = row['phase'] not in ('lift', 'hold') or self.admission is not None
        checks['no_extra_endpoint_wait'] = self.endpoint_count <= plan['endpoint_settle_steps']
        if self.admission: checks['last_command_targets_held_after_admission'] = bool(np.all(commands == self.admission['command_q_m']))


def raw_arrays(path):
    with np.load(path, allow_pickle=False) as raw:
        return {key: raw[key].copy() for key in raw.files}


def private_free(value):
    if isinstance(value, dict):
        return all(not any(word in key.lower() for word in ('native', 'actor', 'collider', 'partner', 'source_id', 'bound_id'))
            and private_free(item) for key, item in value.items())
    if isinstance(value, list): return all(private_free(item) for item in value)
    return not isinstance(value, str) or not value.startswith('/World/')


def same_geometry(now, reference):
    if set(now['fingers']) != set(reference['fingers']): return False
    for side, finger in now['fingers'].items():
        a = {c['path']: c for c in finger['colliders']}
        b = {c['path']: c for c in reference['fingers'][side]['colliders']}
        if set(a) != set(b): return False
        for path, c in a.items():
            if set(c) != set(b[path]): return False
            for key, value in c.items():
                tolerance = 1e-9 if c['role'] == 'white' else 1e-8
                if key in ('points_finger_m', 'bounds_finger_m'):
                    if not np.allclose(value, b[path][key], atol=tolerance, rtol=0): return False
                elif value != b[path][key]: return False
    return True


def body_margin_geometry(now, reference, authoring, plan):
    """Normalize only the declared two BODY offset opinions/API fallbacks for comparison."""
    normalized = copy.deepcopy(now)
    target = float(np.float32(plan['body_contact_offset_m']))
    allowed_defaults = plan['allowed_unauthored_collision_defaults']
    allowed = set(allowed_defaults)
    if authoring['timing'] != 'pre_initialization' or authoring['paths'] != plan['expected_body_paths']: return False
    if authoring['target_contact_offset_m'] != plan['body_contact_offset_m']: return False
    if set(authoring['schema_attribute_names']) != allowed | {'physxCollision:contactOffset'}: return False
    if set(authoring['records']) != {'left', 'right'}: return False
    for side, path in plan['expected_body_paths'].items():
        records = [c for c in normalized['fingers'][side]['colliders'] if c['path'] == path]
        refs = [c for c in reference['fingers'][side]['colliders'] if c['path'] == path]
        if len(records) != 1 or len(refs) != 1: return False
        record, old, proof = records[0], refs[0], authoring['records'][side]
        if record['role'] != 'body' or proof['path'] != path or old['contact_offset_m'] is not None: return False
        expected_offset = {'usd_type': 'float', 'sdk_value': target}
        if proof['old_authored_offset'] is not None or proof['new_authored_offset'] != expected_offset: return False
        if abs(record['contact_offset_m']-target) > 1e-10: return False
        if proof['other_authored_attributes_unchanged'] is not True: return False
        if proof['other_authored_before_sha256'] != proof['other_authored_after_sha256']: return False
        added_schemas = set(proof['applied_schemas_after'])-set(proof['applied_schemas_before'])
        if not set(proof['applied_schemas_before']) <= set(proof['applied_schemas_after']) or added_schemas-set(['PhysxCollisionAPI']): return False
        defaults = proof['newly_exposed_unauthored_defaults']
        if not set(defaults) <= allowed or not set(defaults) <= set(authoring['schema_attribute_names']): return False
        if any(value != allowed_defaults[name] for name, value in defaults.items()): return False
        attributes = record['attributes']; original = old['attributes']
        if attributes.get('physxCollision:contactOffset') != {'usd_type': 'float', 'sdk_value': target}: return False
        for name, value in defaults.items():
            if name in original or attributes.get(name) != value: return False
        expected_new = {'physxCollision:contactOffset'} | set(defaults)
        if set(attributes)-set(original) != expected_new: return False
        record['attributes'] = {k: v for k, v in attributes.items() if k not in expected_new}
        record['contact_offset_m'] = old['contact_offset_m']
        if record['rest_offset_m'] != old['rest_offset_m']:
            if old['rest_offset_m'] is not None or 'physxCollision:restOffset' not in defaults or record['rest_offset_m'] != defaults['physxCollision:restOffset']['sdk_value']: return False
            record['rest_offset_m'] = old['rest_offset_m']
    return same_geometry(normalized, reference)


def runtime_margin_checks(record, baseline, plan):
    checks = {'mapping_unknown': record['mapping'] == 'UNKNOWN',
        'baseline_pin_record': record['baseline_readback_sha256'] == plan['baseline_readback']['sha256'],
        'view_inventory': set(record['views']) == set(baseline['views']) == {'left', 'right', 'coupon'}}
    target = float(np.float32(plan['body_contact_offset_m']))
    for label in ('left', 'right', 'coupon'):
        view, original = record['views'][label], baseline['views'][label]
        checks[label+'_binding'] = (view['requested_path'] == original['requested_path']
            and view['prim_paths'] == original['prim_paths'] and view['count'] == original['count'] == 1
            and view['max_shapes'] == original['max_shapes'] == (2 if label == 'coupon' else 5)
            and view['view_error'] is None and view['row_to_collider_mapping'] == 'UNKNOWN')
        for name in ('material_properties', 'contact_offsets', 'rest_offsets'):
            value, old = view['getters'][name], original['getters'][name]
            a, b = np.asarray(value['values'], float), np.asarray(old['values'], float)
            checks[label+'_'+name+'_schema'] = (value['status'] == 'AVAILABLE' and value['error'] is None
                and value['shape'] == old['shape'] and value['dtype'] == old['dtype'] == 'float32'
                and a.shape == b.shape == tuple(old['shape']) and bool(np.isfinite(a).all()))
            if not checks[label+'_'+name+'_schema']:
                checks[label+'_'+name+'_multiset'] = False
                continue
            if name == 'material_properties':
                same = sorted(map(tuple, a[0])) == sorted(map(tuple, b[0]))
            elif name == 'rest_offsets': same = sorted(a[0]) == sorted(b[0]) == [0.]*view['max_shapes']
            else:
                expected = sorted(b[0]) if label == 'coupon' else sorted([target]+b[0, 1:].tolist())
                same = bool(np.all(b == b[0, 0]) and np.allclose(sorted(a[0]), expected,
                    atol=plan['runtime_property_tolerance_m'], rtol=0))
            checks[label+'_'+name+'_multiset'] = bool(same)
    return checks


def canonical_margin(record):
    return {label: {'path': view['requested_path'], 'prim_paths': view['prim_paths'], 'count': view['count'],
        'max_shapes': view['max_shapes'], 'materials': sorted(map(tuple, view['getters']['material_properties']['values'][0])),
        'contact_offsets': sorted(view['getters']['contact_offsets']['values'][0]),
        'rest_offsets': sorted(view['getters']['rest_offsets']['values'][0])} for label, view in record['views'].items()}


def audit(folder, mode, predecessor, started):
    folder = Path(folder); plan = read(HERE/'protocol.json'); science = read(HERE/'source_science.json')
    old_dir = ROOT/'experiments/stage2_exploratory_20261025/evaluation'
    sys.path[:0] = [str(old_dir), str(ROOT)]
    legacy = load('free_retention_legacy', old_dir/'evaluate.py')
    mapper = load('free_retention_mapping', ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py')
    admission_module = load('free_retention_admission', ROOT/'experiments/stage2_position_candidate_20261025/evaluate.py')
    plane = admission_module.parent
    screen = load('free_retention_screen', ROOT/'experiments/stage2_contact_screen_20261025/screen.py')
    helper = mapper.load_helpers()
    contact_protocol = read(old_dir/'contact_protocol.json')
    meta = read(folder/'capture_metadata.json'); marker = read(folder/'fixture_complete.json')
    supervisor = read(folder/'supervisor.json')
    remaining = min(supervisor['remaining_audit_seconds'],
        plan['audit_limit_seconds'], plan['maximum_active_seconds']-supervisor['current_case_elapsed_seconds'],
        plan['aggregate_case_ceiling_seconds']-supervisor['prior_case_seconds']-supervisor['capture_wall_seconds'])
    if remaining <= 1: raise TimeoutError('No shared audit time remains')
    deadline = started+remaining-1
    checks = {'execution_authorized': plan['execution_authorized'] is True,
        'protocol_pin': meta['contact_policy_protocol_sha256'] == sha(HERE/'protocol.json'),
        'source_science_pin': meta['source_science_sha256'] == sha(HERE/'source_science.json') == plan['source_science_sha256'],
        'margin_protocol_pin': meta['margin_protocol_sha256'] == sha(HERE/'protocol.json'),
        'mode': meta['mode'] == marker['mode'] == mode,
        'capture_complete': marker['capture_completed'] is True and supervisor['capture_completed'] is True
            and not (folder/'failure.json').exists(),
        'known_fixture_only': meta['fixture_contact_association'] == 'Declared known fixture initialization; no perception claim',
        'retained_budget': supervisor['prior_case_seconds'] >= plan['prior_case_seconds']
            and plan['aggregate_case_ceiling_seconds'] == 2800}
    checks['position_only_policy'] = meta['lift_admission_policy'] == 'position_only_30_endpoint_commands'
    for path, digest in plan.get('input_sha256', {}).items(): checks['input_'+path] = sha(path) == digest
    for path, digest in plan['helper_pins'].items(): checks['helper_'+path] = sha(ROOT/path) == digest
    for name in ('parent_runner', 'readback_helper'):
        checks[name+'_pin'] = sha(plan[name]['path']) == plan[name]['sha256']
    prior = plan['prior_supervisor']
    checks['prior_clock_pin'] = sha(prior['path']) == prior['sha256']
    checks['prior_clock'] = read(prior['path'])['cumulative_case_seconds'] == plan['prior_case_seconds']
    baseline_meta = read(plan['baseline_metadata']['path'])
    baseline = {'initial_robot_properties': baseline_meta['settings_initial']['robot_properties']}
    baseline_geometry = read(plan['baseline_geometry']['path'])
    source_metadata = read(plan['source_metadata']['path'])
    for name in ('baseline_metadata', 'baseline_geometry', 'source_metadata'):
        checks[name+'_pin'] = sha(plan[name]['path']) == plan[name]['sha256']
    inventory = read(folder/meta['truth_inventory']); truthroot = folder/Path(meta['truth_inventory']).parent
    source_initial = raw_arrays(truthroot/inventory['body_states_file'])['states']
    edges = {v['id'] for v in inventory['initial_edges']}
    checks['source_inventory'] = (len(inventory['ids']) == len(set(inventory['ids'])) == 301
        and len(edges) == len(inventory['initial_edges']) == 930 and source_initial.shape == (301, 13))
    checks.update(legacy.settings_checks(meta, science, inventory, baseline, source_metadata['settings_initial']['cooked_hashes']))
    checks['non_margin_settings_equal_reference'] = meta['settings_initial'] == meta['settings_terminal'] == source_metadata['settings_initial']
    checks.update(legacy.cook_checks(read(folder/meta['cook_file']), meta['settings_initial']['cooked_hashes']))
    geometry = read(folder/meta['tool_geometry_file'])
    authoring = read(folder/meta['margin_authoring_file'])
    baseline_readback = read(plan['baseline_readback']['path'])
    checks['baseline_readback_pin'] = sha(plan['baseline_readback']['path']) == plan['baseline_readback']['sha256']
    proof = plan['baseline_readback_audit']; baseline_audit = read(proof['path'])
    checks['baseline_readback_validated'] = (sha(proof['path']) == proof['sha256'] and baseline_audit['diagnostic_complete'] is True
        and baseline_audit['runtime_arrays_valid'] is True and baseline_audit['readback_sha256'] == plan['baseline_readback']['sha256'])
    checks['collision_schema_pin'] = sha(plan['collision_schema']['path']) == plan['collision_schema']['sha256']
    checks['one_authored_BODY_margin_change'] = body_margin_geometry(geometry, baseline_geometry, authoring, plan)
    checks['terminal_geometry'] = same_geometry(read(folder/'geometry_terminal.json'), geometry)
    margin_initial = read(folder/meta['margin_readback_initial_file'])
    margin_terminal = read(folder/meta['margin_readback_terminal_file'])
    for phase, record in [('initial', margin_initial), ('terminal', margin_terminal)]:
        checks.update({phase+'_margin_'+k: v for k, v in runtime_margin_checks(record, baseline_readback, plan).items()})
    restoration = read(folder/meta['property_restoration_file'])
    old_eval_protocol = read(old_dir/'protocol.json')
    checks.update(legacy.restoration_checks(restoration, baseline, old_eval_protocol))
    checks.update(legacy.targeted_write_checks(restoration))
    fixture = read(folder/meta['fixture_initial_file']); coupon, pedestal = fixture['coupon'], fixture['pedestal']
    target = coupon['path']; support = pedestal['path']; state0 = np.asarray(coupon['initial_state_world'], float)
    checks['free_dynamic_coupon'] = (coupon['dynamic'] is True and coupon['disable_gravity'] is False
        and coupon['native_degree'] == 0 and coupon['solver_iterations'] == [32, 4] and target not in inventory['ids']
        and pedestal['passive'] is True and target != support)
    checks['coupon_properties'] = meta['coupon_properties_initial'] == meta['coupon_properties_terminal'] == coupon['properties']
    checks['initial_pose_finite'] = state0.shape == (13,) and bool(np.isfinite(state0).all())
    reference = read(plan['fixture_reference_metadata']['path'])['initial_proprioception']
    checks['fixture_reference_pin'] = sha(plan['fixture_reference_metadata']['path']) == plan['fixture_reference_metadata']['sha256']
    initial_tcp = meta['initial_proprioception']['tcp_pose_world_wxyz']; expected_tcp = reference['tcp_pose_world_wxyz']
    checks['reference_staging_pose'] = (np.linalg.norm(np.asarray(initial_tcp[:3])-expected_tcp[:3]) <= plan['fixture_max_initial_pose_error_m']
        and helper.angle_between(initial_tcp[3:], expected_tcp[3:]) <= plan['fixture_max_initial_angle_error_rad'])
    checks['authored_coupon_pose'] = (np.linalg.norm(state0[:3]-coupon['root_pose_world_wxyz'][:3]) <= plan['fixture_max_initial_pose_error_m']
        and helper.angle_between(state0[3:7], fixture['design']['coupon_pose'][3:]) <= plan['fixture_max_initial_angle_error_rad']
        and np.linalg.norm(state0[:3]-fixture['design']['coupon_pose'][:3]) <= plan['fixture_max_initial_pose_error_m']
        and coupon['body_size_m'] == plan['body_size_m'])
    checks['passive_support_design'] = (pedestal['size_m'][:2] == plan['post_size_xy_m']
        and abs(fixture_bottom(state0, coupon['body_size_m'], helper.rotation)-pedestal['bounds_world_m'][1][2]) <= plan['fixture_max_initial_pose_error_m'])
    checks['initial_overlap'] = all(abs(v-plan['nominal_body_side_overlap_m']) <= plan['fixture_nominal_band_tolerance_m']
        for v in fixture['actual_initial_body_side_overlap_m'].values()) and set(fixture['actual_initial_body_side_overlap_m']) == {'left', 'right'}
    checks.update(plane.endpoint_checks(meta, plan, geometry, helper))
    if mode == 'pick':
        proof = read(predecessor)
        checks['fresh_control_predecessor'] = (proof['mode'] == 'control' and proof['proceed_gate_passed'] is True
            and proof['protocol_sha256'] == sha(HERE/'protocol.json') and proof['fixture_initial'] == fixture
            and proof['settings_initial'] == meta['settings_initial']
            and proof['initial_joint_positions'] == meta['initial_joint_positions']
            and sha(Path(proof['capture_directory'])/'capture_metadata.json') == proof['capture_metadata_sha256'])
        checks['fresh_control_margin_model'] = (proof['margin_initial']['baseline_readback_sha256'] == margin_initial['baseline_readback_sha256']
            and canonical_margin(proof['margin_initial']) == canonical_margin(margin_initial) and proof['margin_authoring'] == authoring)
    observer = read(folder/meta['observer_metadata'])
    observer['resolved_views'].update(read(folder/meta['evaluation_observer_metadata'])['resolved_views'])
    views = observer['resolved_views']; native = read(folder/meta['native_observer_metadata'])
    resolved_support = set(helper.filter_paths(views['source'])) & ({support} | set(pedestal['collider_paths']))
    checks['support_filter_resolved'] = bool(resolved_support)
    checks['three_views'] = set(views) == {'left', 'right', 'source'} and views['source']['sensor_paths'] == [target]
    checks['complete_tensor_filters'] = all(v['sensor_count'] == 1 and v['max_contact_data_count'] == 1024
        and not v['missing_requested_filter_paths'] and not v['extra_resolved_filter_paths'] for v in views.values())
    if mode == 'pick': checks['fresh_control_observer'] = proof['observer_metadata'] == observer
    roles = {c['path']: {'side': side, 'role': c['role']} for side, finger in geometry['fingers'].items()
        for c in finger['colliders'] if c['enabled']}
    checks['native_role_inventory'] = native['role_paths'] == roles
    checks['native_actor_inventory'] = native['actor_sides'] == {f['body_path']: s for s, f in geometry['fingers'].items()}
    checks['native_buffer'] = native['maximum_points_per_callback'] == 1024
    mapping_protocol_path = ROOT/'experiments/stage2_collider_probe_20261025/protocol.json'
    checks['native_mapping_protocol_pin'] = sha(mapping_protocol_path) == plan['native_mapping_evidence']['mapper_protocol_sha256']
    checks['native_API_pin'] = any(e['sha256'] == native['api_sha256'] for e in read(mapping_protocol_path)['source_api_evidence'])
    truth = iter(legacy.rows(folder/meta['truth_trace'])); fixtures = iter(legacy.rows(folder/meta['fixture_trace']))
    native_index = iter(legacy.rows(folder/meta['native_contact_index']))
    adapter = PositionAdmission(plan, meta, admission_module, helper)
    previous = None; failures = Counter(); retired_reference = Counter(); loaded_counts = Counter(); support_observations = 0; peak = {'left': 0., 'right': 0.}
    reference = None; max_relative_m = max_relative_rad = max_source_m = max_source_rad = 0.
    hold_count = support_frames = 0; min_hold_clearance = None; first_lift = lift_origin = lift_final = None
    source_final = source_initial; last_state = state0; total = 0; raw_ids = {}; expected_confirmation = None
    for row in legacy.rows(folder/meta['online_trace']):
        legacy.check_time(deadline); total += 1
        gt, fr, ix = next(truth, None), next(fixtures, None), next(native_index, None)
        local = {'step_clock': row['step'] == total and all(v is not None and v['step'] == total
            and v['time_s'] == row['time_s'] for v in (gt, fr, ix)),
            'finite_robot': legacy.finite(row['q']) and legacy.finite(row['qdot']) and legacy.finite(row['joint_commands']),
            'no_capture_abort': not row['stop_reasons'],
            'phase': row['phase'] in (['control'] if mode == 'control' else ['close', 'lift', 'hold'])}
        local['online_identity_quarantine'] = private_free(row)
        if not local['step_clock']: raise ValueError('Missing/stale paired trace')
        source_final = raw_arrays(truthroot/gt['state_file'])['states']; state = np.asarray(fr['coupon_state_world'])
        local['source_graph'] = set(gt['edges']) == edges and len(gt['edges']) == 930 and not gt['break_events'] and not gt['nonfinite']
        local['finite_states'] = legacy.finite(state) and state.shape == (13,) and source_final.shape == source_initial.shape and legacy.finite(source_final)
        drift = float(np.max(np.linalg.norm(source_final[:, :3]-source_initial[:, :3], axis=1)))
        angle = float(max(helper.angle_between(a[3:7], b[3:7]) for a, b in zip(source_final, source_initial)))
        max_source_m = max(max_source_m, drift); max_source_rad = max(max_source_rad, angle)
        local['stationary_source'] = drift <= .002 and angle <= np.deg2rad(2)
        local['coupon_isolated'] = fr['native_degree'] == 0 and fr['isolated_coupon'] is True
        q, qd, command = map(np.asarray, (row['q'], row['qdot'], row['joint_commands']))
        fi, ai = meta['finger_joint_indices'], meta['arm_joint_indices']; limits = np.asarray(meta['joint_limits'])
        local['joint_limits'] = bool(np.all(q >= limits[:, 0]) and np.all(q <= limits[:, 1]))
        local['actual_joint_speeds'] = bool(max(abs(qd[fi])) <= .002 and max(abs(qd[ai])) <= 1.)
        local['finger_travel'] = bool(max(abs(q[fi]-np.asarray(meta['initial_joint_positions'])[fi])) <= .004002
            and max(abs(command[fi]-np.asarray(meta['initial_joint_positions'])[fi])) <= .004002)
        if previous:
            if mode == 'pick': local['phase_order'] = ['close', 'lift', 'hold'].index(row['phase']) >= ['close', 'lift', 'hold'].index(previous['phase'])
            local['continuous_clock'] = abs(row['time_s']-previous['time_s']-meta['dt_s']) <= 1e-7
            old = np.asarray(previous['joint_commands']); delta = command-old
            local['command_increments'] = bool(max(abs(delta[ai])) <= .005+1e-6 and max(abs(delta[fi])) <= .001*meta['dt_s']+2e-9)
            speed = np.linalg.norm(np.asarray(row['tcp_pose_world_wxyz'][:3])-previous['tcp_pose_world_wxyz'][:3])/meta['dt_s']
            local['TCP_speed'] = speed <= (.002 if row['phase'] in ('lift', 'hold') else .003)
        tcp, goal = row['tcp_pose_table_wxyz'], row['tcp_target_table_wxyz']
        local['TCP_tracking'] = np.linalg.norm(np.asarray(tcp[:3])-goal[:3]) <= (.002 if mode == 'control' else .0005) and helper.angle_between(tcp[3:], goal[3:]) <= np.deg2rad(2 if mode == 'control' else 1)
        if row['phase'] == 'lift' and first_lift is None:
            first_lift, lift_origin = total, np.asarray(previous['tcp_pose_world_wxyz'][:3])
        contact_checks, detail, data, summaries = legacy.contact_frame(folder, row, {'contacts': gt['contacts']}, observer,
            geometry, contact_protocol, target)
        for key in plane.RETIRED:
            if key in contact_checks: retired_reference[key] += int(not contact_checks.pop(key))
        local.update(contact_checks)
        data['source'] = raw_arrays(folder/legacy.contact_file(gt['contacts']['source']))
        event = read(folder/ix['native_events_file'])
        local['native_event'] = (event['complete'] is True and not event['errors'] and event['step'] == total
            and event['time_after_s'] == row['time_s'] and abs(event['time_before_s']+meta['dt_s']-row['time_s']) <= 1e-7
            and event['dt_s'] == meta['dt_s'] and event['out_of_window_callbacks_total'] == 0)
        for callback in event['callbacks']:
            for header in callback['headers']:
                local['native_stage'] = local.get('native_stage', True) and header['stage_id'] == native['stage_id']
                if not header['points']: continue
                for name in ('actor0', 'actor1', 'collider0', 'collider1'):
                    path, identity = header[name], header['raw_'+name]
                    local['native_ID_consistency'] = local.get('native_ID_consistency', True) and isinstance(identity, int) and raw_ids.get(path, identity) == identity and all(v != identity or p == path for p, v in raw_ids.items())
                    raw_ids[path] = identity
        events = mapper.event_points(event, views, roles, plan['force_floor_N'], local)
        points, mapped = {}, {}
        for label, view in views.items():
            points[label] = mapper.tensor_points(data[label], helper.filter_paths(view), helper, meta['dt_s'], 1024, plan['force_floor_N'])
            mapped[label] = mapper.map_points(points[label], events[label], plan['native_mapping_evidence']['matching'])
            local[label+'_bijection'] = mapped[label]['status'] == 'MAPPED'
            loaded_counts[label] += len(points[label])
        finger_events = {tuple(m['event']): s for s in ('left', 'right') for m in mapped[s]['matches']}
        source_events = {tuple(m['event']) for m in mapped['source']['matches']}
        finger_paths = {f['body_path']: s for s, f in geometry['fingers'].items()}
        support_load = 0.
        for label in ('left', 'right', 'source'):
            matches = {m['tensor_row']: m for m in mapped[label]['matches']}
            for point in points[label]:
                match = matches.get(point['row']); event_key = tuple(match['event']) if match else None
                if label == 'source' and point['partner'] in resolved_support:
                    support_observations += 1
                    support_load += abs(float(data[label]['normal_forces_N'][point['row']].item())); continue
                side = finger_paths.get(point['partner']) if label == 'source' else label
                pair_ok = (event_key in finger_events and finger_events[event_key] == side) if label == 'source' else (point['partner'] == target and event_key in source_events)
                local['BODY_coupon_pairs_only'] = local.get('BODY_coupon_pairs_only', True) and side is not None and match is not None and match['role'].lower() == 'body' and pair_ok
                if side is None: continue
                selected = fixture['design']['coupon_pose']; yaw = fixture['design']['yaw']
                xy = np.asarray(point['position'][:2])-selected[:2]; c, s = np.cos(yaw), np.sin(yaw)
                localxy = np.array([c*xy[0]+s*xy[1], -s*xy[0]+c*xy[1]])
                lift_delta = 0. if first_lift is None else row['tcp_pose_table_wxyz'][2]-lift_origin[2]
                upper = fixture['design']['body_top']+plan['stud_height_m']; margin = .002+np.sin(np.deg2rad(1))*.016
                associated = bool(abs(localxy[0]) <= .016+margin and abs(localxy[1]) <= .008+margin
                    and upper-.0017-.0096-.0015+lift_delta <= point['position'][2] <= upper+.0015+lift_delta)
                result = screen.screen_contact(point['position'], point['separation'], point['normal'] if label == 'source' else -point['normal'], row['finger_poses_world_wxyz'][side], plane.numeric_cad(geometry['fingers'][side], side), associated)
                local['plane_compatible'] = local.get('plane_compatible', True) and result['compatible']
                if label != 'source':
                    order = [p['row'] for p in points[label]].index(point['row'])
                    recorded = row['point_ownership'][label]
                    local[label+'_all_online_points'] = len(recorded) == len(points[label])
                    local['online_screen_matches_independent'] = local.get('online_screen_matches_independent', True) and order < len(recorded) and recorded[order]['plane_screen'] == result
        if support_load > plan['force_floor_N']: support_frames += 1
        for side in peak: peak[side] = max(peak[side], detail['peak_N'][side])
        if total == 1: local['initial_unloaded'] = max(detail['peak_N'].values()) <= 1e-6
        if mode == 'control':
            local['constant_control_commands'] = bool(np.array_equal(command, np.asarray(meta['initial_joint_positions'])))
            local['control_no_robot_contact'] = max(detail['peak_N'].values()) <= plan['force_floor_N']
            local['stable_coupon'] = np.linalg.norm(state[:3]-state0[:3]) <= plan['control_max_coupon_translation_m'] and helper.angle_between(state[3:7], state0[3:7]) <= plan['control_max_coupon_angle_rad']
        else:
            adapter.closure(row, geometry, detail, local)
            if adapter.confirmation is not None and expected_confirmation is None:
                expected_confirmation = force_confirmation_record(adapter.confirmation, row, fi)
            if adapter.admission and reference is None: reference = legacy.relative_pose(row['tcp_pose_world_wxyz'], state)
            if reference:
                relative_m, relative_rad = holding_error(row['tcp_pose_world_wxyz'], state, reference, legacy)
                max_relative_m = max(max_relative_m, relative_m); max_relative_rad = max(max_relative_rad, relative_rad)
                local['coupon_relative_retention'] = relative_m <= plan['held_translation_limit_m'] and relative_rad <= plan['held_angle_limit_rad']
            if row['phase'] == 'lift':
                lift_final = np.asarray(goal[:3])
            if row['phase'] == 'hold':
                hold_count += 1; clearance = fixture_bottom(state, coupon['body_size_m'], helper.rotation)-pedestal['bounds_world_m'][1][2]
                min_hold_clearance = clearance if min_hold_clearance is None else min(min_hold_clearance, clearance)
                local['held_clear_of_support'] = clearance >= plan['minimum_support_separation_m'] and support_load <= plan['force_floor_N']
        for name, passed in local.items():
            if not passed: failures[name] += 1
        previous, last_state = row, state
    checks['all_frames'] = not failures
    checks['all_paired_traces_consumed'] = next(truth, None) is None and next(fixtures, None) is None and next(native_index, None) is None
    checks['steps_marker'] = marker['steps_executed'] == meta['steps_executed'] == total and total <= plan['maximum_physics_steps']
    checks['supported_before_lift'] = support_frames >= 3
    checks['source_terminal_speeds'] = bool(np.max(np.linalg.norm(source_final[:, 7:10], axis=1)) <= .02 and np.max(np.linalg.norm(source_final[:, 10:13], axis=1)) <= .2)
    rise = float(last_state[2]-state0[2])
    if mode == 'control':
        checks['full_stationary_control'] = total == plan['control_steps'] and marker['controller_status'] == 'control_completed'
    else:
        checks['positive_admission'] = adapter.admission is not None
        checks['candidate_record'] = meta['position_candidate'] == adapter.position_candidate and meta['lift_admission'] == adapter.admission
        checks['force_reference_record'] = meta['force_confirmation_reference'] == expected_confirmation and meta['force_confirmation_reference_passed'] is (expected_confirmation is not None)
        checks['no_force_based_admission'] = meta['grasp_confirmation'] is None and (adapter.admission is None or adapter.admission['kind'] == 'position_candidate')
        checks['completed_pick'] = marker['controller_status'] == 'bounded_sequence_completed' and previous['phase'] == 'hold'
        checks['coupon_rise'] = rise >= plan['minimum_coupon_rise_m']
        checks['lift_5mm'] = lift_origin is not None and bool(np.allclose(lift_final-lift_origin, [0, 0, .005], atol=1e-8, rtol=0))
        checks['held_30'] = hold_count == plan['hold_steps'] and reference is not None
    passed = bool(all(checks.values()))
    return mapper.json_native({'mode': mode, 'protocol_sha256': sha(HERE/'protocol.json'), 'checks': checks,
        'frame_failure_counts': dict(failures), 'failed_checks': [k for k, v in checks.items() if not v],
        'retired_finite_surface_reference_failures': dict(retired_reference),
        'steps': total, 'proceed_gate_passed': passed, 'free_coupon_retention_passed': passed and mode == 'pick',
        'tower_extraction_claim': False, 'hardware_claim': False, 'automatic_retry': False,
        'perception_claim': False, 'transfer_authorized': False, 'online_held_identity': 'UNKNOWN',
        'fixture_initial': fixture, 'settings_initial': meta['settings_initial'], 'loaded_observations': dict(loaded_counts),
        'margin_initial': margin_initial, 'margin_authoring': authoring,
        'margin_configuration_verified': bool(checks['one_authored_BODY_margin_change'] and all(v for k, v in checks.items() if '_margin_' in k)),
        'runtime_row_to_BODY_mapping': 'UNKNOWN',
        'source_support_loaded_observations': support_observations,
        'capture_directory': str(folder.resolve()), 'capture_metadata_sha256': sha(folder/'capture_metadata.json'),
        'initial_joint_positions': meta['initial_joint_positions'], 'observer_metadata': observer,
        'force_confirmation_reference': expected_confirmation, 'position_candidate': adapter.position_candidate, 'lift_admission': adapter.admission,
        'metrics': {'coupon_rise_m': rise, 'relative_translation_max_m': max_relative_m, 'relative_angle_max_rad': max_relative_rad,
            'minimum_hold_support_clearance_m': min_hold_clearance, 'source_drift_max_m': max_source_m,
            'source_angle_max_rad': max_source_rad, 'force_peak_N': peak}, 'wall_seconds': time.monotonic()-started})


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--mode', choices=['control', 'pick'], required=True)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--predecessor-control', type=Path)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    if args.mode == 'pick' and args.predecessor_control is None: raise ValueError('Fresh control required')
    started = time.monotonic(); result = audit(args.input, args.mode, args.predecessor_control, started)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

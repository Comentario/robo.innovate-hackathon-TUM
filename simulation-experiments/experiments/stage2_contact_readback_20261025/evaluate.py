"""JSON-only startup readback contract; no shape-order or traction inference."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shape(value):
    if not isinstance(value, list): return []
    if not value: return [0]
    child = shape(value[0])
    if any(shape(item) != child for item in value): raise ValueError('Ragged array')
    return [len(value), *child]


def finite(value):
    if isinstance(value, dict): return all(finite(x) for x in value.values())
    if isinstance(value, list): return all(finite(x) for x in value)
    return not isinstance(value, float) or math.isfinite(value)


def numeric_array(value):
    if isinstance(value, list): return all(numeric_array(x) for x in value)
    return type(value) in (int, float) and math.isfinite(value)


def getter_contract(record, expected_shape):
    """A recorded API error is an observation, never a successful value readback."""
    status = record['status']
    attempted = status in ('AVAILABLE', 'UNAVAILABLE')
    if status == 'UNAVAILABLE':
        return {'attempt_record_valid': bool(record['error']) and record['values'] is None
            and record['shape'] is None and record['dtype'] is None,
            'runtime_array_valid': False, 'uniform_returned_value': None, 'status': status, 'error': record['error']}
    try: actual_shape = shape(record['values'])
    except ValueError: actual_shape = None
    valid = (attempted and record['error'] is None and actual_shape == record['shape'] == expected_shape
        and record['dtype'] == 'float32' and numeric_array(record['values']))
    rows = record['values'][0] if valid else []
    uniform = rows[0] if rows and all(row == rows[0] for row in rows) else None
    return {'attempt_record_valid': bool(attempted and record['error'] is None),
        'runtime_array_valid': bool(valid), 'uniform_returned_value': uniform, 'status': status, 'error': record['error']}


def same_graph(a, b):
    return (len(a['parts']) == len(set(a['parts'])) == len(b['parts']) == len(set(b['parts'])) == 301
        and len(a['edges']) == len(set(a['edges'])) == len(b['edges']) == len(set(b['edges'])) == 930
        and set(a['parts']) == set(b['parts']) and set(a['edges']) == set(b['edges']))


def evaluate(folder):
    folder = Path(folder); plan = read(HERE/'protocol.json'); data = read(folder/'readback.json')
    marker = read(folder/'readback_complete.json'); supervisor = read(folder/'supervisor.json')
    baseline = read(plan['reference_metadata']['path'])
    checks = {'execution_authorized': plan['execution_authorized'] is True,
        'protocol_pin': data['protocol_sha256'] == sha(HERE/'protocol.json'),
        'capture_complete': marker['capture_completed'] is True and supervisor['capture_completed'] is True
            and marker['measured_steps'] == 0 and marker['physical_retry_authorized'] is False
            and not (folder/'failure.json').exists(),
        'reference_metadata_pin': sha(plan['reference_metadata']['path']) == plan['reference_metadata']['sha256'],
        'prior_clock_pin': sha(plan['prior_supervisor']['path']) == plan['prior_supervisor']['sha256'],
        'prior_clock': read(plan['prior_supervisor']['path'])['cumulative_case_seconds'] == plan['prior_case_seconds'],
        'retained_resource': supervisor['prior_case_seconds'] == plan['prior_case_seconds']
            and supervisor['maximum_active_seconds'] == plan['maximum_active_seconds'] == 90
            and supervisor['aggregate_case_ceiling_seconds'] == plan['aggregate_case_ceiling_seconds'] == 2500}
    for path, digest in plan['input_sha256'].items(): checks['input_'+path] = sha(path) == digest
    checks['source_pin_inventory'] = set(data['source_pins']) == {'parent_runner', 'parent_protocol', 'source_science', 'tool_model', 'tensor_api'}
    checks['expected_source_descriptors'] = data['source_pins'] == plan['source_pins']
    for name, item in data['source_pins'].items():
        checks['captured_source_'+name] = (sha(item['path']) == item['sha256']
            and plan['input_sha256'].get(item['path']) == item['sha256'])
    checks['initialization_only'] = (data['initialization']['explicit_preassembly_physics_steps'] == 1
        and data['initialization']['measured_steps'] == 0 and data['initialization']['inherited_targeted_mass_restoration'] is True)
    checks['mapping_honesty'] = data['shape_row_to_collider_mapping'] == 'UNKNOWN'
    checks['SI_stage'] = data['stage_meters_per_unit'] == 1.
    checks['usd_inventory_separate'] = (set(data['usd_colliders']) == {'left', 'right', 'coupon'}
        and all(records and all(r['runtime_row_index'] is None for r in records) for records in data['usd_colliders'].values()))
    before, after = data['before'], data['after']
    checks['finite_snapshots'] = finite(before) and finite(after)
    checks['clock_unchanged'] = before['time_s'] == after['time_s'] and math.isfinite(before['time_s'])
    entry = data['hook_entry']
    checks['hook_entry_unchanged'] = (entry['time_s'] == before['time_s'] and entry['q'] == before['proprioception']['q']
        and entry['qdot'] == before['proprioception']['qdot'])
    checks['proprioception_unchanged'] = before['proprioception'] == after['proprioception']
    checks['same_1822_initial_proprioception'] = before['proprioception'] == baseline['initial_proprioception']
    checks['robot_link_poses_unchanged'] = before['robot_link_poses_world_wxyz'] == after['robot_link_poses_world_wxyz']
    checks['source_unchanged'] = same_graph(before['source'], after['source'])
    coupon_path = plan['view_paths']['coupon']
    checks['coupon_isolated'] = all(s['coupon_component']['parts'] == [coupon_path]
        and s['coupon_component']['edges'] == [] for s in (before, after))
    checks['coupon_state_unchanged'] = before['coupon_state_world'] == after['coupon_state_world'] and shape(before['coupon_state_world']) == [13]
    checks['settings_unchanged'] = data['settings_unchanged'] is True and before['settings'] == after['settings'] == baseline['settings_initial']
    checks['coupon_properties_unchanged'] = before['coupon_properties'] == after['coupon_properties'] == baseline['coupon_properties_initial']
    expected_fixture = plan['reference_fixture']
    checks['reference_fixture_pin'] = sha(expected_fixture['path']) == expected_fixture['sha256']
    fixture = read(folder/data['fixture_initial_file']); old_fixture = read(expected_fixture['path'])
    checks['same_1822_fixture'] = fixture == old_fixture
    checks['same_1822_initial_coupon'] = before['coupon_state_world'] == old_fixture['coupon']['initial_state_world']
    views = {}; checks['three_exact_views'] = set(data['views']) == set(plan['view_paths']) == {'left', 'right', 'coupon'}
    for label, path in plan['view_paths'].items():
        view = data['views'][label]; count = view['max_shapes']
        checks[label+'_exact_body'] = (view['requested_path'] == path and view['prim_paths'] == [path]
            and view['count'] == 1 and isinstance(count, int) and count > 0 and view['view_error'] is None)
        checks[label+'_unmapped'] = view['row_to_collider_mapping'] == 'UNKNOWN'
        checks[label+'_three_getters'] = set(view['getters']) == {'material_properties', 'contact_offsets', 'rest_offsets'}
        views[label] = {}
        for kind in ('material_properties', 'contact_offsets', 'rest_offsets'):
            expected = [1, count, 3] if kind == 'material_properties' else [1, count]
            result = getter_contract(view['getters'][kind], expected); views[label][kind] = result
            checks[label+'_'+kind+'_attempt'] = result['attempt_record_valid']
    complete = bool(all(checks.values()))
    return {'diagnostic_complete': complete, 'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
        'runtime_arrays_valid': complete and all(v['runtime_array_valid'] for view in views.values() for v in view.values()),
        'views': views, 'shape_row_to_collider_mapping': 'UNKNOWN', 'BODY_material_mapped': False,
        'array_schema': {'material_properties': ['static_friction', 'dynamic_friction', 'restitution'],
            'material_units': 'dimensionless', 'contact_offsets': 'meters', 'rest_offsets': 'meters',
            'runtime_arrays_valid_means': 'Getter returned finite numeric float32 arrays of the documented shape; not a physical traction test.'},
        'uniform_value_scope': 'All returned slots of the exact one-body view only; no collider index or combined traction inferred.',
        'proceed_gate_passed': False, 'retention_passed': False, 'physics_extraction_passed': False,
        'physical_retry_authorized': False, 'source_pins': data['source_pins'], 'readback_sha256': sha(folder/'readback.json'),
        'protocol_sha256': sha(HERE/'protocol.json')}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    start = time.monotonic(); result = evaluate(args.input); result['wall_seconds'] = time.monotonic()-start
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

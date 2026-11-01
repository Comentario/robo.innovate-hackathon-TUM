"""JSON-only isolated-coupon material readback; no traction or shape identity claim."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time

HERE = Path(__file__).resolve().parent
KINDS = ('material_properties', 'contact_offsets', 'rest_offsets')
ROLES = ('left', 'right', 'coupon')
ATTRS = ('physics:staticFriction', 'physics:dynamicFriction', 'physics:restitution')
DECLARED = {'BodyCollider': (.5, .4, .1), 'TopCollider': (1., .8, .2)}


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def f32(value): return struct.unpack('f', struct.pack('f', value))[0]
def pinned(record): return sha(record['path']) == record['sha256']


def finite(value):
    if isinstance(value, dict): return all(finite(x) for x in value.values())
    if isinstance(value, list): return all(finite(x) for x in value)
    return not isinstance(value, float) or math.isfinite(value)


def shape(value):
    if not isinstance(value, list): return []
    child = shape(value[0]) if value else []
    if any(shape(item) != child for item in value): raise ValueError('Ragged array')
    return [len(value), *child]


def numeric(value):
    if isinstance(value, list): return all(numeric(x) for x in value)
    return type(value) in (int, float) and math.isfinite(value)


def getter_contract(record, expected):
    if record['status'] == 'UNAVAILABLE':
        return {'attempt_record_valid': bool(record['error']) and all(record[k] is None for k in ('values', 'shape', 'dtype')),
                'runtime_array_valid': False, 'status': 'UNAVAILABLE', 'error': record['error']}
    try: actual_shape = shape(record['values'])
    except ValueError: actual_shape = None
    available = record['status'] == 'AVAILABLE' and record['error'] is None
    return {'attempt_record_valid': available,
            'runtime_array_valid': bool(available and actual_shape == record['shape'] == expected
                and record['dtype'] == 'float32' and numeric(record['values'])),
            'status': record['status'], 'error': record['error']}


def bag(record):
    rows = record['values'][0]
    return sorted(tuple(row) if isinstance(row, list) else row for row in rows)


def runtime_comparison(views, baseline):
    """Compare unordered returned rows only; never assign a row to a collider."""
    attempts, arrays, results, checks = {}, {}, {}, {}
    for label in ROLES:
        current, old = views[label], baseline[label]
        count = current['max_shapes']
        checks[label+'_slot_count'] = type(count) is int and count == old['max_shapes'] == (2 if label == 'coupon' else 5)
        attempts[label], arrays[label], results[label] = {}, {}, {}
        checks[label+'_getter_inventory'] = set(current['getters']) == set(KINDS)
        for kind in KINDS:
            expected = [1, count, 3] if kind == 'material_properties' else [1, count]
            missing = {'status': 'UNAVAILABLE', 'error': 'MISSING_RECORD', 'values': None, 'shape': None, 'dtype': None}
            result = getter_contract(current['getters'].get(kind, missing), expected)
            prior = getter_contract(old['getters'].get(kind, missing), expected)
            results[label][kind] = result
            attempts[label][kind] = kind in current['getters'] and result['attempt_record_valid']
            arrays[label][kind] = result['runtime_array_valid'] and prior['runtime_array_valid']
            if arrays[label][kind]:
                expected_bag = sorted(tuple(f32(x) for x in row) for row in DECLARED.values()) if label == 'coupon' and kind == 'material_properties' else bag(old['getters'][kind])
                checks[label+'_'+kind+'_bag'] = bag(current['getters'][kind]) == expected_bag
            else: checks[label+'_'+kind+'_bag'] = False
    return {'attempts_valid': all(v for role in attempts.values() for v in role.values()),
            'arrays_valid': all(v for role in arrays.values() for v in role.values()),
            'checks': checks, 'getters': results}


def binding_api_addition(before, after):
    """Allow one binding API insertion; preserve every other API and its order."""
    if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(set(before)):
        return False
    name = 'MaterialBindingAPI'
    if name in before: return after == before
    return after.count(name) == 1 and [api for api in after if api != name] == before


def authoring_contract(record, coupon_path, helper, original_author, wrapper):
    before, after = record['before'], record['after']; scope = coupon_path+'/DeclaredContactMaterials'
    targets = {coupon_path+'/'+name: scope+'/'+('Body' if name == 'BodyCollider' else 'Top') for name in DECLARED}
    new_paths = {scope, *targets.values()}
    checks = {'authoring_timing': record['timing'] == 'pre_initialization',
        'authoring_helper_pin': record['helper_pin'] == helper and pinned(record['actual_helper_copy'])
            and record['actual_helper_copy']['sha256'] == helper['sha256'],
        'authoring_subtree_inventory': coupon_path in before and all(p == coupon_path or p.startswith(coupon_path+'/') for p in before)
            and set(after) == set(before) | new_paths and not set(before) & new_paths}
    for path, old in before.items():
        expected = copy.deepcopy(old); api_ok = True
        if path in targets:
            observed_apis = after.get(path, {}).get('apis')
            api_ok = binding_api_addition(old['apis'], observed_apis)
            expected['apis'] = observed_apis
            expected['relationships']['material:binding:physics'] = [targets[path]]
        checks['authoring_preserved_'+path] = api_ok and after.get(path) == expected
    empty = {'type': 'Scope', 'apis': [], 'attributes': {}, 'relationships': {}}
    checks['authoring_scope_only'] = after.get(scope) in (empty, {**empty, 'relationships': {'proxyPrim': []}})
    for name, triple in DECLARED.items():
        target = targets[coupon_path+'/'+name]
        expected = {'type': 'Material', 'apis': ['PhysicsMaterialAPI'], 'relationships': {},
            'attributes': {attr: {'usd_type': 'float', 'sdk_value': f32(value), 'connections': [],
                'has_authored_value': True, 'has_authored_connections': False} for attr, value in zip(ATTRS, triple)}}
        checks['authoring_exact_material_'+name] = after.get(target) == expected
    checks['density_unauthored'] = record['density_defaults'] == {target: {'value': 0., 'has_authored_value': False} for target in targets.values()}
    hook = record['hook']
    checks['authoring_hook_provenance'] = (hook['kind'] == 'process_local_Tool.author_wrapper'
        and hook['class_module'] == 'tool_model' and hook['class_name'] == 'Tool'
        and hook['class_identity_unchanged'] is True and hook['original_method_source'] == original_author
        and pinned(original_author) and hook['wrapper_source'] == wrapper and pinned(wrapper))
    expected_report = {'scope': 'USD_SCHEMA_AUTHORING_ONLY', 'brick_root': coupon_path,
        'pre_initialization_asserted': True, 'targets': {name: {'collider_path': coupon_path+'/'+name,
            'material_path': targets[coupon_path+'/'+name], 'declared_coefficients': [f32(x) for x in triple]}
            for name, triple in DECLARED.items()}, 'runtime_coefficients_verified': False, 'retention_claim': False}
    checks['authoring_exact_helper_report'] = record['report'] == expected_report
    return checks


def graph_same(a, b):
    return all(len(a[k]) == len(set(a[k])) == len(b[k]) == len(set(b[k])) == n
        and set(a[k]) == set(b[k]) for k, n in (('parts', 301), ('edges', 930)))


def usd_inventory_delta(current, old, coupon_path):
    checks = {'untouched_finger_usd': all(current[k] == old[k] for k in ('left', 'right'))}
    current_rows = {r['path']: r for r in current['coupon']}
    old_rows = {r['path']: r for r in old['coupon']}
    expected_paths = {coupon_path+'/'+name for name in DECLARED}
    checks['exact_coupon_colliders'] = (len(current['coupon']) == len(old['coupon']) == 2
        and set(current_rows) == set(old_rows) == expected_paths)
    for name, triple in DECLARED.items():
        path = coupon_path+'/'+name; target = coupon_path+'/DeclaredContactMaterials/'+('Body' if name == 'BodyCollider' else 'Top')
        before, after = old_rows[path], current_rows[path]
        expected = copy.deepcopy(before)
        expected.update(material_path=target, binding_relationship=path+'.material:binding:physics',
            material_attributes={attr: {'value': f32(value), 'has_authored_value': True} for attr, value in zip(ATTRS, triple)})
        expected['material_attributes'].update({name: {'value': None, 'has_authored_value': False}
            for name in ('physxMaterial:frictionCombineMode', 'physxMaterial:restitutionCombineMode')})
        checks[name+'_only_binding_delta'] = (before['material_path'] is None and before['material_attributes'] is None
            and after == expected and after['runtime_row_index'] is None)
    return checks


def evaluate(folder):
    folder = Path(folder); plan = read(HERE/'protocol.json'); data = read(folder/'readback.json')
    marker = read(folder/'readback_complete.json'); supervisor = read(folder/'supervisor.json')
    baseline = read(plan['baseline_readback']['path']); baseline_audit = read(plan['baseline_readback_audit']['path'])
    reference = read(plan['reference_metadata']['path']); old_fixture = read(plan['reference_fixture']['path'])
    checks = {'execution_authorized': plan['execution_authorized'] is True,
        'protocol_pin': data['protocol_sha256'] == sha(HERE/'protocol.json'),
        'capture_complete': marker['capture_completed'] is True and supervisor['capture_completed'] is True
            and marker['measured_steps'] == 0 and marker['physical_retry_authorized'] is False
            and data['diagnostic_complete'] is True and not (folder/'failure.json').exists(),
        'baseline_validated': baseline_audit['diagnostic_complete'] is True and baseline_audit['runtime_arrays_valid'] is True,
        'prior_clock': read(plan['prior_supervisor']['path'])['cumulative_case_seconds'] == plan['prior_case_seconds'],
        'resource_contract': (supervisor['prior_case_seconds'] == plan['prior_case_seconds']
            and supervisor['maximum_active_seconds'] == plan['maximum_active_seconds'] == 60
            and supervisor['aggregate_case_ceiling_seconds'] == plan['aggregate_case_ceiling_seconds'] == 2800
            and 0 <= supervisor['capture_wall_seconds'] <= plan['maximum_active_seconds']
            and 0 < supervisor['remaining_audit_seconds'] <= plan['audit_limit_seconds']
            and plan['prior_case_seconds'] + supervisor['capture_wall_seconds'] < plan['aggregate_case_ceiling_seconds'])}
    for name in ('baseline_readback', 'baseline_readback_audit', 'reference_metadata', 'reference_fixture', 'prior_supervisor', 'binding_helper', 'original_author_source'):
        checks[name+'_pin'] = pinned(plan[name])
    for path, digest in plan['input_sha256'].items(): checks['input_'+path] = sha(path) == digest
    checks['captured_source_descriptors'] = data['source_pins'] == plan['source_pins'] == baseline['source_pins']
    for name, record in data['source_pins'].items():
        checks['captured_source_'+name] = pinned(record) and plan['input_sha256'].get(record['path']) == record['sha256']
    before, after = data['before'], data['after']; entry = data['hook_entry']
    checks['initialization_only'] = (data['initialization']['explicit_preassembly_physics_steps'] == 1
        and data['initialization']['measured_steps'] == 0 and data['initialization']['inherited_targeted_mass_restoration'] is True)
    checks['finite_snapshots'] = finite(before) and finite(after) and finite(entry)
    checks['all_state_and_settings_unchanged'] = before == after == baseline['before']
    checks['hook_entry_unchanged'] = entry == baseline['hook_entry'] and entry['time_s'] == before['time_s'] \
        and entry['q'] == before['proprioception']['q'] and entry['qdot'] == before['proprioception']['qdot']
    checks['reference_proprioception'] = before['proprioception'] == reference['initial_proprioception']
    checks['reference_settings'] = before['settings'] == reference['settings_initial'] and data['settings_unchanged'] is True
    checks['robot_names_and_stage_units'] = data['robot_body_names'] == baseline['robot_body_names'] and data['stage_meters_per_unit'] == baseline['stage_meters_per_unit'] == 1.
    checks['source_graph'] = graph_same(before['source'], after['source']) and before['source'] == baseline['before']['source']
    coupon_path = plan['view_paths']['coupon']
    checks['coupon_isolated'] = before['coupon_component'] == after['coupon_component'] == {'parts': [coupon_path], 'edges': []}
    checks['coupon_properties'] = before['coupon_properties'] == after['coupon_properties'] == reference['coupon_properties_initial']
    checks['fixture_unchanged'] = read(folder/data['fixture_initial_file']) == old_fixture
    checks['initial_coupon_unchanged'] = before['coupon_state_world'] == old_fixture['coupon']['initial_state_world'] and shape(before['coupon_state_world']) == [13]
    checks['mapping_honesty'] = data['shape_row_to_collider_mapping'] == 'UNKNOWN'
    checks['three_exact_views'] = set(data['views']) == set(plan['view_paths']) == set(ROLES)
    for label, path in plan['view_paths'].items():
        view = data['views'][label]
        checks[label+'_exact_body'] = (view['requested_path'] == path and view['prim_paths'] == [path]
            and view['count'] == 1 and view['view_error'] is None and view['row_to_collider_mapping'] == 'UNKNOWN')
    checks.update(usd_inventory_delta(data['usd_colliders'], baseline['usd_colliders'], coupon_path))
    authoring = read(folder/plan['binding_authoring_file'])
    checks['frozen_declared_coefficients'] = plan['expected_coupon_materials'] == [list(row) for row in DECLARED.values()]
    wrapper = {'path': str((HERE/'readback.py').resolve()), 'sha256': sha(HERE/'readback.py')}
    checks.update(authoring_contract(authoring, coupon_path, plan['binding_helper'], plan['original_author_source'], wrapper))
    runtime = runtime_comparison(data['views'], baseline['views'])
    checks['getter_attempt_records'] = runtime['attempts_valid']
    capture_complete = bool(all(checks.values()))
    runtime_checks = runtime['checks']; verified = capture_complete and runtime['arrays_valid'] and all(runtime_checks.values())
    return {'diagnostic_complete': capture_complete, 'runtime_materials_verified': bool(verified),
        'runtime_verdict': 'VERIFIED_UNORDERED_COUPON_MATERIAL_ROWS' if verified else 'UNKNOWN_OR_NOT_VERIFIED',
        'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
        'runtime_checks': runtime_checks, 'failed_runtime_checks': [k for k, v in runtime_checks.items() if not v],
        'runtime_arrays_valid': runtime['arrays_valid'], 'views': runtime['getters'],
        'shape_row_to_collider_mapping': 'UNKNOWN', 'BODY_material_mapped': False,
        'friction_pair_coefficient': 'UNKNOWN', 'proceed_gate_passed': False, 'retention_passed': False,
        'physics_extraction_passed': False, 'physical_retry_authorized': False,
        'scope': 'Startup material configuration only. No contact, traction, row-to-collider assignment or retention claim.',
        'readback_sha256': sha(folder/'readback.json'), 'protocol_sha256': sha(HERE/'protocol.json')}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    start = time.monotonic()
    try: result = evaluate(args.input)
    except Exception as error:
        result = {'diagnostic_complete': False, 'runtime_materials_verified': False,
            'runtime_verdict': 'UNKNOWN_OR_NOT_VERIFIED', 'failed_checks': ['missing_or_invalid_evaluation_input'],
            'error': type(error).__name__+': '+str(error), 'proceed_gate_passed': False, 'retention_passed': False,
            'physical_retry_authorized': False, 'shape_row_to_collider_mapping': 'UNKNOWN'}
    result['wall_seconds'] = time.monotonic()-start
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    raise SystemExit(0 if result['runtime_materials_verified'] else 1)


if __name__ == '__main__': main()

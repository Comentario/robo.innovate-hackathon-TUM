"""Invented JSON/arrays and source AST only; no captured data or simulator."""
import ast
import copy
from pathlib import Path
import tempfile
import numpy as np
import evaluate as audit


def test_frame_loop_unchanged():
    original = Path('/home/faps/dev/github/robo.innovate26/runs/20261025T165816.000989Z-stage2-finger-response/experiments/stage2_finger_response_20261025/evaluate.py')
    def frame_loop(path):
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'audit')
        return next(n for n in function.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'row')
    assert ast.dump(frame_loop(original), include_attributes=False) == ast.dump(frame_loop(Path(audit.__file__)), include_attributes=False)
    text = Path(audit.__file__).read_text()
    assert 'original_control_exact_predecessor' not in text and 'fresh_control_predecessor' in text


def authoring_fixture(pin):
    root = '/Coupon'; scope = root+'/DeclaredContactMaterials'
    empty = {'type': 'Scope', 'apis': [], 'attributes': {}, 'relationships': {}}
    before = {root: {'type': 'Xform', 'apis': [], 'attributes': {'mass': {'sdk_value': .002}}, 'relationships': {}}}
    for name in ('BodyCollider', 'TopCollider'):
        before[root+'/'+name] = {'type': 'Cube', 'apis': ['PhysicsCollisionAPI'],
            'attributes': {'size': {'sdk_value': 1.}}, 'relationships': {'material:binding': ['/Visual']}}
    after = copy.deepcopy(before); after[scope] = {**empty, 'relationships': {'proxyPrim': []}}
    targets = {}; densities = {}
    for name, leaf, triple in (('BodyCollider', 'Body', (.5, .4, .1)), ('TopCollider', 'Top', (1., .8, .2))):
        path = root+'/'+name; target = scope+'/'+leaf; values = [float(np.float32(v)) for v in triple]
        after[path]['apis'].insert(0, 'MaterialBindingAPI'); after[path]['relationships']['material:binding:physics'] = [target]
        after[target] = {'type': 'Material', 'apis': ['PhysicsMaterialAPI'], 'relationships': {},
            'attributes': {key: {'usd_type': 'float', 'sdk_value': value, 'connections': [],
                'has_authored_value': True, 'has_authored_connections': False} for key, value in
                zip(('physics:staticFriction', 'physics:dynamicFriction', 'physics:restitution'), values)}}
        targets[name] = {'collider_path': path, 'material_path': target, 'declared_coefficients': values}
        densities[target] = {'value': 0., 'has_authored_value': False}
    wrapper = audit.HERE/'run_fixture.py'
    record = {'before': before, 'after': after, 'timing': 'pre_initialization', 'helper_pin': pin, 'actual_helper_copy': pin,
        'density_defaults': densities, 'hook': {'kind': 'process_local_inherited_Tool.author_wrapper', 'class_module': 'declared1825_margin',
            'class_name': 'MarginTool', 'runtime_class_name': 'MarginTool', 'class_identity_unchanged': True,
            'original_method_source': pin, 'wrapper_source': {'path': str(wrapper.resolve()), 'sha256': audit.sha(wrapper)}},
        'report': {'scope': 'USD_SCHEMA_AUTHORING_ONLY', 'brick_root': root, 'pre_initialization_asserted': True,
            'targets': targets, 'runtime_coefficients_verified': False, 'retention_claim': False}}
    plan = {'binding_helper': pin, 'original_author_source': pin, 'expected_coupon_materials': [[.5, .4, .1], [1., .8, .2]]}
    return root, record, plan


def test_authoring_lifecycle():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'stub.py'; path.write_text('# invented source\n')
        root, record, plan = authoring_fixture({'path': str(path), 'sha256': audit.sha(path)})
        original = copy.deepcopy(record)
        assert all(audit.material_authoring_checks(record, plan, root).values()) and record == original
        for mutate in (
            lambda x: x['after'][root+'/BodyCollider']['apis'].append('ExtraAPI'),
            lambda x: x['after'][root+'/TopCollider']['apis'].append('MaterialBindingAPI'),
            lambda x: x['after'][root+'/DeclaredContactMaterials']['relationships'].update(proxyPrim=['/Changed']),
            lambda x: x['after'][root]['attributes']['mass'].update(sdk_value=1.),
            lambda x: x['after'][root+'/BodyCollider']['relationships'].update({'material:binding': ['/Changed']}),
        ):
            bad = copy.deepcopy(record); mutate(bad)
            assert not all(audit.material_authoring_checks(bad, plan, root).values())
        schema = {key: value for key, value in record['after'].items() if key != root}
        initial = {'binding_schema': schema, 'binding_schema_unchanged': True,
            'material_settings_changed_reference': 'corrected1828_baseline', 'material_model_changed_from_1825': True}
        assert all(audit.material_lifecycle_checks(initial, initial, record, root).values())
        terminal = copy.deepcopy(initial); terminal['binding_schema'][root+'/DeclaredContactMaterials/Body']['attributes']['physics:dynamicFriction']['sdk_value'] = .9
        assert not all(audit.material_lifecycle_checks(initial, terminal, record, root).values())
    assert not audit.api_addition(['First', 'Second'], ['MaterialBindingAPI', 'Second', 'First'])


def getter(values):
    shape = [1, len(values), 3] if isinstance(values[0], list) else [1, len(values)]
    return {'status': 'AVAILABLE', 'error': None, 'dtype': 'float32', 'shape': shape, 'values': [values]}


def test_combined_runtime():
    views = {}; baseline_offset = float(np.float32(.0013625002466))
    for side, count in (('left', 5), ('right', 5), ('coupon', 2)):
        materials = [[.5, .5, 0.]]*4+[[2.5, 2., 0.]] if count == 5 else [[float(np.float32(v)) for v in row] for row in ((.5, .4, .1), (1., .8, .2))]
        views[side] = {'requested_path': '/'+side, 'prim_paths': ['/'+side], 'count': 1, 'max_shapes': count,
            'view_error': None, 'row_to_collider_mapping': 'UNKNOWN', 'getters': {'material_properties': getter(materials),
                'contact_offsets': getter([baseline_offset]*count), 'rest_offsets': getter([0.]*count)}}
    baseline = {'views': views}; record = {'mapping': 'UNKNOWN', 'baseline_readback_sha256': 'baseline', 'views': copy.deepcopy(views)}
    for side in ('left', 'right'): record['views'][side]['getters']['contact_offsets']['values'][0][0] = float(np.float32(.0001))
    record['views']['coupon']['getters']['material_properties']['values'][0].reverse()
    plan = {'baseline_readback': {'sha256': 'baseline'}, 'body_contact_offset_m': .0001, 'runtime_property_tolerance_m': 1e-8}
    original = copy.deepcopy(record)
    assert all(audit.runtime_margin_checks(record, baseline, plan).values()) and record == original
    for side, kind, value in (('coupon', 'material_properties', [.5, .5, 0.]), ('left', 'material_properties', [1., 1., 0.]),
                               ('right', 'contact_offsets', .0001), ('coupon', 'rest_offsets', .001)):
        bad = copy.deepcopy(record)
        index = 1 if kind == 'contact_offsets' else 0
        bad['views'][side]['getters'][kind]['values'][0][index] = value
        assert not all(audit.runtime_margin_checks(bad, baseline, plan).values())


if __name__ == '__main__':
    test_frame_loop_unchanged(); test_authoring_lifecycle(); test_combined_runtime()
    print('PASS: frozen physical loop, exact binding/lifecycle, combined materials+100um bags and strict negatives')

"""Small invented JSON contracts only; no USD, NumPy, saved data or simulator."""
import copy
from pathlib import Path
import tempfile
from evaluate import authoring_contract, binding_api_addition, f32, getter_contract, runtime_comparison, sha, usd_inventory_delta


def getter(values):
    count = len(values); vector = bool(values and isinstance(values[0], list))
    return {'status': 'AVAILABLE', 'error': None, 'values': [values],
        'shape': [1, count, 3] if vector else [1, count], 'dtype': 'float32'}


def views():
    return {role: {'max_shapes': count, 'getters': {
        'material_properties': getter([[.5, .5, 0.] for _ in range(count)]),
        'contact_offsets': getter([f32(.0013625)]*count), 'rest_offsets': getter([0.]*count)}}
        for role, count in (('left', 5), ('right', 5), ('coupon', 2))}


def test_runtime():
    old = views(); current = copy.deepcopy(old)
    current['coupon']['getters']['material_properties'] = getter([[f32(x) for x in row] for row in ((1., .8, .2), (.5, .4, .1))])
    untouched = copy.deepcopy((current, old)); result = runtime_comparison(current, old)
    assert result['arrays_valid'] and all(result['checks'].values())
    assert (current, old) == untouched
    for role, kind, value in (('left', 'material_properties', [1., 1., 0.]),
                              ('coupon', 'contact_offsets', .0001), ('right', 'rest_offsets', .0001)):
        bad = copy.deepcopy(current); bad[role]['getters'][kind]['values'][0][0] = value
        assert not all(runtime_comparison(bad, old)['checks'].values())
    bad = copy.deepcopy(current); bad['coupon']['getters']['material_properties'] = {
        'status': 'UNAVAILABLE', 'error': 'Backend unavailable', 'values': None, 'shape': None, 'dtype': None}
    result = runtime_comparison(bad, old)
    assert result['attempts_valid'] and not result['arrays_valid'] and not all(result['checks'].values())
    del bad['coupon']['getters']['material_properties']
    result = runtime_comparison(bad, old)
    assert not result['attempts_valid'] and not result['arrays_valid'] and not result['checks']['coupon_getter_inventory']
    assert not getter_contract(getter([[float('nan'), .4, .1]]), [1, 1, 3])['runtime_array_valid']
    assert not getter_contract({**getter([[.5, .4, .1]]), 'shape': [1, 3, 1]}, [1, 1, 3])['runtime_array_valid']


def test_authoring():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)/'source.py'; source.write_text('# synthetic provenance only\n')
        pin = {'path': str(source), 'sha256': sha(source)}
        root = '/Coupon'; scope = root+'/DeclaredContactMaterials'
        empty = {'type': 'Scope', 'apis': [], 'attributes': {}, 'relationships': {}}
        before = {root: {'type': 'Xform', 'apis': ['PhysicsMassAPI'],
            'attributes': {'physics:mass': {'sdk_value': .002}}, 'relationships': {}}}
        for name in ('BodyCollider', 'TopCollider'):
            before[root+'/'+name] = {'type': 'Cube', 'apis': ['PhysicsCollisionAPI'],
                'attributes': {'size': {'sdk_value': 1.}}, 'relationships': {'material:binding': ['/Visual']}}
        after = copy.deepcopy(before); after[scope] = copy.deepcopy(empty); targets = {}; densities = {}
        for name, leaf, triple in (('BodyCollider', 'Body', (.5, .4, .1)), ('TopCollider', 'Top', (1., .8, .2))):
            path = root+'/'+name; target = scope+'/'+leaf
            after[path]['apis'].append('MaterialBindingAPI'); after[path]['relationships']['material:binding:physics'] = [target]
            after[target] = {'type': 'Material', 'apis': ['PhysicsMaterialAPI'], 'relationships': {},
                'attributes': {attr: {'usd_type': 'float', 'sdk_value': f32(value), 'connections': [],
                    'has_authored_value': True, 'has_authored_connections': False}
                    for attr, value in zip(('physics:staticFriction', 'physics:dynamicFriction', 'physics:restitution'), triple)}}
            targets[name] = {'collider_path': path, 'material_path': target, 'declared_coefficients': [f32(x) for x in triple]}
            densities[target] = {'value': 0., 'has_authored_value': False}
        record = {'timing': 'pre_initialization', 'helper_pin': pin, 'actual_helper_copy': pin,
            'before': before, 'after': after, 'density_defaults': densities,
            'hook': {'kind': 'process_local_Tool.author_wrapper', 'class_module': 'tool_model', 'class_name': 'Tool',
                'class_identity_unchanged': True, 'original_method_source': pin, 'wrapper_source': pin},
            'report': {'scope': 'USD_SCHEMA_AUTHORING_ONLY', 'brick_root': root, 'pre_initialization_asserted': True,
                'targets': targets, 'runtime_coefficients_verified': False, 'retention_claim': False}}
        original = copy.deepcopy(record)
        assert all(authoring_contract(record, root, pin, pin, pin).values()) and record == original
        semantic = copy.deepcopy(record)
        for name in ('BodyCollider', 'TopCollider'):
            semantic['after'][root+'/'+name]['apis'] = ['MaterialBindingAPI', 'PhysicsCollisionAPI']
        semantic['after'][scope]['relationships'] = {'proxyPrim': []}
        assert all(authoring_contract(semantic, root, pin, pin, pin).values())
        for mutate in (
            lambda r: r['after'][root]['attributes']['physics:mass'].update(sdk_value=.1),
            lambda r: r['after'].update({root+'/Extra': empty}),
            lambda r: r['after'][root+'/BodyCollider']['relationships'].update({'material:binding': ['/Changed']}),
            lambda r: r['after'][scope+'/Body']['attributes'].update({'physics:density': {'sdk_value': 1.}}),
            lambda r: r['density_defaults'][scope+'/Top'].update(has_authored_value=True),
            lambda r: r['after'][root+'/BodyCollider']['apis'].append('ExtraAPI'),
            lambda r: r['after'][root+'/BodyCollider'].update(apis=['MaterialBindingAPI']),
            lambda r: r['after'][root+'/BodyCollider']['apis'].append('MaterialBindingAPI'),
            lambda r: r['after'][scope]['relationships'].update(proxyPrim=['/Unexpected']),
            lambda r: r['after'][scope]['relationships'].update(other=[]),
        ):
            bad = copy.deepcopy(record); mutate(bad)
            assert not all(authoring_contract(bad, root, pin, pin, pin).values())


def test_api_order():
    old = ['PhysicsCollisionAPI', 'PhysxCollisionAPI']
    assert binding_api_addition(old, ['MaterialBindingAPI', *old])
    assert binding_api_addition(old, [old[0], 'MaterialBindingAPI', old[1]])
    assert binding_api_addition(old, [*old, 'MaterialBindingAPI'])
    assert not binding_api_addition(old, ['MaterialBindingAPI', *reversed(old)])
    assert not binding_api_addition(old, ['MaterialBindingAPI', old[0]])
    assert not binding_api_addition(old, ['MaterialBindingAPI', *old, 'ExtraAPI'])
    assert not binding_api_addition(old, ['MaterialBindingAPI', *old, 'MaterialBindingAPI'])
    already = ['MaterialBindingAPI', *old]
    assert binding_api_addition(already, already)
    assert not binding_api_addition(already, [*old, 'MaterialBindingAPI'])


def test_usd_inventory():
    root = '/Coupon'; old = {'left': [{'sentinel': 1}], 'right': [{'sentinel': 2}], 'coupon': []}
    for name in ('BodyCollider', 'TopCollider'):
        old['coupon'].append({'path': root+'/'+name, 'material_path': None, 'binding_relationship': None,
            'material_attributes': None, 'runtime_row_index': None, 'collider_attributes': {'preserved': 1}})
    current = copy.deepcopy(old)
    for record, leaf, triple in zip(current['coupon'], ('Body', 'Top'), ((.5, .4, .1), (1., .8, .2))):
        record['material_path'] = root+'/DeclaredContactMaterials/'+leaf
        record['binding_relationship'] = record['path']+'.material:binding:physics'
        record['material_attributes'] = {key: {'value': f32(value), 'has_authored_value': True}
            for key, value in zip(('physics:staticFriction', 'physics:dynamicFriction', 'physics:restitution'), triple)}
        record['material_attributes'].update({key: {'value': None, 'has_authored_value': False}
            for key in ('physxMaterial:frictionCombineMode', 'physxMaterial:restitutionCombineMode')})
    assert all(usd_inventory_delta(current, old, root).values())
    current['coupon'][0]['collider_attributes']['preserved'] = 2
    assert not all(usd_inventory_delta(current, old, root).values())


if __name__ == '__main__':
    test_runtime(); test_authoring(); test_api_order(); test_usd_inventory()
    print('PASS: unordered float32 bags, missing/error UNKNOWN, exact USD delta and immutable JSON inputs')

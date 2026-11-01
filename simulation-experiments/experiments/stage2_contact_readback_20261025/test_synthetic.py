"""Tiny JSON shape/status tests; no saved measurements or simulator imports."""
from evaluate import getter_contract, shape


def main():
    valid = {'status': 'AVAILABLE', 'error': None, 'values': [[[2.5, 2., 0.], [2.5, 2., 0.]]], 'shape': [1, 2, 3], 'dtype': 'float32'}
    result = getter_contract(valid, [1, 2, 3])
    assert result['runtime_array_valid'] and result['uniform_returned_value'] == [2.5, 2., 0.]
    assert not getter_contract({**valid, 'shape': [2, 1, 3]}, [1, 2, 3])['runtime_array_valid']
    assert not getter_contract({**valid, 'values': [[[float('nan'), 2., 0.], [2.5, 2., 0.]]]}, [1, 2, 3])['runtime_array_valid']
    unavailable = {'status': 'UNAVAILABLE', 'error': 'Documented backend unavailable', 'values': None, 'shape': None, 'dtype': None}
    result = getter_contract(unavailable, [1, 2, 3])
    assert result['attempt_record_valid'] and not result['runtime_array_valid']
    assert not getter_contract({**unavailable, 'values': [[[0., 0., 0.]]]}, [1, 1, 3])['attempt_record_valid']
    try: shape([[1], [1, 2]])
    except ValueError: pass
    else: raise AssertionError('Ragged array accepted')
    print('PASS: exact JSON shapes, uniform-slot descriptor, nonfinite/error UNKNOWN and no fabricated zeros')


if __name__ == '__main__': main()

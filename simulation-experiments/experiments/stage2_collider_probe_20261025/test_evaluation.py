"""Synthetic independent matching checks; no captured inputs are read."""
import copy
import json
import numpy as np
from evaluate import event_points, map_points, public_packet, json_native


def main():
    rules = {'position_atol_m': 2e-6, 'separation_atol_m': 2e-6, 'normal_atol': .001,
             'impulse_atol_Ns': 1e-7, 'impulse_rtol': 1e-5}
    robot, cube = '/Robot/fr3_leftfinger', '/coupon'
    shape = robot+'/body'; roles = {shape: {'side': 'left', 'role': 'body'}}
    views = {'left': {'sensor_paths': [robot]}, 'coupon': {'sensor_paths': [cube]}}
    point = {'data_index': 0, 'position': [.1, .2, .3], 'normal': [1., 0., 0.],
             'impulse': [.001, 0., 0.], 'separation': -.00001}
    header = {'actor0': robot, 'actor1': cube, 'collider0': shape, 'collider1': cube+'/shape',
              'proto_index0': 2**32-1, 'proto_index1': 2**32-1,
              'contact_data_offset': 0, 'num_contact_data': 1, 'points': [point]}
    event = {'step': 1, 'time_before_s': 0., 'time_after_s': .01, 'dt_s': .01, 'complete': True,
             'callbacks': [{'observed_clock_s': .01, 'raw_contact_data_count': 1, 'headers': [header]}]}
    checks = {}; streams = event_points(event, views, roles, 1e-8, checks)
    assert all(checks.values())
    for label, sign, partner in [('left', 1, cube), ('coupon', -1, robot)]:
        tensor = {'row': 0, 'position': np.array(point['position']), 'normal': np.array([sign, 0., 0.]),
                  'impulse': np.array([sign*.001, 0, 0]), 'separation': point['separation'], 'partner': partner}
        assert map_points([tensor], streams[label], rules)['status'] == 'MAPPED'
        assert map_points([tensor], streams[label]*2, rules)['status'] == 'UNKNOWN'
        assert map_points([tensor], [], rules)['status'] == 'UNKNOWN'
        for key in ('normal', 'impulse'):
            bad = copy.deepcopy(tensor); bad[key] *= -1
            assert map_points([bad], streams[label], rules)['status'] == 'UNKNOWN'
        bad = copy.deepcopy(tensor); bad['partner'] = '/wrong'
        assert map_points([bad], streams[label], rules)['status'] == 'UNKNOWN'
    packet = public_packet(event, roles, {robot: 'left'})
    assert packet['complete'] and packet['robot_contacts'][0]['role'] == 'body'
    assert set(packet['robot_contacts'][0]) == {'side', 'role', 'point_world_m', 'normal_robot_world',
        'normal_impulse_on_robot_world_Ns', 'normal_force_on_robot_world_N'}
    for key, value in [('collider0', robot+'/unknown'), ('proto_index0', 0)]:
        bad = copy.deepcopy(event); bad['callbacks'][0]['headers'][0][key] = value
        rejected = public_packet(bad, roles, {robot: 'left'})
        assert not rejected['complete'] and not rejected['robot_contacts'] and rejected['unknown_robot_shapes'] == 1
    lost = copy.deepcopy(event); lost['callbacks'][0]['raw_contact_data_count'] = 0
    lost['callbacks'][0]['headers'][0].update(contact_data_offset=-1, num_contact_data=0, points=[])
    checks = {}; event_points(lost, views, roles, 1e-8, checks)
    assert all(checks.values())
    lost['callbacks'][0]['headers'][0].update(collider0='/unknown', proto_index0=0)
    empty = public_packet(lost, roles, {robot: 'left'})
    assert empty['complete'] and not empty['robot_contacts'] and empty['unknown_robot_shapes'] == 0
    original = {'checks': {'valid': np.bool_(True), 'positive_roles': np.bool_(False)},
                'roles': {'BODY': {'loaded_frames': np.int64(0)}},
                'proceed_gate_passed': np.bool_(False), 'status': 'UNKNOWN',
                'nested': [np.float64(.2), {'flags': np.array([True, False])}]}
    normalized = json_native(original)
    assert normalized['checks']['valid'] is True and normalized['checks']['positive_roles'] is False
    assert normalized['proceed_gate_passed'] is False and normalized['roles']['BODY']['loaded_frames'] == 0
    assert isinstance(original['checks']['valid'], np.bool_)
    assert json.loads(json.dumps(normalized, allow_nan=False)) == normalized
    assert normalized['nested'] == [.2, {'flags': [True, False]}]
    try:
        json.dumps(json_native({'invalid': np.float64(np.nan)}), allow_nan=False)
    except ValueError:
        pass
    else:
        raise AssertionError('Nonfinite rejection was weakened')
    print('PASS: independent unique/missing/duplicate/sign/partner mapping, unknown shape/proto quarantine and empty LOST')


if __name__ == '__main__':
    main()

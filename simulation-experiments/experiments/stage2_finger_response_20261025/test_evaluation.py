"""Tiny synthetic geometry/holding/quarantine checks; no saved experiment data."""
import numpy as np
from scipy.spatial.transform import Rotation
from pathlib import Path
import copy
from evaluate import (fixture_bottom, holding_error, private_free, force_confirmation_record,
    PositionAdmission, load, body_margin_geometry, runtime_margin_checks, response_limits)


def check_response_limits():
    packet = {'asset_velocity_limits_m_s': [.2, .01]}
    admission = {'command_q_m': .005}; commands = [.005, .005]
    np.testing.assert_array_equal(response_limits('close', packet, commands, None), [.002, .002])
    np.testing.assert_array_equal(response_limits('control', packet, commands, None), [.002, .002])
    np.testing.assert_array_equal(response_limits('lift', packet, commands, admission), [.02, .01])
    np.testing.assert_array_equal(response_limits('hold', packet, commands, admission), [.02, .01])
    assert response_limits('lift', packet, commands, None) is None
    assert response_limits('hold', packet, [.005, .0051], admission) is None
    assert response_limits('unexpected', packet, commands, admission) is None
    assert response_limits('lift', {}, commands, admission) is None
    assert response_limits('close', {'asset_velocity_limits_m_s': [.001, .2]}, commands, admission) is None
    assert response_limits('lift', {'asset_velocity_limits_m_s': [.2, float('nan')]}, commands, admission) is None


def check_single_margin():
    defaults = {'physxCollision:restOffset': {'usd_type': 'float', 'sdk_value': {'nonfinite_scalar': '-inf'}},
        'physxCollision:torsionalPatchRadius': {'usd_type': 'float', 'sdk_value': 0.},
        'physxCollision:minTorsionalPatchRadius': {'usd_type': 'float', 'sdk_value': 0.}}
    plan = {'body_contact_offset_m': .0001, 'allowed_unauthored_collision_defaults': defaults,
        'expected_body_paths': {s: '/'+s+'/mesh_3' for s in ('left', 'right')},
        'baseline_readback': {'sha256': 'baseline'}, 'runtime_property_tolerance_m': 1e-8}
    target = float(np.float32(.0001)); offset = {'usd_type': 'float', 'sdk_value': target}
    old = {'fingers': {s: {'colliders': [{'path': p, 'role': 'body', 'attributes': {'geometry': 'unchanged'},
        'contact_offset_m': None, 'rest_offset_m': None}]} for s, p in plan['expected_body_paths'].items()}}
    now = copy.deepcopy(old); proof = {'timing': 'pre_initialization', 'target_contact_offset_m': .0001,
        'paths': plan['expected_body_paths'], 'schema_attribute_names': [*defaults, 'physxCollision:contactOffset'], 'records': {}}
    for side, path in plan['expected_body_paths'].items():
        body = now['fingers'][side]['colliders'][0]; body['contact_offset_m'] = target
        body['rest_offset_m'] = {'nonfinite_scalar': '-inf'}
        body['attributes'].update(copy.deepcopy(defaults)); body['attributes']['physxCollision:contactOffset'] = offset
        proof['records'][side] = {'path': path, 'old_authored_offset': None, 'new_authored_offset': offset,
            'other_authored_attributes_unchanged': True, 'other_authored_before_sha256': 'same', 'other_authored_after_sha256': 'same',
            'applied_schemas_before': [], 'applied_schemas_after': ['PhysxCollisionAPI'], 'newly_exposed_unauthored_defaults': defaults}
    assert body_margin_geometry(now, old, proof, plan)
    changed = copy.deepcopy(now); changed['fingers']['left']['colliders'][0]['attributes']['geometry'] = 'edited'
    assert not body_margin_geometry(changed, old, proof, plan)
    changed = copy.deepcopy(proof); changed['records']['right']['other_authored_after_sha256'] = 'different'
    assert not body_margin_geometry(now, old, changed, plan)
    base = {'views': {}}
    for side in ('left', 'right', 'coupon'):
        count = 2 if side == 'coupon' else 5
        arrays = {'material_properties': [[[.5, .5, 0.]]*count], 'contact_offsets': [[.0013625]*count], 'rest_offsets': [[0.]*count]}
        base['views'][side] = {'requested_path': '/'+side, 'prim_paths': ['/'+side], 'count': 1, 'max_shapes': count,
            'view_error': None, 'row_to_collider_mapping': 'UNKNOWN', 'getters': {k: {'status': 'AVAILABLE', 'error': None,
                'shape': list(np.asarray(v).shape), 'dtype': 'float32', 'values': v} for k, v in arrays.items()}}
    current = {'mapping': 'UNKNOWN', 'baseline_readback_sha256': 'baseline', 'views': copy.deepcopy(base['views'])}
    for side in ('left', 'right'): current['views'][side]['getters']['contact_offsets']['values'][0][3] = target
    assert all(runtime_margin_checks(current, base, plan).values())  # No index assumption.
    bad = copy.deepcopy(current); bad['views']['coupon']['getters']['contact_offsets']['values'][0][0] = target
    assert not all(runtime_margin_checks(bad, base, plan).values())
    bad = copy.deepcopy(current); bad['views']['left']['getters']['material_properties']['values'][0][0][0] = 2.
    assert not all(runtime_margin_checks(bad, base, plan).values())


def check_position_only():
    root = Path(__file__).resolve().parents[2]
    parent = load('synthetic_position_raw', root/'experiments/stage2_position_candidate_20261025/evaluate.py')
    plan = {'endpoint_command_tolerance_m': 1e-9, 'grasp_confirmation_N': 1.5,
        'grasp_confirmation_consecutive_steps': 3, 'candidate_consecutive_steps': 3,
        'position_contact_floor_N': 1e-6, 'blocked_finger_allowance_m': 2e-6,
        'blocked_gap_allowance_m': 4e-6, 'endpoint_settle_steps': 30}
    meta = {'finger_joint_indices': [0, 1], 'endpoint_preflight': {'endpoint_q_m': .005,
        'gap_intercept_m': .004, 'gap_per_symmetric_q': 2.,
        'inner_planes_finger_y_m': {'left': -.002, 'right': .002},
        'fingers': {'left': {'opening_axis_hand': [0, 1, 0]}, 'right': {'opening_axis_hand': [0, -1, 0]}}}}
    adapter = PositionAdmission(plan, meta, parent, Helper)
    for step in range(1, 34):
        early = step <= 3; command = .006 if early else .005
        actual = command+.001; count = 0 if early else step-3
        row = {'step': step, 'phase': 'close', 'q': [actual, actual], 'joint_commands': [command, command],
            'finger_command_scalar_m': command, 'stop_reasons': [], 'endpoint_settle_completed_commands': count,
            'nominal_commanded_pad_gap_m': .004+2*command, 'actual_model_pad_gap_m': .004+2*actual,
            'position_candidate_sample': not early, 'position_candidate_consecutive_steps': count,
            'finger_tracking_errors_m': [actual-command]*2, 'actual_joint_gap_m': .004+2*actual,
            'commanded_joint_gap_m': .004+2*command, 'normal_force_per_pad_N': {'left': 1.6, 'right': 1.7},
            'tcp_pose_world_wxyz': [0, 0, 0, 1, 0, 0, 0],
            'finger_poses_world_wxyz': {'left': [0, actual+.004, 0, 1, 0, 0, 0],
                'right': [0, -actual-.004, 0, 1, 0, 0, 0]}}
        checks = {}; adapter.closure(row, None, {'peak_N': row['normal_force_per_pad_N']}, checks)
        assert all(checks.values()), checks
        if step < 33: assert adapter.admission is None
    assert adapter.force_record['step'] == 3 and adapter.force_record['command_q_m'] == .006
    assert adapter.force_record['at_endpoint'] is False
    assert adapter.admission == {'kind': 'position_candidate', 'step': 33, 'command_q_m': .005}
    assert [x['step'] for x in adapter.position_candidate['window']] == [31, 32, 33]
    rejected = PositionAdmission(plan, meta, parent, Helper)
    for step in range(1, 31):
        altered = dict(row, step=step, endpoint_settle_completed_commands=step,
            position_candidate_consecutive_steps=step if step < 30 else 0,
            position_candidate_sample=step < 30, stop_reasons=[] if step < 30 else ['sampled_force_abort_left'])
        rejected.closure(altered, None, {'peak_N': altered['normal_force_per_pad_N']}, {})
    assert rejected.admission is None


class Helper:
    @staticmethod
    def rotation(q): return Rotation.from_quat(np.asarray(q)[[1, 2, 3, 0]]).as_matrix()

    @staticmethod
    def relative_pose(tcp, body):
        r = Helper.rotation(tcp[3:7])
        return r.T@(np.asarray(body[:3])-tcp[:3]), r.T@Helper.rotation(body[3:7])


def main():
    state = np.array([.1, .2, .05, 1., 0., 0., 0., 0., 0., 0., 0., 0., 0.])
    assert fixture_bottom(state, [.032, .016, .0096], Helper.rotation) == .05
    tcp = np.array([.1, .2, .07, 1., 0., 0., 0.])
    reference = Helper.relative_pose(tcp, state)
    moved, lifted = state.copy(), tcp.copy(); moved[2] += .005; lifted[2] += .005
    a, b = holding_error(lifted, moved, reference, Helper)
    assert a < 1e-12 and b < 1e-12
    moved[2] -= .002
    assert holding_error(lifted, moved, reference, Helper)[0] > .001
    assert private_free({'step': 1, 'forces_N': [1, 2]})
    assert not private_free({'nested': [{'collider0': 'x'}]})
    assert not private_free({'x': '/World/secret'})
    confirmation = {'step': 24, 'command_q_m': .005, 'at_endpoint': True}
    row = {'step': 24, 'joint_commands': [1., .005, .006]}
    expected = force_confirmation_record(confirmation, row, [1, 2])
    assert expected == {**confirmation, 'commanded_finger_q_m': [.005, .006]}
    assert expected != confirmation  # Missing vector is rejected by full-schema comparison.
    assert expected != {**confirmation, 'commanded_finger_q_m': [.005, .005]}
    assert force_confirmation_record(None, row, [1, 2]) is None
    try: force_confirmation_record(confirmation, {**row, 'step': 25}, [1, 2])
    except ValueError: pass
    else: raise AssertionError('Commands from a different step accepted')
    check_position_only()
    check_single_margin()
    check_response_limits()
    print('PASS: preserved admission/holding/margin; capped phase ceilings; no missing/unknown/unfrozen-target allowance')


if __name__ == '__main__': main()

"""Tiny synthetic geometry/holding/quarantine checks; no saved experiment data."""
import numpy as np
from scipy.spatial.transform import Rotation
from pathlib import Path
from evaluate import fixture_bottom, holding_error, private_free, force_confirmation_record, PositionAdmission, load


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
    print('PASS: holding/quarantine/schema; early force is reference only; exact30 blocked admission; aborted window rejected')


if __name__ == '__main__': main()

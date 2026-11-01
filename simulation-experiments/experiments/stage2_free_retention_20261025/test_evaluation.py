"""Tiny synthetic geometry/holding/quarantine checks; no saved experiment data."""
import numpy as np
from scipy.spatial.transform import Rotation
from evaluate import fixture_bottom, holding_error, private_free, force_confirmation_record


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
    print('PASS: geometry/holding/quarantine and exact force-command record, wrong/missing vector rejection')


if __name__ == '__main__': main()

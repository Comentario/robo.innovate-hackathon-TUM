"""Small synthetic FK/Jacobian/DLS checks; no USD or simulator imports."""
import json
import numpy as np
from kinematics import errors, fk, solve, transform


def main():
    joints = []
    for i, axis in enumerate(('Z', 'Y', 'X', 'Y', 'X', 'Y', 'Z')):
        local = np.eye(4); local[:3, 3] = [.03, .01, .04]
        joints.append({'type': 'revolute', 'T_parent_joint': local.tolist(),
                       'T_child_joint': np.eye(4).tolist(),
                       'axis_vector': np.eye(3)['XYZ'.index(axis)].tolist()})
    # Include a fixed hand transform and a rolled/yawed root: no world-axis shortcut.
    hand = np.eye(4); hand[:3, 3] = [0., 0., .02]
    joints.append({'type': 'fixed', 'T_parent_joint': hand.tolist(), 'T_child_joint': np.eye(4).tolist()})
    chain = {'T_world_root': transform([-.09, -.4, 0.], [.9238795325, 0, 0, .3826834324]).tolist(),
             'joints': joints, 'limits_rad': [[-2., 2.]]*7}
    offset = transform([0., 0., .1175575612], [1., 0, 0, 0])
    q = np.array([.1, -.2, .1, -.1, .2, .1, -.1])
    _, tcp, jacobian = fk(chain, q, offset)
    for i in range(7):
        changed = q.copy(); changed[i] += 1e-7
        numeric = errors(tcp, fk(chain, changed, offset)[1])/1e-7
        np.testing.assert_allclose(jacobian[:, i], numeric, atol=1e-7, rtol=1e-6)
    target = fk(chain, q+.01, offset)[1]
    result, _, predicted, _, residual = solve(chain, q, offset, target)
    assert np.linalg.norm(residual[:3]) <= .0001
    assert np.linalg.norm(residual[3:]) <= np.deg2rad(.1)
    assert np.max(abs(result-q)) < .05
    json.dumps({'predicted': predicted.tolist(), 'q': result.tolist()}, allow_nan=False)
    try:
        solve(chain, np.full(7, 3.), offset, target)
    except RuntimeError as exc:
        assert 'limits' in str(exc)
    else:
        raise AssertionError('Out-of-limit seed accepted')
    try:
        transform([0, 0, 0], [2, 0, 0, 0])
    except RuntimeError:
        pass
    else:
        raise AssertionError('Unnormalized quaternion accepted')
    print('PASS: synthetic seven-axis FK/Jacobian/DLS, fixed hand/root frames, limits, strict JSON')


if __name__ == '__main__':
    main()

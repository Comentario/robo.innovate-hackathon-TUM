"""Small synthetic endpoint/freeze/interface checks; no captured data or Kit."""
from collections import Counter
from types import SimpleNamespace
import numpy as np
from evaluate import ContactAudit, RETIRED, nominal_gap, source_partner_category


def main():
    fingers = {'/Robot/left': 'left', '/Robot/right': 'right'}
    ids = {'target', 'support'}
    assert source_partner_category('/Robot/left', 'target', fingers, ids) == 'FINGER'
    assert source_partner_category('support', 'target', fingers, ids) == 'OTHER_LEGO_INTERFACE'
    assert source_partner_category('/World/Robot/hand', 'target', fingers, ids) == 'FORBIDDEN_OTHER_ROBOT'
    assert source_partner_category('/ground', 'target', fingers, ids) == 'UNKNOWN'
    assert set(RETIRED) == {'all_loaded_points_body_flat_lateral', 'all_reciprocal_loaded_points_body_flat_lateral'}
    obj = object.__new__(ContactAudit)
    obj.plan = {'endpoint_command_tolerance_m': 1e-9, 'grasp_confirmation_N': 1.5,
                'grasp_confirmation_consecutive_steps': 3, 'endpoint_settle_steps': 30}
    endpoint = .00559331; inner = {'left': .00140669, 'right': -.00140669}
    obj.meta = {'finger_joint_indices': [0, 1], 'endpoint_preflight': {'endpoint_q_m': endpoint,
        'gap_intercept_m': .00281338, 'gap_per_symmetric_q': 2., 'inner_planes_finger_y_m': inner}}
    obj.helper = SimpleNamespace(rotation=lambda q: np.eye(3))
    obj.positive = obj.endpoint_count = 0; obj.confirmation = None
    def row(step, requested, phase='close'):
        command = float(np.float32(requested))
        state = {'step': step, 'phase': phase, 'finger_command_scalar_m': requested,
            'joint_commands': [command, command], 'nominal_commanded_pad_gap_m': .00281338+2*requested,
            'endpoint_settle_completed_commands': obj.endpoint_count+int(phase == 'close' and abs(requested-endpoint) <= 1e-9),
            'tcp_pose_world_wxyz': [0, 0, 0, 1, 0, 0, 0],
            'finger_poses_world_wxyz': {'left': [0, .008, 0, 1, 0, 0, 0], 'right': [0, -.008, 0, 1, 0, 0, 0]}}
        state['actual_model_pad_gap_m'] = nominal_gap(state, inner, obj.helper.rotation)
        return state
    for step in (1, 2, 3):
        checks = {}; obj.closure(row(step, .0065-step/120000), {}, {'peak_N': {'left': 1.5, 'right': 1.5}}, checks)
        assert all(checks.values())
    assert obj.confirmation['step'] == 3
    frozen = obj.confirmation['command_q_m']
    checks = {}; obj.closure(row(4, frozen, 'lift'), {}, {'peak_N': {'left': 1., 'right': 1.}}, checks)
    assert checks['last_command_frozen_after_confirmation']
    checks = {}; obj.closure(row(5, frozen-.00001, 'lift'), {}, {'peak_N': {'left': 1., 'right': 1.}}, checks)
    assert not checks['last_command_frozen_after_confirmation']
    obj.positive = obj.endpoint_count = 0; obj.confirmation = None
    for step in range(1, 31):
        checks = {}; obj.closure(row(step, endpoint), {}, {'peak_N': {'left': 0., 'right': 0.}}, checks)
        assert all(checks.values())
    assert obj.endpoint_count == 30 and obj.confirmation is None
    checks = {}; obj.closure(row(31, endpoint), {}, {'peak_N': {'left': 0., 'right': 0.}}, checks)
    assert not checks['settle_budget_before_confirmation']
    print('PASS: last commanded float32 target freeze, 30 completed endpoint samples, separate LEGO/robot source contacts and exact retired predicates')


if __name__ == '__main__': main()

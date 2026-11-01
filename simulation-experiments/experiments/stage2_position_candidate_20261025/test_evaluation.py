"""Synthetic admission windows and reference-only force checks; no saved data."""
import copy
from collections import Counter
from types import SimpleNamespace
import numpy as np
from evaluate import AdmissionAudit, raw_position_sample, amend_force_prerequisites, parent


def instance():
    obj = object.__new__(AdmissionAudit)
    obj.plan = {'endpoint_command_tolerance_m': 1e-9, 'grasp_confirmation_N': 1.5,
        'grasp_confirmation_consecutive_steps': 3, 'endpoint_settle_steps': 30,
        'position_contact_floor_N': 1e-6, 'blocked_finger_allowance_m': 2e-6,
        'blocked_gap_allowance_m': 4e-6, 'candidate_consecutive_steps': 3}
    obj.meta = {'finger_joint_indices': [0, 1], 'endpoint_preflight': {'endpoint_q_m': .00559331,
        'gap_intercept_m': .00281338, 'gap_per_symmetric_q': 2.,
        'inner_planes_finger_y_m': {'left': .00140669, 'right': -.00140669},
        'fingers': {'left': {'opening_axis_hand': [0, 1, 0]}, 'right': {'opening_axis_hand': [0, -1, 0]}}}}
    obj.helper = SimpleNamespace(rotation=lambda q: np.eye(3))
    obj.positive = obj.endpoint_count = obj.position_count = 0
    obj.confirmation = obj.position_candidate = obj.admission = None
    obj.force_only_reference = Counter(); obj.window = []; obj.admission_window = []
    return obj


def row(obj, step, phase='close', forces=None):
    endpoint = obj.meta['endpoint_preflight']['endpoint_q_m']; commanded = float(np.float32(endpoint))
    actual = commanded+.0005
    result = {'step': step, 'phase': phase, 'finger_command_scalar_m': endpoint,
        'joint_commands': [commanded, commanded], 'q': [actual, actual],
        'normal_force_per_pad_N': forces or {'left': .5, 'right': .6}, 'stop_reasons': [],
        'endpoint_settle_completed_commands': obj.endpoint_count+int(phase == 'close'),
        'nominal_commanded_pad_gap_m': .00281338+2*endpoint,
        'tcp_pose_world_wxyz': [0, 0, 0, 1, 0, 0, 0],
        'finger_poses_world_wxyz': {'left': [0, actual, 0, 1, 0, 0, 0], 'right': [0, -actual, 0, 1, 0, 0, 0]}}
    result['actual_model_pad_gap_m'] = parent.nominal_gap(result, obj.meta['endpoint_preflight']['inner_planes_finger_y_m'], obj.helper.rotation)
    sample, errors, actual_gap, command_gap = raw_position_sample(result, obj.meta, obj.plan)
    result.update(position_candidate_sample=sample, position_candidate_consecutive_steps=obj.position_count+1 if sample else 0,
        finger_tracking_errors_m=errors.tolist(), actual_joint_gap_m=actual_gap, commanded_joint_gap_m=command_gap)
    return result


def main():
    obj = instance(); good = row(obj, 1)
    assert raw_position_sample(good, obj.meta, obj.plan)[0]
    assert not raw_position_sample(good, obj.meta, obj.plan, {'left': 0., 'right': .6})[0]
    for modify in ('force_floor', 'one_unblocked', 'abort'):
        bad = copy.deepcopy(good)
        if modify == 'force_floor': bad['normal_force_per_pad_N']['right'] = 1e-6
        elif modify == 'one_unblocked': bad['q'][0] = bad['joint_commands'][0]+1e-6
        else: bad['stop_reasons'] = ['sampled_force_abort_left']
        assert not raw_position_sample(bad, obj.meta, obj.plan)[0]
    pose_only = copy.deepcopy(good); pose_only['q'] = list(pose_only['joint_commands']); pose_only['actual_model_pad_gap_m'] = 99.
    assert not raw_position_sample(pose_only, obj.meta, obj.plan)[0]
    for step in range(1, 31):
        current = row(obj, step); checks = {}
        obj.closure(current, {}, {'peak_N': current['normal_force_per_pad_N']}, checks)
        assert all(checks.values())
        if step < 30: assert obj.admission is None
    assert obj.confirmation is None and obj.admission['kind'] == 'position_candidate'
    assert [p['step'] for p in obj.position_candidate['window']] == [28, 29, 30]
    assert all(p['sample_passed'] for p in obj.position_candidate['window'])
    current = row(obj, 31, 'lift'); checks = {}
    obj.closure(current, {}, {'peak_N': current['normal_force_per_pad_N']}, checks)
    assert checks['admission_before_lift'] and checks['last_command_targets_held_after_admission']
    assert obj.force_only_reference['no_lift_before_confirmation'] == 1 and len(obj.admission_window) == 3
    missing = instance()
    for step in range(1, 31):
        current = row(missing, step, forces={'left': 0., 'right': .6} if step == 29 else None)
        missing.closure(current, {}, {'peak_N': current['normal_force_per_pad_N']}, {})
    assert missing.admission is None
    force = instance()
    for step in (1, 2, 3):
        current = row(force, step, forces={'left': 1.5, 'right': 1.5})
        force.closure(current, {}, {'peak_N': current['normal_force_per_pad_N']}, {})
    assert force.admission['kind'] == 'force_confirmation' and force.confirmation['step'] == 3
    assert force.position_candidate is None and force.endpoint_count == 3
    result = {'checks': {'all_measured_frame_guards': False, 'positive_force_trigger': False,
        'detachment_after_grasp_trigger': False, 'held_relative_transform': False},
        'frame_failure_counts': {'force_trigger_before_lift': 10, 'tcp_tracking': 1},
        'metrics': {'first_singleton_step': 40, 'first_force_trigger_step': None}}
    revised = amend_force_prerequisites(result, obj)
    assert revised['force_only_reference_checks']['positive_force_trigger'] is False
    assert revised['checks']['held_relative_transform'] is False and revised['checks']['all_measured_frame_guards'] is False
    assert revised['frame_failure_counts'] == {'tcp_tracking': 1}
    assert revised['checks']['detachment_after_lift_admission'] and revised['metrics']['first_force_trigger_step'] is None
    print('PASS: raw bilateral endpoint window, stale/missing/aborted rejection, no pose-gap substitution, honest force references and unchanged native/motion failures')


if __name__ == '__main__': main()

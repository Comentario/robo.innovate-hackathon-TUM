"""Small invented protocol/model cases only; no robot, source dataset or Isaac."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

PATH = Path(__file__).resolve().parents[1]/'experiments/control_alignment_20261026/evaluate.py'
spec = importlib.util.spec_from_file_location('independent_control_audit', PATH)
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def tokens():
    identity = np.eye(4).reshape(-1, order='F').tolist()
    coefficients = np.array([[0., 0., .01, .1]]*7)
    return ([2, 2]+identity*3+[.1]*7+[0.]*18+[-1.]*3+[1.]*3
        +[1., .02, .4, .3, 1., .001, .017453292519943295, .5, 2., 6., .3, .1, .08, 50., 0., .15, 0., 1.]
        +[-3.]*7+[3.]*7+identity*8+[0.]+coefficients.reshape(-1).tolist()+[1.])


class ControlAuditTests(unittest.TestCase):
    def test_parse_spline_nested_rebase(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'joint_input.txt'; path.write_text('\n'.join(map(str, tokens())))
            plan = audit.parse_plan(path)
            comparisons = {'timeout': 0. <= plan['timeout'], 'endpoint': 0. <= plan['position_tolerance'],
                'settle': plan['seconds']+.8 <= 2., 'stable': .5 >= plan['stable']}
            self.assertTrue(all(type(value) is bool for value in comparisons.values()))
            self.assertEqual(json.loads(json.dumps(comparisons)), comparisons)
            np.testing.assert_allclose(audit.spline_q(plan, .5), [.105]*7, atol=1e-15)
            reference = plan['q0']+.0005
            np.testing.assert_array_equal(audit.rebased_command(plan, 0., reference)[2], reference)
            u, raw, command = audit.rebased_command(plan, .5, reference)
            self.assertEqual(u, .5); np.testing.assert_allclose(command, [.10525]*7, atol=1e-15)
            np.testing.assert_allclose(audit.rebased_command(plan, 2., reference)[2], [.11]*7, atol=1e-15)
            for values in ([1, *tokens()[1:]], [*tokens(), 99], [*tokens()[:-1], float('nan')]):
                path.write_text('\n'.join(map(str, values)))
                with self.assertRaises(ValueError): audit.parse_plan(path)

    def test_independent_limiter_first_reference_and_small_step(self):
        parameters = np.array([[2.6, 0., 6., 3., -3.]]*7); zeros = np.zeros(7); command = np.full(7, .1)
        output = audit.sdk_limit(parameters, command, zeros, zeros, zeros)
        np.testing.assert_allclose(output, [4.999999e-6]*7, atol=1e-15, rtol=0)
        np.testing.assert_array_equal(audit.sdk_limit(parameters, command, command, zeros, zeros), command)
        with self.assertRaises(ValueError): audit.sdk_limit(parameters, [float('nan')]*7, zeros, zeros, zeros)

    def test_actual_target_channel_not_measured_alias(self):
        command = np.linspace(.101, .701, 7); accepted = command.astype(np.float32).astype(float)
        state = {'q': (accepted+.0002).tolist(), 'q_d': accepted.tolist(),
            'joint_target_readback': accepted.tolist(), 'raw_requested_q': command.tolist()}
        self.assertTrue(all(audit.target_channels(state, command).values()))
        aliased = dict(state, q_d=state['q'])
        self.assertFalse(audit.target_channels(aliased, command)['public_qd_readback'])
        wrong = dict(state, joint_target_readback=(accepted+.0001).tolist())
        self.assertFalse(audit.target_channels(wrong, command)['accepted_limited_command'])

    def test_callback_result_serializes_without_normalizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'joint_input.txt'; path.write_text('\n'.join(map(str, tokens())))
            plan = audit.parse_plan(path); q = plan['q0'].tolist(); pose = audit.model_fk(plan, q)[0].reshape(-1, order='F').tolist()
            state = {'q': q, 'dq': [0.]*7, 'q_d': q, 'dq_d': [0.]*7, 'ddq_d': [0.]*7,
                'joint_target_readback': q, 'F_T_EE': plan['tool'].tolist(), 'O_T_EE': pose, 'O_dP_EE_c': [0.]*6, 'time': 0.}
            after = dict(state, time=.001)
            row = {'step': 1, 'period_s': 0., 'elapsed_s': 0., 'startup_s': 0., 'warmed': False, 'u': 0.,
                'state_before': state, 'state_after': after, 'guard_status': 'PASS', 'hardware_network_feedback': 'UNAVAILABLE',
                'raw_spline_q': q, 'rebased_command_q': q, 'limited_command_q': q,
                'expected_O_T_EE': audit.expected_pose(plan, 0.).reshape(-1, order='F').tolist()}
            trace = Path(directory)/'trace.jsonl'; trace.write_text(json.dumps(row)+'\n')
            parameters = np.array([[2.6, 0., 6., 3., -3.]]*7)
            checks, metrics = audit.callback_audit(trace, plan, parameters, 'A')
            self.assertFalse(checks['all_callback_checks'])  # Invented singular/short fixture is deliberately invalid.
            self.assertIs(type(checks['end_stationary']), bool)
            self.assertTrue(json.dumps({'checks': checks, 'metrics': metrics}, allow_nan=False))

    def test_column_major_FK_and_independent_jacobian(self):
        origins = []
        for i in range(7):
            t = np.eye(4); t[:3, :3] = Rotation.from_euler('xyz', [.1*i, -.12*i, .04]).as_matrix()
            t[:3, 3] = [.01*i, -.008*i, .05]; origins.append(t)
        ee = np.eye(4); ee[:3, 3] = [.02, .01, .1034]
        plan = {'origins': origins, 'ee': ee, 'length': .3}; q = np.linspace(-.3, .3, 7)
        pose, jacobian = audit.model_fk(plan, q)
        for i in range(7):
            plus = q.copy(); minus = q.copy(); plus[i] += 1e-7; minus[i] -= 1e-7
            derivative = (audit.model_fk(plan, plus)[0][:3, 3]-audit.model_fk(plan, minus)[0][:3, 3])/2e-7
            np.testing.assert_allclose(jacobian[:3, i], derivative, atol=2e-9, rtol=0)
        np.testing.assert_array_equal(audit.matrix(pose.reshape(-1, order='F')), pose)
        with self.assertRaises(ValueError): audit.matrix([0.]*15)

    def test_derived_clock_serialization_only(self):
        n = 3000; initial = .001
        times = initial+np.arange(1, n+1)*float(np.float32(.001))
        self.assertEqual(audit.clock_serialization_budget(n), n*abs(float(np.float32(.001))-.001)+1e-9)
        self.assertTrue(audit.source_clock_coverage(times, initial, float(times[-1]), n))
        bad = times.copy(); bad[-1] += 1e-6
        self.assertFalse(audit.source_clock_coverage(bad, initial, float(bad[-1]), n))
        missing = times[:-1]
        self.assertFalse(audit.source_clock_coverage(missing, initial, float(times[-1]), n))
        with self.assertRaises(ValueError): audit.clock_serialization_budget(-1)

    def test_batched_source_startup_mapping_and_equivalence(self):
        names = [f'brick_{i:03d}' for i in range(300)]
        expected = ['/World/envs/env_0/'+name for name in names]
        poses = np.zeros((300, 7)); poses[:, 0] = np.arange(300)*.01; poses[:, 3] = 1.
        initial = {'names': names, 'poses_world_wxyz': poses.tolist()}
        proof = {'names': names, 'expected_root_paths': expected, 'actual_view_prim_paths': expected[::-1],
            'row_indices_in_name_order': list(range(299, -1, -1)), 'count': 300,
            'subspace_roots': '/', 'frame': 'world', 'getter_layout': 'xyz_xyzw', 'returned_layout': 'xyz_wxyz',
            'snapshot_copy': True, 'no_step_called_by_reader': True, 'old_reader': 'scene[name].data.root_link_pose_w[0]',
            'old_poses_world_wxyz': poses.tolist(), 'new_poses_world_wxyz': poses.tolist(),
            'clock_before_s': .001, 'clock_after_s': .001, 'position_tolerance_m': 1e-9, 'angle_tolerance_rad': 1e-7,
            'maximum_position_error_m': 0., 'maximum_angle_error_rad': 0., 'equivalence_passed': True}
        self.assertTrue(audit.startup_getter_proof(proof, initial, .001))
        for field, value in [('row_indices_in_name_order', list(range(300))), ('snapshot_copy', False),
                ('frame', 'environment'), ('clock_after_s', .002)]:
            bad = copy.deepcopy(proof); bad[field] = value
            self.assertFalse(audit.startup_getter_proof(bad, initial, .001))
        bad = copy.deepcopy(proof); bad['new_poses_world_wxyz'][0][0] += 1e-6
        self.assertFalse(audit.startup_getter_proof(bad, initial, .001))
        bad = copy.deepcopy(proof); bad['actual_view_prim_paths'][0] = bad['actual_view_prim_paths'][1]
        self.assertFalse(audit.startup_getter_proof(bad, initial, .001))
        # Quaternion sign equivalence is valid; initial recording still binds exact new rows.
        proof['old_poses_world_wxyz'] = (poses*np.array([1, 1, 1, -1, -1, -1, -1])).tolist()
        self.assertTrue(audit.startup_getter_proof(proof, initial, .001))
        self.assertTrue(json.dumps({'check': audit.startup_getter_proof(proof, initial, .001)}, allow_nan=False))

    def test_v2_fresh_source_reference_preserves_cache_discrepancy(self):
        names = [f'brick_{i:03d}' for i in range(300)]; paths = ['/World/envs/env_0/'+n for n in names]
        poses = np.zeros((300, 7)); poses[:, 0] = np.arange(300)*.01; poses[:, 3] = 1.
        cached = poses.copy(); cached[0, 0] += 4e-9
        discrepancy = float(abs(cached[0, 0]-poses[0, 0]))
        summary = {'maximum_position_error_m': discrepancy, 'maximum_angle_error_rad': 0., 'passed': False}
        proof = {'proof_version': 2, 'names': names, 'expected_root_paths': paths,
            'actual_view_prim_paths': paths[::-1], 'row_indices_in_name_order': list(range(299, -1, -1)),
            'count': 300, 'subspace_roots': '/', 'frame': 'world', 'getter_layout': 'xyz_xyzw', 'returned_layout': 'xyz_wxyz',
            'snapshot_copy': True, 'no_step_called_by_reader': True, 'clock_before_s': .001, 'clock_after_s': .001,
            'reference_reader': 'fresh_per_asset_PhysX_get_transforms',
            'direct_raw_poses_world_xyzw': poses[:, [0, 1, 2, 4, 5, 6, 3]].tolist(),
            'direct_poses_world_wxyz': poses.tolist(), 'new_poses_world_wxyz': poses.tolist(),
            'batch_raw_poses_world_xyzw': poses[::-1][:, [0, 1, 2, 4, 5, 6, 3]].tolist(),
            'cached_poses_world_wxyz': cached.tolist(), 'cached_direct_comparison': summary,
            'cached_batch_comparison': copy.deepcopy(summary), 'maximum_position_error_m': 0.,
            'maximum_angle_error_rad': 0., 'position_tolerance_m': 1e-9, 'angle_tolerance_rad': 1e-7,
            'equivalence_passed': True}
        initial = {'names': names, 'poses_world_wxyz': poses.tolist()}
        self.assertTrue(audit.startup_getter_proof(proof, initial, .001))
        for mutate in [lambda p: p['direct_raw_poses_world_xyzw'][0].__setitem__(0, .0002),
                lambda p: p.update(row_indices_in_name_order=list(range(300))),
                lambda p: p['cached_direct_comparison'].update(passed=True),
                lambda p: p.update(proof_version=3),
                lambda p: p.update(old_reader='scene[name].data.root_link_pose_w[0]')]:
            bad = copy.deepcopy(proof); mutate(bad)
            self.assertFalse(audit.startup_getter_proof(bad, initial, .001))


if __name__ == '__main__': unittest.main()

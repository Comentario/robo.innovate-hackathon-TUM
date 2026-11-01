"""Invented pose arrays only; no saved scene, tensor API or simulator."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

SPEC = importlib.util.spec_from_file_location('pose_reader_audit', Path(__file__).with_name('evaluate.py'))
audit = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(audit)
OLD_SPEC = importlib.util.spec_from_file_location('startup_proof_audit',
    Path(__file__).resolve().parent.parent/'control_alignment_20261026/evaluate.py')
old_audit = importlib.util.module_from_spec(OLD_SPEC); OLD_SPEC.loader.exec_module(old_audit)


def fixture():
    names = [f'brick_{i:03}' for i in range(300)]
    paths = ['/World/envs/env_0/'+name for name in names]
    poses = np.zeros((300, 7), np.float32); poses[:, 0] = np.arange(300)*.01
    poses[:, 3:5] = [np.sqrt(.5), np.sqrt(.5)]
    xyzw = poses[:, [0, 1, 2, 4, 5, 6, 3]]
    def channel(raw, layout):
        return {'raw_layout': layout, 'raw_dtype': 'float32', 'raw_poses': raw.tolist(),
            'poses_world_wxyz': poses.tolist(), 'clock_before_s': .001, 'clock_after_s': .001}
    scene = {'native_parts_paths': [f'/part_{i}' for i in range(301)],
        'native_connections_paths': [f'/edge_{i}' for i in range(930)],
        'arm_joint_positions': [0.]*7, 'physics_time_s': .001, 'physics_step_index': 1}
    data = {'pose_readers': {'schema': 'pose-reader-startup-v1', 'names': names, 'expected_root_paths': paths,
        'actual_view_prim_paths': paths[::-1], 'row_indices_in_name_order': list(range(299, -1, -1)), 'count': 300,
        'frame': 'world', 'subspace_roots': '/', 'limits': {'position_m': 1e-9, 'angle_rad': 1e-7},
        'no_step_called': True, 'snapshot_copy': True,
        'channels': {'cached': channel(poses, 'xyz_wxyz'), 'direct': channel(xyzw, 'xyz_xyzw'),
            'batch': channel(xyzw[::-1], 'xyz_xyzw')}, 'comparisons': {}},
        'scene_before': scene, 'scene_after': copy.deepcopy(scene), 'control_commands': 0,
        'initialized_bricks': 300, 'initializer_source_snapshot': audit.INITIALIZER, 'manifest_sha256': 'invented'}
    summaries(data)
    return data


def summaries(data):
    p = data['pose_readers']
    for key, a, b in [('cached_direct', 'cached', 'direct'), ('cached_batch', 'cached', 'batch'), ('direct_batch', 'direct', 'batch')]:
        p['comparisons'][key] = audit.pair_errors(p['channels'][a]['poses_world_wxyz'], p['channels'][b]['poses_world_wxyz'])


class DiagnosticAuditTests(unittest.TestCase):
    def test_actual_v2_confirmation_bound_to_three_channels(self):
        data = fixture(); capture = data['pose_readers']; channels = capture['channels']
        cached = channels['cached']; cached['raw_poses'][0][2] = cached['poses_world_wxyz'][0][2] = 4e-9
        summaries(data)
        proof = {key: copy.deepcopy(capture[key]) for key in ['names', 'expected_root_paths',
            'actual_view_prim_paths', 'row_indices_in_name_order', 'count', 'subspace_roots', 'frame']}
        proof.update(proof_version=2, reference_reader='fresh_per_asset_PhysX_get_transforms',
            getter_layout='xyz_xyzw', returned_layout='xyz_wxyz', snapshot_copy=True,
            no_step_called_by_reader=True, clock_before_s=.001, clock_after_s=.001,
            position_tolerance_m=1e-9, angle_tolerance_rad=1e-7, equivalence_passed=True,
            maximum_position_error_m=0., maximum_angle_error_rad=0.,
            direct_raw_poses_world_xyzw=channels['direct']['raw_poses'],
            direct_poses_world_wxyz=channels['direct']['poses_world_wxyz'],
            batch_raw_poses_world_xyzw=channels['batch']['raw_poses'],
            cached_poses_world_wxyz=cached['poses_world_wxyz'],
            cached_direct_comparison=capture['comparisons']['cached_direct'],
            cached_batch_comparison=capture['comparisons']['cached_batch'],
            new_poses_world_wxyz=channels['batch']['poses_world_wxyz'])
        record = {'proof': proof, 'initial': {'names': capture['names'],
            'poses_world_wxyz': channels['batch']['poses_world_wxyz']},
            'physics_time_before_s': .001, 'physics_time_after_s': .001,
            'physics_step_before': 1, 'physics_step_after': 1, 'control_commands': 0}
        self.assertTrue(all(audit.confirmation_checks(data, record, old_audit.startup_getter_proof).values()))
        for mutate in [lambda r: r.update(physics_step_after=2),
                lambda r: r['initial']['poses_world_wxyz'][0].__setitem__(0, .001),
                lambda r: r['proof']['direct_raw_poses_world_xyzw'][0].__setitem__(0, .001)]:
            wrong = copy.deepcopy(record); mutate(wrong)
            self.assertFalse(all(audit.confirmation_checks(data, wrong, old_audit.startup_getter_proof).values()))

    def test_copied_file_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'reader.py'; source.write_text('# invented source\n')
            hashes = {'reader.py': audit.digest(source)}
            self.assertTrue(audit.copied_sources_match(root, hashes))
            self.assertFalse(audit.copied_sources_match(root, {}))
            self.assertFalse(audit.copied_sources_match(root, {'../reader.py': hashes['reader.py']}))
            source.write_text('# changed\n')
            self.assertFalse(audit.copied_sources_match(root, hashes))
            source.unlink(); self.assertFalse(audit.copied_sources_match(root, hashes))

    def test_all_equivalent_with_nontrivial_quaternion_and_permutation(self):
        result = audit.evaluate(fixture())
        self.assertTrue(result['diagnostic_complete']); self.assertTrue(result['all_readers_equivalent'])
        self.assertEqual(result['reader_status'], 'ALL_READERS_EQUIVALENT')
        self.assertFalse(result['absolute_pose_accuracy_verified'])
        json.dumps(result, allow_nan=False)

    def test_cache_discrepancy_is_complete_diagnostic_not_equality_pass(self):
        data = fixture(); cached = data['pose_readers']['channels']['cached']
        cached['raw_poses'][0][2] = cached['poses_world_wxyz'][0][2] = .0002
        summaries(data); result = audit.evaluate(data)
        self.assertTrue(result['diagnostic_complete']); self.assertFalse(result['all_readers_equivalent'])
        self.assertEqual(result['reader_status'], 'CACHE_ONLY_DISCREPANCY')
        self.assertTrue(result['fresh_direct_batch_equivalent'])

    def test_fresh_discrepancy_remains_unknown_pose_truth(self):
        data = fixture(); direct = data['pose_readers']['channels']['direct']
        direct['raw_poses'][0][2] = direct['poses_world_wxyz'][0][2] = .0002
        summaries(data); result = audit.evaluate(data)
        self.assertTrue(result['diagnostic_complete'])
        self.assertEqual(result['reader_status'], 'DIRECT_BATCH_MISMATCH')
        self.assertFalse(result['fresh_direct_batch_equivalent'])
        self.assertFalse(result['corrected_check_automatically_authorized'])

    def test_clock_mapping_conversion_graph_and_false_summary_rejected(self):
        for mutate in [
            lambda d: d['scene_after'].update(physics_time_s=.002),
            lambda d: d['scene_after'].update(physics_step_index=2),
            lambda d: d['scene_after'].update(physics_step_index=True),
            lambda d: d['pose_readers'].update(row_indices_in_name_order=list(range(300))),
            lambda d: d['pose_readers']['channels']['direct']['raw_poses'][0].__setitem__(3, 0.),
            lambda d: d['scene_after']['native_connections_paths'].pop(),
            lambda d: d['pose_readers']['comparisons']['direct_batch'].update(passed=False),
        ]:
            data = fixture(); mutate(data); result = audit.evaluate(data)
            self.assertFalse(result['diagnostic_complete']); self.assertEqual(result['reader_status'], 'UNKNOWN')
            self.assertFalse(result['all_readers_equivalent'])


if __name__ == '__main__': unittest.main()

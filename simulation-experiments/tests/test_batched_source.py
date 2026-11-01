"""Invented tensor-buffer/path tests; no actual Tensor API or scene."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

SOURCE=Path(__file__).resolve().parents[1]/'experiments/control_alignment_20261026/batched_source.py'
spec=importlib.util.spec_from_file_location('batched_source_test_module',SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Tensor:
    def __init__(self,array):self.array=array
    def __getitem__(self,index):return Tensor(self.array[index])
    def detach(self):return self
    def cpu(self):return self
    def numpy(self):return self.array


def fixture(paths=None):
    names=['brick_a','brick_b','brick_c'];expected=['/World/'+n for n in names]
    old=np.array([[1.,2.,3.,1.,0.,0.,0.],[4.,5.,6.,1.,0.,0.,0.],[7.,8.,9.,1.,0.,0.,0.]],np.float32)
    scene={name:SimpleNamespace(root_physx_view=SimpleNamespace(prim_paths=[path]),data=SimpleNamespace(root_link_pose_w=Tensor(old[i:i+1]))) for i,(name,path) in enumerate(zip(names,expected))}
    for i,name in enumerate(names):
        actor=old[i:i+1][:,[0,1,2,4,5,6,3]].copy()
        scene[name].root_physx_view.get_transforms=lambda actor=actor:Tensor(actor)
        scene[name].data._root_link_pose_w=SimpleNamespace(timestamp=.001,data=scene[name].data.root_link_pose_w)
        scene[name].data._sim_timestamp=.001
    actual=[expected[2],expected[0],expected[1]] if paths is None else paths
    raw=np.array([[7.,8.,9.,0.,0.,0.,-1.],[1.,2.,3.,0.,0.,0.,1.],[4.,5.,6.,0.,0.,0.,1.]],np.float32)
    view=SimpleNamespace(prim_paths=actual,count=len(actual),get_transforms=lambda:Tensor(raw))
    calls=[]
    simulation=SimpleNamespace(set_subspace_roots=lambda value:calls.append(('roots',value)),
        create_rigid_body_view=lambda value:(calls.append(('paths',value)) or view))
    tensor_api=SimpleNamespace(create_simulation_view=lambda frontend:(calls.append(('frontend',frontend)) or simulation))
    omni=ModuleType('omni');physics=ModuleType('omni.physics');physics.tensors=tensor_api;omni.physics=physics
    return names,scene,raw,view,calls,{'omni':omni,'omni.physics':physics,'omni.physics.tensors':tensor_api}


class BatchedTests(unittest.TestCase):
    def test_three_channel_capture_keeps_mismatches_and_raw_order(self):
        names,scene,raw,view,calls,modules=fixture()
        scene[names[0]].data.root_link_pose_w.array[0,0]+=.001
        with patch.dict(sys.modules,modules):proof=module.capture_startup_comparison(scene,names,lambda:.001)
        self.assertEqual(proof['schema'],'pose-reader-startup-v1')
        self.assertFalse(proof['comparisons']['cached_direct']['passed'])
        self.assertFalse(proof['comparisons']['cached_batch']['passed'])
        self.assertTrue(proof['comparisons']['direct_batch']['passed'])
        self.assertEqual(proof['channels']['batch']['raw_poses'][0][0],7.)
        self.assertEqual(proof['channels']['batch']['poses_world_wxyz'][0][0],1.)
        self.assertEqual(proof['channels']['cached']['cache_timestamp_before'],[.001]*3)
        for channel in proof['channels'].values():
            self.assertEqual(channel['clock_before_s'],.001);self.assertEqual(channel['clock_after_s'],.001)
            self.assertEqual(channel['raw_dtype'],'float32')
        old=proof['channels']['batch']['raw_poses'][0][0];raw[:]=99
        self.assertEqual(proof['channels']['batch']['raw_poses'][0][0],old)

    def test_three_channel_capture_detects_direct_batch_disagreement(self):
        names,scene,raw,view,calls,modules=fixture();raw[1,0]+=.002
        with patch.dict(sys.modules,modules):proof=module.capture_startup_comparison(scene,names,lambda:4.)
        self.assertTrue(proof['comparisons']['cached_direct']['passed'])
        self.assertFalse(proof['comparisons']['direct_batch']['passed'])
        self.assertEqual(len(proof['channels']['direct']['raw_poses']),3)

    def test_partial_sink_precedes_path_guard_and_is_copied(self):
        names,scene,raw,view,calls,modules=fixture(['/World/brick_a','/World/brick_a','/World/brick_c'])
        evidence=[]
        with patch.dict(sys.modules,modules):
            with self.assertRaises(RuntimeError):module.capture_startup_comparison(scene,names,lambda:.001,evidence.append)
        self.assertEqual([p['capture_stage'] for p in evidence],['cached_raw','direct_raw','batch_raw_before_path_validation'])
        final=evidence[-1];self.assertEqual(final['actual_view_prim_paths'],view.prim_paths)
        self.assertEqual(final['channels']['batch']['raw_poses'][0][0],7.)
        raw[:]=123;self.assertEqual(final['channels']['batch']['raw_poses'][0][0],7.)
        self.assertEqual(set(evidence[0]['channels']),{'cached'})

    def test_cache_metadata_before_after_read_and_nonfinite_partial(self):
        names,scene,raw,view,calls,modules=fixture()
        value=scene[names[0]].data.root_link_pose_w
        class LazyData:
            def __init__(self):self._sim_timestamp=.001;self._root_link_pose_w=SimpleNamespace(timestamp=-1.,data=None)
            @property
            def root_link_pose_w(self):
                self._root_link_pose_w.timestamp=self._sim_timestamp;self._root_link_pose_w.data=value
                return value
        scene[names[0]].data=LazyData()
        with patch.dict(sys.modules,modules):proof=module.capture_startup_comparison(scene,names,lambda:.001)
        cached=proof['channels']['cached']
        self.assertEqual(cached['cache_buffer_present_before'],[False,True,True])
        self.assertEqual(cached['cache_timestamp_before'],[-1.,.001,.001])
        self.assertEqual(cached['cache_timestamp_after'],[.001]*3)
        raw[0,0]=float('nan');evidence=[]
        with patch.dict(sys.modules,modules):
            with self.assertRaises(RuntimeError):module.capture_startup_comparison(scene,names,lambda:.001,evidence.append)
        self.assertEqual(evidence[-1]['channels']['batch']['raw_poses'][0][0],{'nonfinite_scalar':'nan'})

    def test_actual_path_permutation_world_frame_and_sign(self):
        names,scene,raw,view,calls,modules=fixture()
        with patch.dict(sys.modules,modules):reader=module.BatchedSourcePoses(scene,list(reversed(names)))
        self.assertEqual(reader.proof['names'],names);self.assertEqual(reader.proof['row_indices_in_name_order'],[1,2,0])
        self.assertEqual(calls,[('frontend','torch'),('roots','/'),('paths',['/World/'+n for n in names])])
        self.assertTrue(reader.proof['equivalence_passed']);self.assertEqual(reader.proof['maximum_angle_error_rad'],0.)
        self.assertEqual(reader.proof['proof_version'],2)
        self.assertEqual(reader.proof['reference_reader'],'fresh_per_asset_PhysX_get_transforms')
        self.assertNotIn('old_reader',reader.proof);self.assertNotIn('old_poses_world_wxyz',reader.proof)
        np.testing.assert_array_equal(reader.read()[:,0],[1,4,7])
        np.testing.assert_array_equal(reader.read()[2,3:],[-1,0,0,0])  # Preserve raw quaternion sign.

    def test_snapshots_do_not_alias_reused_tensor_buffer(self):
        names,scene,raw,view,calls,modules=fixture()
        with patch.dict(sys.modules,modules):reader=module.BatchedSourcePoses(scene,names)
        first=reader.read();proof=np.asarray(reader.proof['new_poses_world_wxyz']).copy();raw[:,0]+=100
        np.testing.assert_array_equal(first[:,0],[1,4,7]);np.testing.assert_array_equal(proof[:,0],[1,4,7])
        np.testing.assert_array_equal(reader.read()[:,0],[101,104,107])
        first[:]=99;np.testing.assert_array_equal(reader.read()[:,0],[101,104,107])

    def test_missing_duplicate_actor_paths_rejected(self):
        for paths in (['/World/brick_a','/World/brick_a','/World/brick_c'],['/World/brick_a','/World/brick_b'],['/World/brick_a','/World/brick_b','/World/other']):
            names,scene,raw,view,calls,modules=fixture(paths)
            with patch.dict(sys.modules,modules):
                with self.assertRaises(RuntimeError):module.BatchedSourcePoses(scene,names)
        names,scene,raw,view,calls,modules=fixture();scene[names[1]].root_physx_view.prim_paths=['/World/brick_a']
        with patch.dict(sys.modules,modules):
            with self.assertRaises(RuntimeError):module.BatchedSourcePoses(scene,names)
            with self.assertRaises(ValueError):module.BatchedSourcePoses(scene,[names[0],names[0]])

    def test_startup_discrepancy_and_invalid_readback(self):
        for mutation in ('position','angle','nan','zero'):
            names,scene,raw,view,calls,modules=fixture()
            if mutation=='position':raw[1,0]+=.001
            elif mutation=='angle':raw[1,3]=1e-5
            elif mutation=='nan':raw[0,0]=float('nan')
            else:raw[0,3:]=0
            with patch.dict(sys.modules,modules):
                with self.assertRaises(RuntimeError):module.BatchedSourcePoses(scene,names)
        q=np.array([[1.,0.,0.,0.],[0.,1.,0.,0.]])
        np.testing.assert_allclose(module.quaternion_angles(q,-q),0,atol=0)

    def test_failed_equivalence_preserves_independent_proof(self):
        names,scene,raw,view,calls,modules=fixture();raw[1,0]+=.001
        with patch.dict(sys.modules,modules):
            with self.assertRaises(module.SourcePoseEquivalenceError) as captured:
                module.BatchedSourcePoses(scene,names)
        proof=captured.exception.proof
        self.assertFalse(proof['equivalence_passed']);self.assertGreater(proof['maximum_position_error_m'],1e-9)
        self.assertEqual(proof['names'],names);self.assertEqual(proof['row_indices_in_name_order'],[1,2,0])
        self.assertEqual(len(proof['direct_poses_world_wxyz']),3);self.assertEqual(len(proof['cached_poses_world_wxyz']),3)
        self.assertEqual(len(proof['direct_raw_poses_world_xyzw']),3);self.assertEqual(len(proof['batch_raw_poses_world_xyzw']),3)
        self.assertEqual(len(proof['new_poses_world_wxyz']),3)
        before=proof['new_poses_world_wxyz'][0][0];raw[:]=99
        self.assertEqual(proof['new_poses_world_wxyz'][0][0],before)

    def test_cache_only_float32_ulp_discrepancy_is_retained_not_gating(self):
        names,scene,raw,view,calls,modules=fixture()
        fresh=np.float32(.032);cached=np.nextafter(fresh,np.float32(np.inf))
        scene[names[0]].data.root_link_pose_w.array[0,0]=cached
        scene[names[0]].root_physx_view.get_transforms().array[0,0]=fresh
        raw[1,0]=fresh
        with patch.dict(sys.modules,modules):reader=module.BatchedSourcePoses(scene,names)
        proof=reader.proof
        self.assertTrue(proof['equivalence_passed']);self.assertEqual(proof['maximum_position_error_m'],0.)
        self.assertEqual(proof['maximum_angle_error_rad'],0.)
        self.assertFalse(proof['cached_direct_comparison']['passed']);self.assertFalse(proof['cached_batch_comparison']['passed'])
        self.assertEqual(proof['cached_direct_comparison']['maximum_position_error_m'],float(cached)-float(fresh))
        self.assertEqual(proof['cached_poses_world_wxyz'][0][0],float(cached))
        self.assertEqual(proof['direct_poses_world_wxyz'][0][0],float(fresh))
        np.testing.assert_array_equal(reader.read()[:,0],[fresh,4,7])
        raw[1,0]=cached  # The SAME nanometer difference between fresh APIs must fail.
        with patch.dict(sys.modules,modules):
            with self.assertRaises(module.SourcePoseEquivalenceError) as captured:
                module.BatchedSourcePoses(scene,names)
        failed=captured.exception.proof
        self.assertFalse(failed['equivalence_passed'])
        self.assertEqual(failed['maximum_position_error_m'],float(cached)-float(fresh))
        self.assertTrue(failed['cached_batch_comparison']['passed'])


if __name__=='__main__':unittest.main()

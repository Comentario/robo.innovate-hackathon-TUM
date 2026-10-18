from copy import deepcopy
import unittest
from arm_bridge.scene_state import scene_digest,require_same_scene,same_pose,compose_poses


class ReferenceSceneTests(unittest.TestCase):
    def setUp(self):
        self.scene={'joints':{'panda_joint1':.1},'objects':{'stamp':{'header':{'frame_id':'world','stamp':{'sec':1,'nanosec':0}},'pose':[.4,.1,.12]}},'attached':[],'collision_matrix':{'pairs':[False,True]}}

    def test_timestamps_do_not_hide_geometry_joints_attachments_or_collision_policy(self):
        baseline=scene_digest(self.scene)
        changed=deepcopy(self.scene);changed['objects']['stamp']['header']['stamp']['sec']=99
        self.assertEqual(scene_digest(changed),baseline)
        for kind in ('object','joint','attachment','policy'):
            changed=deepcopy(self.scene)
            if kind=='object':changed['objects']['stamp']['pose'][0]+=.01
            elif kind=='joint':changed['joints']['panda_joint1']+=.02
            elif kind=='attachment':changed['attached']=['held_brick']
            else:changed['collision_matrix']['pairs'][0]=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):require_same_scene(changed,baseline)

    def test_object_and_primitive_poses_compose_rotated_offsets(self):
        root={'position_m':[.4,.2,.1],'orientation_xyzw':[0.,0.,1.,0.]}
        local={'position_m':[.03,.01,.02],'orientation_xyzw':[0.,0.,0.,1.]}
        result=compose_poses(root,local)
        for actual,expected in zip(result['position_m'],[.37,.19,.12]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(result['orientation_xyzw'],root['orientation_xyzw'])

    def test_pose_comparison_checks_quaternion_sign_and_finite_geometry(self):
        p={'position_m':[.4,0.,.12],'orientation_xyzw':[0.,0.,0.,1.]}
        q=deepcopy(p);q['orientation_xyzw']=[0.,0.,0.,-1.]
        self.assertTrue(same_pose(p,q))
        q['position_m'][0]+=.02;self.assertFalse(same_pose(p,q))
        for bad in (float('nan'),float('inf')):
            q=deepcopy(p);q['position_m'][0]=bad;self.assertFalse(same_pose(p,q))
        q=deepcopy(p);q['orientation_xyzw']=[0.,0.,0.,2.];self.assertFalse(same_pose(p,q))


if __name__=='__main__':unittest.main()

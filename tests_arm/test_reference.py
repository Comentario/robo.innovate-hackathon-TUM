"""Optional ROS message tests: transforms and collision-policy preservation."""
import math
import unittest
from types import SimpleNamespace
from moveit_msgs.msg import AllowedCollisionMatrix, AllowedCollisionEntry
from arm_bridge.adapter import hand_goal, MoveItAdapter, TOUCH


class ReferenceTests(unittest.TestCase):
    def test_object_center_maps_to_downward_hand_for_both_upright_faces(self):
        for q in ([0,0,0,1],[0,0,1,0]):
            p=hand_goal(dict(position_m=[.4,-.2,.12],orientation_xyzw=q),offset=.11)
            self.assertAlmostEqual(p.position.z,.23)
            self.assertAlmostEqual(p.position.x,.4)
            # Quaternion rotates local hand Z onto world -Z.
            x,y,z,w=p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w
            self.assertAlmostEqual(1-2*(x*x+y*y),-1.)
            self.assertAlmostEqual(x*x+y*y+z*z+w*w,1.)

    def test_grasp_contacts_preserve_existing_robot_pairs_and_exclude_other_bricks(self):
        names=['panda_link6',*TOUCH]
        initial=[[a!=b for b in names] for a in names]
        matrix=AllowedCollisionMatrix(entry_names=names,entry_values=[AllowedCollisionEntry(enabled=row) for row in initial])
        scenes=[]
        harness=SimpleNamespace(objects={'selected':{},'other':{}},get_scene=None,
            call=lambda *_:SimpleNamespace(scene=SimpleNamespace(allowed_collision_matrix=matrix)),scene=scenes.append)
        MoveItAdapter.contacts(harness,'selected')
        result=scenes[-1].allowed_collision_matrix
        for i,a in enumerate(names):
            for j,b in enumerate(names):
                self.assertEqual(result.entry_values[result.entry_names.index(a)].enabled[result.entry_names.index(b)],initial[i][j])
        for finger in TOUCH:
            i=result.entry_names.index(finger)
            self.assertTrue(result.entry_values[i].enabled[result.entry_names.index('selected')])
            self.assertFalse(result.entry_values[i].enabled[result.entry_names.index('other')])
        matrix=result
        MoveItAdapter.contacts(harness,'other')
        result=scenes[-1].allowed_collision_matrix
        for finger in TOUCH:
            i=result.entry_names.index(finger)
            self.assertFalse(result.entry_values[i].enabled[result.entry_names.index('selected')])
            self.assertTrue(result.entry_values[i].enabled[result.entry_names.index('other')])


if __name__=='__main__':unittest.main()

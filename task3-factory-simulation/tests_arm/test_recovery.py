from copy import deepcopy
from types import SimpleNamespace
import unittest
from sensor_msgs.msg import JointState
from moveit_msgs.msg import PlanningScene,AttachedCollisionObject
from arm_bridge.adapter import MoveItAdapter,JOINTS,FINGERS,READY,box


class ReferenceRecoveryTests(unittest.TestCase):
    def scene(self):
        scene=PlanningScene()
        scene.robot_state.joint_state=JointState(name=JOINTS+FINGERS,position=[.2,-.8,.1,-2.1,.2,1.5,.7,.04,.04])
        pose={'position_m':[.4,.1,.12],'orientation_xyzw':[0,0,0,1]}
        scene.world.collision_objects=[box('a',[.06,.025,.02],pose)]
        return scene,pose

    def test_restore_reads_live_joints_and_geometry_without_initializing_the_scene(self):
        scene,pose=self.scene()
        writes=[]
        harness=SimpleNamespace(objects={'a':{'position_m':[.3,-.2,.12],'orientation_xyzw':[0,0,0,1]}},job={'cell':{'brick_size_m':[.06,.025,.02]}},positions=READY+[.04,.04],object_pose=MoveItAdapter.object_pose,scene=writes.append)
        MoveItAdapter.restore_from_scene(harness,scene)
        self.assertEqual(harness.positions,list(scene.robot_state.joint_state.position))
        self.assertEqual(harness.objects['a'],pose);self.assertIsNone(harness.held);self.assertEqual(writes,[])
        scene.world.collision_objects=[]
        with self.assertRaises(ValueError):MoveItAdapter.restore_from_scene(harness,scene)

    def test_moveit_exported_object_pose_is_not_mistaken_for_origin(self):
        scene,pose=self.scene();obj=scene.world.collision_objects[0]
        obj.pose=obj.primitive_poses[0]
        from geometry_msgs.msg import Pose
        obj.primitive_poses=[Pose()];obj.primitive_poses[0].orientation.w=1.
        self.assertEqual(MoveItAdapter.object_pose(obj),pose)
        obj.pose.orientation.w=0.;obj.pose.orientation.z=1.
        obj.primitive_poses[0].position.x=.02
        self.assertAlmostEqual(MoveItAdapter.object_pose(obj)['position_m'][0],.38)

    def test_held_closed_or_changed_robot_never_passes_the_empty_gripper_gate(self):
        scene,_=self.scene()
        harness=SimpleNamespace(positions=list(scene.robot_state.joint_state.position),motion=None,held=None,is_valid=lambda:True)
        MoveItAdapter.require_empty_stopped_robot(harness,scene)
        for kind in ('attached','closed','changed','moving','collision'):
            trial=deepcopy(scene);h=SimpleNamespace(**vars(harness))
            if kind=='attached':trial.robot_state.attached_collision_objects=[AttachedCollisionObject(link_name='panda_hand')]
            elif kind=='closed':trial.robot_state.joint_state.position[-1]=.01
            elif kind=='changed':trial.robot_state.joint_state.position[0]+=.1
            elif kind=='moving':h.motion=True
            else:h.is_valid=lambda:False
            with self.subTest(kind=kind),self.assertRaises(ValueError):MoveItAdapter.require_empty_stopped_robot(h,trial)

class ReferenceGoalTests(unittest.TestCase):
    def test_collision_valid_ik_goal_is_used_and_failed_plans_are_never_played(self):
        from moveit_msgs.srv import GetPositionIK,GetMotionPlan
        from moveit_msgs.msg import RobotState
        from geometry_msgs.msg import Pose
        calls=[];plans=[]
        def call(client,request,**kwargs):
            calls.append(client)
            if client=='ik':
                self.assertTrue(request.ik_request.avoid_collisions)
                response=GetPositionIK.Response();response.error_code.val=1
                response.solution.joint_state.name=JOINTS
                response.solution.joint_state.position=list(READY)
                return response
            plans.append(request.motion_plan_request)
            response=GetMotionPlan.Response();response.motion_plan_response.error_code.val=99999 if len(plans)==1 else 1
            self.assertEqual(len(request.motion_plan_request.goal_constraints[0].joint_constraints),7)
            return response
        harness=SimpleNamespace(ik='ik',plan='plan',is_valid=lambda:True,state=lambda:RobotState(),call=call)
        trajectory,code=MoveItAdapter.plan_to(harness,Pose())
        self.assertEqual(code,1);self.assertIsNotNone(trajectory)
        self.assertEqual(calls,['ik','plan','ik','plan'])

class ReferenceJournalTests(unittest.TestCase):
    def setUp(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from execution import SimulatedAdapter
        from integration import prepare
        from integration.journal import Journal
        from integration.recovery import assess_recovery,basis_digest
        from integration.validation import plan_digest
        root=Path(__file__).resolve().parents[1];read=lambda p:json.loads((root/p).read_text())
        snapshot,plan,job=prepare(read('examples/perception/snapshot.json'),read('examples/faces/config.json'),read('config/cell_panda.json'))
        self.tmp=tempfile.TemporaryDirectory();self.journal=Journal(Path(self.tmp.name)/'reference.sqlite3')
        class ReferenceStop(SimulatedAdapter):backend='panda_moveit_kinematic'
        parent=self.journal.create(snapshot,job,ReferenceStop(5,'approach_pick',True))
        while parent.session.status not in ('stopped','completed'):parent.advance()
        self.row=self.journal.inspect(parent.run_id);placed=deepcopy(plan['placements'][:4]);ids={p['brick_id'] for p in placed}
        self.observation=dict(schema_version='cell-reconciliation-0.1',run_id=parent.run_id,plan_digest=plan_digest(plan),basis_digest=basis_digest(self.row),observation_id='reference-test',source='synthetic',coverage='complete',gripper={'state':'empty'},robot={'state':'safe_home'},placements=placed,inventory=[b for b in snapshot['items'] if b['id'] not in ids],missing_ids=[],frame='world',units='m',source_poses={bid:p for bid,p in job['source_poses'].items() if bid not in ids},robot_scene_digest='scene-token')
        self.proposal=assess_recovery(self.row,self.observation)
        self.adapter=MagicMock(spec=MoveItAdapter);self.adapter.mode='simulation_only';self.adapter.backend='panda_moveit_kinematic'
        self.adapter.verify_recovery_scene.return_value={'scene_digest':'scene-token','physical_validation':False}

    def tearDown(self):self.journal.close();self.tmp.cleanup()

    def prepared(self,status='succeeded',token='scene-token'):
        import json
        self.journal.db.execute('INSERT OR REPLACE INTO reference_preparations VALUES(?,?,?,?)',(self.row['run_id'],status,self.proposal['basis_digest'],json.dumps({'after_scene_digest':token})))

    def recover(self):
        return self.journal.recover_reference_simulation(self.row['run_id'],self.observation,self.adapter,expected_proposal_digest=self.proposal['proposal_digest'])

    def test_durable_preparation_and_live_scene_validation_are_mandatory(self):
        for status,token in [(None,None),('pending','scene-token'),('succeeded','changed')]:
            if status:self.prepared(status,token)
            with self.assertRaises(ValueError):self.recover()
        self.prepared();self.adapter.verify_recovery_scene.side_effect=ValueError('scene changed')
        with self.assertRaisesRegex(ValueError,'scene changed'):self.recover()
        self.assertEqual(self.journal.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)
        self.assertEqual(self.journal.inspect(self.row['run_id']),self.row)
        self.adapter.activate_recovery.assert_not_called()

    def test_reference_child_keeps_robot_backend_and_requires_activation(self):
        from execution import SimulatedAdapter
        self.prepared();child=self.recover()
        self.assertEqual(child.session.job['execution_backend'],'panda_moveit_kinematic')
        self.assertEqual(len(child.session.confirmed),4);self.assertEqual(len(child.session.job['commands']),64)
        self.adapter.verify_recovery_scene.assert_called_once()
        self.adapter.activate_recovery.assert_called_once()
        self.assertEqual(self.journal.inspect(child.run_id)['status'],'ready')
        with self.assertRaises(ValueError):self.journal.resume_simulation(child.run_id,SimulatedAdapter())

    def test_activation_failure_leaves_the_child_stopped_without_dispatch(self):
        self.prepared();self.adapter.activate_recovery.side_effect=ValueError('activation scene changed')
        with self.assertRaisesRegex(ValueError,'activation scene changed'):self.recover()
        row=self.journal.inspect(self.journal.latest_run_id())
        self.assertEqual(row['status'],'stopped');self.assertEqual(row['checkpoint']['cursor'],0)
        self.assertEqual(len(row['checkpoint']['confirmed']),4);self.assertIsNone(row['pending'])
        self.assertEqual(self.journal.inspect(self.row['run_id'])['checkpoint'],self.row['checkpoint'])


if __name__=='__main__':unittest.main()

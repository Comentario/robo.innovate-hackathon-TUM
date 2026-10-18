"""Collision-checked MoveIt paths with kinematic playback, never hardware control."""
from copy import deepcopy
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import JointState
from geometry_msgs.msg import Pose
from shape_msgs.msg import SolidPrimitive
from moveit_msgs.msg import (PlanningScene, CollisionObject, AttachedCollisionObject,
    AllowedCollisionEntry, PlanningSceneComponents, Constraints, PositionConstraint, OrientationConstraint, BoundingVolume)
from moveit_msgs.srv import ApplyPlanningScene, GetMotionPlan, GetStateValidity, GetPositionFK, GetPlanningScene, GetPositionIK
from visualization_msgs.msg import Marker, MarkerArray
from execution import ActionResult

JOINTS=[f'panda_joint{i}' for i in range(1,8)]
FINGERS=['panda_finger_joint1','panda_finger_joint2']
TOUCH=['panda_hand','panda_leftfinger','panda_rightfinger']
READY=[0.,-.785,0.,-2.356,0.,1.571,.785]
# Brick center is 103.4 mm along hand +Z. Reference grasp, not calibration.
GRASP_OFFSET=.1034
COLORS={'dark':(.44,.26,.18),'medium':(.70,.44,.28),'light':(.91,.77,.58)}


def geometry_pose(value):
    p=Pose()
    p.position.x,p.position.y,p.position.z=map(float,value['position_m'])
    p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w=map(float,value['orientation_xyzw'])
    return p


def hand_goal(value,offset=GRASP_OFFSET):
    """Keep the object upright and point hand +Z downward; yaw follows the brick."""
    p=geometry_pose(value)
    p.position.z+=offset
    q=value['orientation_xyzw']
    yaw=2*math.atan2(q[2],q[3])
    p.orientation.x,p.orientation.y=math.cos(yaw/2),math.sin(yaw/2)
    p.orientation.z,p.orientation.w=0.,0.
    return p


def box(name,size,value,frame='world'):
    obj=CollisionObject(id=name)
    obj.header.frame_id=frame
    obj.primitives=[SolidPrimitive(type=SolidPrimitive.BOX,dimensions=list(map(float,size)))]
    obj.primitive_poses=[geometry_pose(value)]
    obj.operation=CollisionObject.ADD
    return obj


class MoveItAdapter(Node):
    mode='simulation_only'
    backend='panda_moveit_kinematic'

    def __init__(self,job,*,speed=4.):
        super().__init__('munich_reference_arm')
        self.job=deepcopy(job)
        self.speed=speed
        self.reference=job['cell']['reference_arm']
        self.grasp_offset=float(self.reference['grasp_offset_m'])
        if not math.isfinite(self.grasp_offset) or self.grasp_offset<=0:raise ValueError('invalid grasp offset')
        if job['frame']!='world' or job['cell']['brick_size_m'][1]>.08:raise ValueError('reference adapter requires world frame and a brick width within 80 mm')
        self.positions=READY+[.04,.04]
        self.joints=self.create_publisher(JointState,'/joint_states',10)
        self.markers=self.create_publisher(MarkerArray,'/munich_arm/markers',QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.apply=self.create_client(ApplyPlanningScene,'/apply_planning_scene')
        self.plan=self.create_client(GetMotionPlan,'/plan_kinematic_path')
        self.valid=self.create_client(GetStateValidity,'/check_state_validity')
        self.fk=self.create_client(GetPositionFK,'/compute_fk')
        self.ik=self.create_client(GetPositionIK,'/compute_ik')
        self.get_scene=self.create_client(GetPlanningScene,'/get_planning_scene')
        self.held=None
        self.objects=deepcopy(job['source_poses'])
        self.placed=set()
        self.evidence=[]
        self.last_pose=None
        for client in (self.apply,self.plan,self.valid,self.fk,self.get_scene,self.ik):
            if not client.wait_for_service(timeout_sec=20.):raise RuntimeError('MoveIt service unavailable; start scripts/arm_demo.sh launch')
        request=GetPlanningScene.Request()
        request.components.components=PlanningSceneComponents.WORLD_OBJECT_NAMES | PlanningSceneComponents.ROBOT_STATE_ATTACHED_OBJECTS
        previous=self.call(self.get_scene,request).scene
        if previous.world.collision_objects or previous.robot_state.attached_collision_objects:
            raise RuntimeError('reference scene is occupied; inspect its journal and restart the synthetic server before a new cycle')
        self.timer=self.create_timer(.04,self.publish_state)
        self.publish_state()
        self.spin_for(1.)
        self.initialize_scene()

    def call(self,client,request,timeout=20.):
        future=client.call_async(request)
        rclpy.spin_until_future_complete(self,future,timeout_sec=timeout)
        if not future.done():raise TimeoutError('MoveIt response timed out; no implicit success')
        return future.result()

    def spin_for(self,seconds):
        end=time.monotonic()+seconds
        while rclpy.ok() and time.monotonic()<end:rclpy.spin_once(self,timeout_sec=min(.02,max(0,end-time.monotonic())))

    def publish_state(self):
        msg=JointState()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.name=JOINTS+FINGERS
        msg.position=list(self.positions)
        self.joints.publish(msg)
        self.publish_markers()

    def state(self):
        from moveit_msgs.msg import RobotState
        state=RobotState(is_diff=True)
        state.joint_state.name=JOINTS+FINGERS
        state.joint_state.position=list(self.positions)
        return state

    def scene(self,scene):
        response=self.call(self.apply,ApplyPlanningScene.Request(scene=scene))
        if not response.success:raise RuntimeError('MoveIt did not acknowledge planning scene')

    def initialize_scene(self):
        scene=PlanningScene(is_diff=True)
        size=self.job['cell']['brick_size_m']
        scene.world.collision_objects=[box(bid,size,value) for bid,value in self.objects.items()]
        # Thin supports with a small contact gap to avoid numerical resting collisions.
        for support in self.reference['supports']:
            scene.world.collision_objects.append(box(support['id'],support['size_m'],dict(position_m=support['position_m'],orientation_xyzw=[0,0,0,1])))
        self.scene(scene)
        if not self.is_valid():raise RuntimeError('reference ready state collides with configured scene')

    def is_valid(self):
        response=self.call(self.valid,GetStateValidity.Request(robot_state=self.state(),group_name='panda_arm'))
        if not response.valid:self.get_logger().error(str([(c.contact_body_1,c.contact_body_2) for c in response.contacts]))
        return response.valid

    def contacts(self,bid=None):
        request=GetPlanningScene.Request()
        request.components.components=PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
        matrix=self.call(self.get_scene,request).scene.allowed_collision_matrix
        # Preserve the robot model's existing self-collision policy.
        names=list(matrix.entry_names)
        old={(a,b):matrix.entry_values[i].enabled[j] for i,a in enumerate(names) for j,b in enumerate(names)}
        names+= [name for name in [*self.objects,*TOUCH] if name not in names]
        scene=PlanningScene(is_diff=True)
        scene.allowed_collision_matrix.entry_names=names
        scene.allowed_collision_matrix.entry_values=[]
        for a in names:
            enabled=[]
            for b in names:
                if (a in self.objects and b in TOUCH) or (b in self.objects and a in TOUCH):
                    enabled.append(bool(bid and (a==bid or b==bid)))
                else:enabled.append(old.get((a,b),False))
            scene.allowed_collision_matrix.entry_values.append(AllowedCollisionEntry(enabled=enabled))
        self.scene(scene)

    def attach(self,bid):
        scene=PlanningScene(is_diff=True)
        scene.robot_state.is_diff=True
        obj=box(bid,self.job['cell']['brick_size_m'],dict(position_m=[0,0,self.grasp_offset],orientation_xyzw=[1,0,0,0]),'panda_hand')
        scene.robot_state.attached_collision_objects=[AttachedCollisionObject(link_name='panda_hand',object=obj,touch_links=TOUCH)]
        self.scene(scene)
        self.held=bid

    def detach(self,bid,value):
        scene=PlanningScene(is_diff=True)
        scene.robot_state.is_diff=True
        scene.robot_state.attached_collision_objects=[AttachedCollisionObject(link_name='panda_hand',object=CollisionObject(id=bid,operation=CollisionObject.REMOVE))]
        scene.world.collision_objects=[box(bid,self.job['cell']['brick_size_m'],value)]
        self.scene(scene)
        self.held=None
        self.objects[bid]=deepcopy(value)
        self.placed.add(bid)

    def plan_to(self,goal):
        if not self.is_valid():return None,-10
        request=GetMotionPlan.Request()
        req=request.motion_plan_request
        req.group_name='panda_arm'
        req.pipeline_id='ompl'
        req.planner_id='RRTConnectkConfigDefault'
        req.start_state=self.state()
        req.allowed_planning_time=3.
        req.num_planning_attempts=2
        req.max_velocity_scaling_factor=.3
        req.max_acceleration_scaling_factor=.3
        req.workspace_parameters.header.frame_id='world'
        req.workspace_parameters.min_corner.x=req.workspace_parameters.min_corner.y=-1.
        req.workspace_parameters.max_corner.x=req.workspace_parameters.max_corner.y=req.workspace_parameters.max_corner.z=1.
        pc=PositionConstraint(link_name='panda_hand',weight=1.)
        pc.header.frame_id='world'
        pc.constraint_region=BoundingVolume(primitives=[SolidPrimitive(type=SolidPrimitive.SPHERE,dimensions=[.002])],primitive_poses=[goal])
        oc=OrientationConstraint(link_name='panda_hand',orientation=goal.orientation,absolute_x_axis_tolerance=.02,absolute_y_axis_tolerance=.02,absolute_z_axis_tolerance=.02,weight=1.)
        oc.header.frame_id='world'
        req.goal_constraints=[Constraints(position_constraints=[pc],orientation_constraints=[oc])]
        for _ in range(3):
            response=self.call(self.plan,request,timeout=15.).motion_plan_response
            if response.error_code.val not in (-1,-2):break
        return (response.trajectory if response.error_code.val==1 else None),response.error_code.val

    def playback(self,trajectory):
        joint=trajectory.joint_trajectory
        if not joint.points:raise RuntimeError('MoveIt returned an empty path')
        indexes=[(JOINTS+FINGERS).index(name) for name in joint.joint_names]
        prev=list(self.positions)
        previous_t=0.
        for point in joint.points:
            stamp=point.time_from_start.sec+point.time_from_start.nanosec*1e-9
            duration=max(.01,(stamp-previous_t)/self.speed)
            start=time.monotonic()
            while True:
                fraction=min(1.,(time.monotonic()-start)/duration)
                for index,value in zip(indexes,point.positions):self.positions[index]=prev[index]+fraction*(value-prev[index])
                self.publish_state()
                if fraction>=1.:break
                self.spin_for(.02)
            prev=list(self.positions)
            previous_t=stamp
        self.spin_for(.1)

    def set_gripper(self,width):
        initial=self.positions[-1]
        for i in range(1,7):
            value=initial+(width-initial)*i/6
            self.positions[-2:]=[value,value]
            if not self.is_valid():raise RuntimeError('collision during synthetic gripper motion')
            self.publish_state()
            self.spin_for(.02)

    def perform(self,command):
        phase,bid=command['phase'],command['brick_id']
        if phase=='confirm':
            return ActionResult('succeeded' if bid in self.placed else 'unknown','synthetic_scene_check_only')
        # Only the selected object may contact the reference gripper.
        if phase=='approach_pick':self.contacts(bid)
        goal=hand_goal(command['object_pose'],self.grasp_offset)
        trajectory,code=self.plan_to(goal)
        self.evidence.append(dict(action_id=command['action_id'],phase=phase,brick_id=bid,moveit_error_code=code,path_points=len(trajectory.joint_trajectory.points) if trajectory else 0))
        if trajectory is None:
            from builtin_interfaces.msg import Duration
            request=GetPositionIK.Request()
            request.ik_request.group_name='panda_arm'
            request.ik_request.ik_link_name='panda_hand'
            request.ik_request.robot_state=self.state()
            request.ik_request.pose_stamped.header.frame_id='world'
            request.ik_request.pose_stamped.pose=goal
            request.ik_request.timeout=Duration(sec=2)
            request.ik_request.avoid_collisions=False
            ik=self.call(self.ik,request)
            if ik.error_code.val==1:
                validity=self.call(self.valid,GetStateValidity.Request(robot_state=ik.solution,group_name='panda_arm'))
                self.evidence[-1]['goal_contacts']=[(c.contact_body_1,c.contact_body_2) for c in validity.contacts]
                self.get_logger().error(str(self.evidence[-1]))
            return ActionResult('failed_before_action',f'moveit_plan_rejected:{code}')
        self.playback(trajectory)
        request=GetPositionFK.Request()
        request.header.frame_id='world'
        request.fk_link_names=['panda_hand']
        request.robot_state=self.state()
        fk=self.call(self.fk,request)
        if fk.error_code.val!=1 or not fk.pose_stamped:raise RuntimeError('endpoint FK unavailable after playback')
        actual=fk.pose_stamped[0].pose
        error=math.dist([actual.position.x,actual.position.y,actual.position.z],[goal.position.x,goal.position.y,goal.position.z])
        self.evidence[-1]['endpoint_position_error_m']=error
        if error>.004:raise RuntimeError('endpoint outside reference grasp tolerance')
        self.last_pose=deepcopy(command['object_pose'])
        if phase=='pick':
            self.attach(bid)
            self.set_gripper(self.job['cell']['brick_size_m'][1]/2)
        elif phase=='place':
            self.detach(bid,command['object_pose'])
            self.set_gripper(.04)
        self.publish_state()
        return ActionResult('succeeded','kinematic_playback_only')

    def publish_markers(self):
        result=MarkerArray()
        byid={p['brick_id']:p for p in self.job['plan']['placements']}
        for i,(bid,value) in enumerate(self.objects.items()):
            m=Marker(id=i,ns='bricks',type=Marker.CUBE,action=Marker.ADD)
            m.header.frame_id='world'
            m.pose=geometry_pose(value)
            if bid==self.held:
                m.header.frame_id='panda_hand'
                m.pose=geometry_pose(dict(position_m=[0,0,self.grasp_offset],orientation_xyzw=[1,0,0,0]))
            m.scale.x,m.scale.y,m.scale.z=self.job['cell']['brick_size_m']
            color=COLORS.get(byid.get(bid,{}).get('color_group'),COLORS['medium'])
            m.color.r,m.color.g,m.color.b=color
            m.color.a=1.
            result.markers.append(m)
        for j,support in enumerate(self.reference['supports']):
            m=Marker(id=100+j,ns='stations',type=Marker.CUBE,action=Marker.ADD)
            m.header.frame_id='world'
            m.pose.position.x,m.pose.position.y,m.pose.position.z=support['position_m']
            m.pose.orientation.w=1.
            m.scale.x,m.scale.y,m.scale.z=support['size_m']
            m.color.r,m.color.g,m.color.b,m.color.a=.22,.32,.4,1.
            result.markers.append(m)
        self.markers.publish(result)

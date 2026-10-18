"""Collision-checked MoveIt paths with kinematic playback, never hardware control."""
from copy import deepcopy
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.clock import Clock, ClockType
from .motion import TimedPath
from .scene_state import scene_digest,require_same_scene,same_pose,without_timestamps,compose_poses
from rosidl_runtime_py.convert import message_to_ordereddict
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import JointState
from geometry_msgs.msg import Pose, Point
from shape_msgs.msg import SolidPrimitive
from moveit_msgs.msg import (PlanningScene, CollisionObject, AttachedCollisionObject,
    AllowedCollisionEntry, PlanningSceneComponents, Constraints, PositionConstraint, OrientationConstraint, BoundingVolume, JointConstraint)
from moveit_msgs.srv import ApplyPlanningScene, GetMotionPlan, GetStateValidity, GetPositionFK, GetPlanningScene, GetPositionIK
from visualization_msgs.msg import Marker, MarkerArray
from execution import ActionResult
from execution.cell import CellLayout

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
    obj.pose.orientation.w=1.
    obj.primitives=[SolidPrimitive(type=SolidPrimitive.BOX,dimensions=list(map(float,size)))]
    obj.primitive_poses=[geometry_pose(value)]
    obj.operation=CollisionObject.ADD
    return obj


class MoveItAdapter(Node):
    mode='simulation_only'
    backend='panda_moveit_kinematic'

    def __init__(self,job,*,speed=4.,restore=False,saved_state=None):
        super().__init__('munich_reference_arm')
        self.job=deepcopy(job)
        self.speed=speed
        self.reference=job['cell']['reference_arm']
        self.grasp_offset=float(self.reference['grasp_offset_m'])
        if not math.isfinite(self.grasp_offset) or self.grasp_offset<=0:raise ValueError('invalid grasp offset')
        if job['frame']!='world' or job['cell']['brick_size_m'][1]>.08:raise ValueError('reference adapter requires world frame and a brick width within 80 mm')
        self.positions=READY+[.04,.04]
        self.visual_epoch_ns=time.time_ns()
        self.visual_start_ns=time.monotonic_ns()
        self.motion=None
        self.playback_metrics=[]
        self.joints=self.create_publisher(JointState,'/joint_states',100)
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
        request.components.components=PlanningSceneComponents.WORLD_OBJECT_GEOMETRY | PlanningSceneComponents.ROBOT_STATE | PlanningSceneComponents.ROBOT_STATE_ATTACHED_OBJECTS
        previous=self.call(self.get_scene,request).scene
        if restore:
            if not isinstance(saved_state,dict) or saved_state.get('job_id')!=job['job_id']:raise ValueError('restore requires a checkpoint bound to this reference job')
            previous,semantic=self.capture_scene()
            require_same_scene(semantic,saved_state.get('scene_digest'))
            self.restore_from_scene(previous)
            self.visual_epoch_ns=max(self.visual_epoch_ns,int(saved_state['visual_time_ns']))
            self.visual_start_ns=time.monotonic_ns()
        elif previous.world.collision_objects or previous.robot_state.attached_collision_objects:
            raise RuntimeError('reference scene is occupied; inspect its journal and restart the synthetic server before a new cycle')
        self.timer=self.create_timer(.02,self.publish_state,clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.publish_state()
        self.spin_for(1.)
        if not restore:self.initialize_scene()
        elif not self.is_valid():raise RuntimeError('restored reference state is in collision')

    @staticmethod
    def object_pose(obj):
        if obj.header.frame_id not in ('world','panda_link0') or len(obj.primitives)!=1 or len(obj.primitive_poses)!=1 or obj.meshes or obj.planes or obj.primitives[0].type!=SolidPrimitive.BOX:
            raise ValueError('known reference bricks must be world-frame boxes')
        def value(p):return dict(position_m=[p.position.x,p.position.y,p.position.z],orientation_xyzw=[p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w])
        return compose_poses(value(obj.pose),value(obj.primitive_poses[0]))

    def restore_from_scene(self,scene):
        joints=dict(zip(scene.robot_state.joint_state.name,scene.robot_state.joint_state.position))
        if any(name not in joints or not math.isfinite(joints[name]) for name in JOINTS+FINGERS):
            raise ValueError('live scene does not contain all reference robot joints')
        self.positions=[joints[name] for name in JOINTS+FINGERS]
        world={o.id:o for o in scene.world.collision_objects}
        attached=scene.robot_state.attached_collision_objects
        if len(attached)>1:raise ValueError('multiple attached objects require explicit intervention')
        held=attached[0].object.id if attached else None
        if attached and attached[0].link_name!='panda_hand':raise ValueError('unexpected attachment link')
        for bid in self.objects:
            if bid==held:continue  # rendered in hand frame, never treated as available stock
            if bid not in world:raise ValueError(f'reference brick missing from live scene: {bid}')
            obj=world[bid]
            value=self.object_pose(obj)
            if list(obj.primitives[0].dimensions)!=self.job['cell']['brick_size_m']:raise ValueError('brick dimensions changed')
            self.objects[bid]=value
        if held is not None and held not in self.objects:raise ValueError('unidentified attached object')
        self.held=held
        # No collision object, TF or joint is reset during restoration.

    def capture_scene(self):
        request=GetPlanningScene.Request()
        request.components.components=(PlanningSceneComponents.ROBOT_STATE | PlanningSceneComponents.ROBOT_STATE_ATTACHED_OBJECTS | PlanningSceneComponents.WORLD_OBJECT_GEOMETRY | PlanningSceneComponents.ALLOWED_COLLISION_MATRIX | PlanningSceneComponents.TRANSFORMS | PlanningSceneComponents.OCTOMAP)
        scene=self.call(self.get_scene,request).scene
        joints=dict(zip(scene.robot_state.joint_state.name,scene.robot_state.joint_state.position))
        return scene,dict(joints=joints,objects={o.id:message_to_ordereddict(o) for o in scene.world.collision_objects},attached=[message_to_ordereddict(o) for o in scene.robot_state.attached_collision_objects],collision_matrix=message_to_ordereddict(scene.allowed_collision_matrix),transforms=[message_to_ordereddict(t) for t in scene.fixed_frame_transforms],octomap=message_to_ordereddict(scene.world.octomap))

    def require_empty_stopped_robot(self,scene):
        joints=dict(zip(scene.robot_state.joint_state.name,scene.robot_state.joint_state.position))
        if self.motion is not None or scene.robot_state.attached_collision_objects or self.held is not None:
            raise ValueError('reference recovery requires no active trajectory and no attached object')
        if any(name not in joints or abs(joints[name]-.04)>.0002 for name in FINGERS):raise ValueError('gripper is not verified open')
        if any(name not in joints or abs(joints[name]-value)>1e-5 for name,value in zip(JOINTS+FINGERS,self.positions)):
            raise ValueError('live robot joints differ from restored playback state')
        if not self.is_valid():raise ValueError('reference state is in collision')

    def fk_hand(self):
        request=GetPositionFK.Request();request.header.frame_id='world'
        request.fk_link_names=['panda_hand'];request.robot_state=self.state()
        response=self.call(self.fk,request)
        if response.error_code.val!=1 or not response.pose_stamped:raise ValueError('reference FK unavailable')
        p=response.pose_stamped[0].pose
        return dict(position_m=[p.position.x,p.position.y,p.position.z],orientation_xyzw=[p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w])

    def move_to_recovery_home(self):
        scene,_=self.capture_scene();self.require_empty_stopped_robot(scene)
        goal=hand_goal({'position_m':self.job['cell']['home_m'],'orientation_xyzw':[0,0,0,1]},self.grasp_offset)
        trajectory,code=self.plan_to(goal)
        if trajectory is None:return ActionResult('failed_before_action',f'recovery_home_plan_rejected:{code}')
        self.playback(trajectory)
        if math.dist(self.fk_hand()['position_m'],[goal.position.x,goal.position.y,goal.position.z])>.004:
            raise ValueError('robot did not reach recovery home')
        return ActionResult('succeeded','collision_checked_reference_home')

    def reconciliation(self,row,observation_id):
        from integration.recovery import basis_digest
        from integration.validation import plan_digest
        scene,semantic=self.capture_scene();self.require_empty_stopped_robot(scene)
        home=hand_goal({'position_m':self.job['cell']['home_m'],'orientation_xyzw':[0,0,0,1]},self.grasp_offset)
        expected=dict(position_m=[home.position.x,home.position.y,home.position.z],orientation_xyzw=[home.orientation.x,home.orientation.y,home.orientation.z,home.orientation.w])
        if not same_pose(self.fk_hand(),expected,position_tolerance=.004,angle_tolerance=.04):raise ValueError('reference hand is not at recovery home')
        world={o.id:o for o in scene.world.collision_objects}
        placements=[];prefix_ended=False
        for p in row['job']['plan']['placements']:
            bid=p['brick_id']
            if bid not in world:raise ValueError('missing known brick in reference scene')
            actual=self.object_pose(world[bid]);target=CellLayout(row['job']['cell']).target_pose(p)
            on_pallet=same_pose(actual,target)
            if on_pallet and prefix_ended:raise ValueError('reference pallet is not an ordered prefix')
            if on_pallet:placements.append(deepcopy(p))
            else:prefix_ended=True
        ids={p['brick_id'] for p in placements}
        inventory=[deepcopy(b) for b in row['snapshot']['items'] if b['id'] not in ids]
        for bid in self.objects:
            if bid not in world:raise ValueError('complete reference inventory is required')
        return dict(schema_version='cell-reconciliation-0.1',run_id=row['run_id'],plan_digest=plan_digest(row['job']['plan']),basis_digest=basis_digest(row),observation_id=observation_id,source='synthetic',coverage='complete',gripper={'state':'empty'},robot={'state':'safe_home'},placements=placements,inventory=inventory,missing_ids=[],frame='world',units='m',source_poses={b['id']:self.object_pose(world[b['id']]) for b in inventory},robot_scene_digest=scene_digest(semantic),robot_scene=semantic)

    def verify_recovery_scene(self,row,observation,proposal):
        fresh=self.reconciliation(row,observation['observation_id'])
        require_same_scene(fresh['robot_scene'],observation.get('robot_scene_digest'))
        if without_timestamps(fresh)!=without_timestamps(observation):raise ValueError('reconciliation differs from the live reference scene')
        return dict(backend=self.backend,scene_digest=fresh['robot_scene_digest'],proposal_digest=proposal['proposal_digest'],joints=deepcopy(self.positions),physical_validation=False)

    def activate_recovery(self,job,receipt):
        _,semantic=self.capture_scene();require_same_scene(semantic,receipt['scene_digest'])
        self.job=deepcopy(job)
        self.placed={p['brick_id'] for p in job.get('preserved_placements',[])}
        self.evidence=[];self.playback_metrics=[]
        self.publish_state()

    def call(self,client,request,timeout=20.):
        future=client.call_async(request)
        rclpy.spin_until_future_complete(self,future,timeout_sec=timeout)
        if not future.done():raise TimeoutError('MoveIt response timed out; no implicit success')
        return future.result()

    def spin_for(self,seconds):
        end=time.monotonic()+seconds
        while rclpy.ok() and time.monotonic()<end:rclpy.spin_once(self,timeout_sec=min(.02,max(0,end-time.monotonic())))

    def publish_state(self):
        if self.motion is not None:
            path,indexes,start,speed=self.motion
            now=time.monotonic()
            self.motion_samples.append(now)
            elapsed=(now-start)*speed
            for index,value in zip(indexes,path.sample(elapsed)):self.positions[index]=value
        msg=JointState()
        msg.header.stamp=Time(nanoseconds=self.visual_epoch_ns+time.monotonic_ns()-self.visual_start_ns).to_msg()
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

    def is_valid(self,positions=None):
        candidate=self.state()
        if positions is not None:candidate.joint_state.position=list(positions)
        response=self.call(self.valid,GetStateValidity.Request(robot_state=candidate,group_name='panda_arm'))
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
        pose_constraints=Constraints(position_constraints=[pc],orientation_constraints=[oc])
        for _ in range(3):
            # Resolve a collision-valid goal before asking OMPL for a path. This
            # avoids relying only on random pose-goal sampling for the redundant arm.
            from builtin_interfaces.msg import Duration
            ik_request=GetPositionIK.Request()
            ik_request.ik_request.group_name='panda_arm'
            ik_request.ik_request.ik_link_name='panda_hand'
            ik_request.ik_request.robot_state=self.state()
            ik_request.ik_request.pose_stamped.header.frame_id='world'
            ik_request.ik_request.pose_stamped.pose=goal
            ik_request.ik_request.timeout=Duration(sec=1)
            ik_request.ik_request.avoid_collisions=True
            ik=self.call(self.ik,ik_request)
            goal_joints=dict(zip(ik.solution.joint_state.name,ik.solution.joint_state.position))
            if ik.error_code.val==1 and all(name in goal_joints for name in JOINTS):
                req.goal_constraints=[Constraints(joint_constraints=[JointConstraint(joint_name=name,position=goal_joints[name],tolerance_above=.0001,tolerance_below=.0001,weight=1.) for name in JOINTS])]
            else:req.goal_constraints=[pose_constraints]
            response=self.call(self.plan,request,timeout=15.).motion_plan_response
            if response.error_code.val not in (-1,-2,99999):break
        return (response.trajectory if response.error_code.val==1 else None),response.error_code.val

    def playback(self,trajectory):
        joint=trajectory.joint_trajectory
        if not joint.points:raise RuntimeError('MoveIt returned an empty path')
        indexes=[(JOINTS+FINGERS).index(name) for name in joint.joint_names]
        path=TimedPath([p.time_from_start.sec+p.time_from_start.nanosec*1e-9 for p in joint.points],[p.positions for p in joint.points])
        self.animate(path,indexes)

    def animate(self,path,indexes):
        if max(abs(self.positions[i]-v) for i,v in zip(indexes,path.positions[0]))>.01:
            raise RuntimeError('trajectory start differs from displayed joints; refusing a jump')
        start=time.monotonic()
        self.motion_samples=[]
        self.motion=(path,indexes,start,self.speed)
        # One steady publication timer samples the entire path, without restarting
        # an interpolation clock (or publishing a burst) at every waypoint.
        try:
            while (time.monotonic()-start)*self.speed<path.duration:
                rclpy.spin_once(self,timeout_sec=.01)
            self.publish_state()
        finally:self.motion=None
        self.playback_metrics.append(dict(planned_duration_s=path.duration,wall_duration_s=time.monotonic()-start,speed=self.speed,frames=len(self.motion_samples),max_frame_gap_s=max((b-a for a,b in zip(self.motion_samples,self.motion_samples[1:])),default=0.)))
        self.spin_for(.04)

    def set_gripper(self,width):
        initial=self.positions[-1]
        for i in range(1,7):
            value=initial+(width-initial)*i/6
            candidate=list(self.positions)
            candidate[-2:]=[value,value]
            if not self.is_valid(candidate):raise RuntimeError('collision during synthetic gripper motion')
        self.animate(TimedPath([0.,.7*self.speed],[[initial,initial],[width,width]]),[7,8])

    def perform(self,command):
        if command['action_id'] not in {c['action_id'] for c in self.job['commands']}:return ActionResult('failed_before_action','reference_job_not_activated')
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
                m.frame_locked=True
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
        # Wire outlines identify preserved placements without altering their shades.
        for p in self.job.get('preserved_placements',[]):
            marker=Marker(id=1000+p['step'],ns='preserved_outline',type=Marker.LINE_LIST,action=Marker.ADD)
            marker.header.frame_id='world';marker.pose=geometry_pose(self.objects[p['brick_id']])
            marker.scale.x=.002
            marker.color.r,marker.color.g,marker.color.b,marker.color.a=.3,1.,.75,1.
            half=[v/2+.001 for v in self.job['cell']['brick_size_m']]
            corners=[(x,y,z) for x in (-half[0],half[0]) for y in (-half[1],half[1]) for z in (-half[2],half[2])]
            for i,a in enumerate(corners):
                for b in corners[i+1:]:
                    if sum(x!=y for x,y in zip(a,b))==1:
                        marker.points.extend([Point(x=a[0],y=a[1],z=a[2]),Point(x=b[0],y=b[1],z=b[2])])
            result.markers.append(marker)
        self.markers.publish(result)

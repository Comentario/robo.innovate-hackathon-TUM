"""ROS 2 transport for the existing inventory/plan contract, with a visual-only consumer."""
import json

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster

from demo import simulate_plan, validate_plan
from planning import make_plan
from planning.faces import make_face_plan


def retained_qos(depth=1):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


def string_message(value):
    return String(data=json.dumps(value, ensure_ascii=True))


class PlannerNode(Node):
    def __init__(self, prefix='/munich_demo'):
        super().__init__('brick_planner_adapter')
        self.publisher = self.create_publisher(String, prefix + '/plan', retained_qos())
        self.subscription = self.create_subscription(String, prefix + '/inventory_request', self.on_request, retained_qos())

    def on_request(self, message):
        try:
            request = json.loads(message.data)
            if not isinstance(request, dict) or type(request.get('face_aware', False)) is not bool:
                raise ValueError('request must be an object with a boolean face_aware flag')
            inventory, config = request['inventory'], request['config']
            if not isinstance(config, dict):
                raise ValueError('config must be an object')
            planner = make_face_plan if request.get('face_aware', False) else make_plan
            plan = planner(inventory, **config)
            validate_plan(plan, inventory)
            response = dict(schema_version='ros-envelope-0.1', status='planned',
                            plan=plan, source_inventory=inventory)
        except (ValueError, TypeError, KeyError) as error:
            # Publish rejection on the same retained topic to invalidate an older preview.
            response = dict(schema_version='ros-envelope-0.1', status='rejected', reason=str(error))
        if response['status']=='planned':
            for key in ('snapshot','source_poses'):
                if key in request:response[key]=request[key]
        self.publisher.publish(string_message(response))


class PreviewNode(Node):
    """Animate logical cubes; never publish joint, trajectory or robot commands."""
    def __init__(self, prefix='/munich_demo', period=0.8, fail_step=None):
        super().__init__('brick_pallet_preview')
        self.static_tf = StaticTransformBroadcaster(self)
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = 'world'
        transform.child_frame_id = 'pallet'
        transform.transform.rotation.w = 1.0
        self.static_tf.sendTransform(transform)
        self.fail_step = fail_step
        self.active = None
        self.cursor = 0
        self.event_publisher = self.create_publisher(String, prefix + '/events', retained_qos(100))
        self.marker_publisher = self.create_publisher(MarkerArray, prefix + '/markers', retained_qos())
        self.subscription = self.create_subscription(String, prefix + '/plan', self.on_plan, retained_qos())
        self.timer = self.create_timer(period, self.tick)

    def event(self, status, **fields):
        self.event_publisher.publish(string_message(dict(execution='simulation_only', status=status, **fields)))

    def markers(self, placements):
        clear = Marker()
        clear.header.frame_id = 'pallet'
        clear.action = Marker.DELETEALL
        markers = [clear]
        palette = dict(dark=(.44,.26,.19), medium=(.72,.47,.32), light=(.91,.78,.63))
        for p in placements:
            cube = Marker()
            cube.header.frame_id = 'pallet'
            cube.header.stamp = self.get_clock().now().to_msg()
            cube.ns, cube.id, cube.type, cube.action = 'bricks', p['step'], Marker.CUBE, Marker.ADD
            cube.pose.position.x = p['column'] * .24
            cube.pose.position.y = p['row'] * .125
            cube.pose.position.z = .04 + p['layer'] * .085
            cube.pose.orientation.w = 1.0
            cube.scale.x, cube.scale.y, cube.scale.z = .22, .105, .075
            cube.color.r, cube.color.g, cube.color.b = palette.get(p['color_group'], (.5,.5,.5))
            cube.color.a = 1.0
            label = Marker()
            label.header = cube.header
            label.ns, label.id, label.type, label.action = 'labels', p['step'], Marker.TEXT_VIEW_FACING, Marker.ADD
            label.pose.position.x, label.pose.position.y = cube.pose.position.x, cube.pose.position.y
            label.pose.position.z = cube.pose.position.z + .055
            label.pose.orientation.w = 1.0
            label.scale.z = .018
            label.color.r = label.color.g = label.color.b = label.color.a = 1.0
            label.text = f"#{p['step']} {p['color_group']} | {p.get('visible_face', 'face not modeled')}"
            markers.extend((cube, label))
        self.marker_publisher.publish(MarkerArray(markers=markers))

    def on_plan(self, message):
        self.active, self.cursor = None, 0
        self.markers([])
        try:
            response = json.loads(message.data)
            if response.get('schema_version') != 'ros-envelope-0.1':
                raise ValueError('unsupported ROS envelope')
            if response.get('status') == 'rejected':
                self.event('rejected', reason=response.get('reason', 'planning rejected'))
                return
            if response.get('status') != 'planned':
                raise ValueError('unsupported response status')
            self.active = simulate_plan(response['plan'], response['source_inventory'], fail_step=self.fail_step)
            self.event('ready', confirmed=0)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.event('rejected', reason=str(error))

    def tick(self):
        if self.active is None:
            return
        report = self.active
        confirmed = report['confirmed_placements']
        if self.cursor < len(confirmed):
            self.cursor += 1
            self.markers(confirmed[:self.cursor])
            self.event('placement_confirmed', confirmed=self.cursor, placement=confirmed[self.cursor - 1])
        else:
            self.event(report['status'], confirmed=self.cursor,
                       next_action='reconcile_inventory_and_pallet' if report['status'] == 'stopped' else 'none')
            self.active = None
        self.timer.reset()

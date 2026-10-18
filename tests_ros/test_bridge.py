"""Live ROS transport checks, run separately after sourcing the optional ROS environment."""
import json
from pathlib import Path
import time
import unittest
from uuid import uuid4

import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
from visualization_msgs.msg import MarkerArray, Marker
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from planning.faces import make_face_plan
from ros_bridge.nodes import PlannerNode, PreviewNode, retained_qos, string_message

ROOT = Path(__file__).resolve().parents[1]


class RosBridgeTests(unittest.TestCase):
    def setUp(self):
        rclpy.init(args=[])
        self.prefix = '/munich_test_' + uuid4().hex[:8]
        self.planner = PlannerNode(self.prefix)
        self.preview = PreviewNode(self.prefix, period=.01)
        self.client = rclpy.create_node('contract_test_client')
        self.publisher = self.client.create_publisher(String, self.prefix + '/inventory_request', retained_qos())
        self.events, self.markers, self.plans = [], [], []
        self.subs = [
            self.client.create_subscription(String, self.prefix + '/events', lambda m:self.events.append(json.loads(m.data)), retained_qos(100)),
            self.client.create_subscription(MarkerArray, self.prefix + '/markers', lambda m:self.markers.append(m), retained_qos()),
            self.client.create_subscription(String, self.prefix + '/plan', lambda m:self.plans.append(json.loads(m.data)), retained_qos())]
        self.executor = SingleThreadedExecutor()
        for node in (self.planner, self.preview, self.client):
            self.executor.add_node(node)
        self.request = dict(inventory=json.loads((ROOT/'examples/faces/inventory.json').read_text()),
                            config=json.loads((ROOT/'examples/faces/config.json').read_text()), face_aware=True)

    def tearDown(self):
        self.executor.shutdown()
        for node in (self.planner, self.preview, self.client):
            node.destroy_node()
        rclpy.shutdown()

    def until(self, status, cubes=None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=.02)
            event_ready = any(e['status'] == status for e in self.events)
            markers_ready = cubes is None or (self.markers and self.cube_count() == cubes)
            plan_ready = self.plans and self.plans[-1]['status'] == ('rejected' if status == 'rejected' else 'planned')
            if event_ready and markers_ready and plan_ready:
                return
        self.fail(f'no {status} event; got {self.events}')

    def cube_count(self):
        return sum(m.type == Marker.CUBE and m.action == Marker.ADD for m in self.markers[-1].markers)

    def test_world_to_pallet_frame_is_available_to_late_subscribers(self):
        buffer = Buffer()
        listener = TransformListener(buffer, self.client)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not buffer.can_transform('world', 'pallet', Time()):
            self.executor.spin_once(timeout_sec=.05)
        transform = buffer.lookup_transform('world', 'pallet', Time())
        self.assertEqual(transform.transform.rotation.w, 1.0)
        self.assertEqual(transform.transform.translation.x, 0.0)
        listener.unregister()

    def test_ros_request_plan_and_marker_transport(self):
        self.publisher.publish(string_message(self.request))
        self.until('completed', cubes=12)
        self.assertEqual(self.events[-1]['confirmed'], 12)
        self.assertEqual(self.plans[-1]['plan']['schema_version'], '0.3')
        self.assertEqual(self.plans[-1]['plan'], make_face_plan(self.request['inventory'], **self.request['config']))
        self.assertEqual(self.cube_count(), 12)
        self.assertEqual(self.markers[-1].markers[1].header.frame_id, 'pallet')

    def test_ros_preview_stops_after_four_confirmations(self):
        self.preview.fail_step = 5
        self.publisher.publish(string_message(self.request))
        self.until('stopped', cubes=4)
        self.assertEqual(self.events[-1]['confirmed'], 4)
        self.assertEqual(self.cube_count(), 4)
        self.assertFalse(any(e['status']=='completed' for e in self.events))

    def test_new_rejection_clears_previous_preview(self):
        self.publisher.publish(string_message(self.request))
        self.until('completed', cubes=12)
        self.assertEqual(self.cube_count(), 12)
        self.request['inventory'] = []
        self.publisher.publish(string_message(self.request))
        self.until('rejected', cubes=0)
        self.assertEqual(self.cube_count(), 0)
        self.assertEqual(self.plans[-1]['status'], 'rejected')

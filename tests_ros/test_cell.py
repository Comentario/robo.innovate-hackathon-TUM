import json
from pathlib import Path
import time
import unittest
from uuid import uuid4
import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
from visualization_msgs.msg import MarkerArray, Marker
from ros_bridge.nodes import PlannerNode, retained_qos, string_message
from ros_bridge.cell_node import CellExecutionNode

ROOT=Path(__file__).resolve().parents[1]


class CellRosTests(unittest.TestCase):
    def setUp(self):
        rclpy.init(args=[])
        prefix='/cell_test_'+uuid4().hex[:8]
        cell=json.loads((ROOT/'config/cell.json').read_text())
        self.planner=PlannerNode(prefix)
        self.preview=CellExecutionNode(cell,prefix,period=.001)
        self.client=rclpy.create_node('cell_observer')
        self.events,self.markers=[],[]
        self.subs=[self.client.create_subscription(String,prefix+'/events',lambda m:self.events.append(json.loads(m.data)),retained_qos(100)),
                   self.client.create_subscription(MarkerArray,prefix+'/markers',lambda m:self.markers.append(m),retained_qos())]
        self.publisher=self.client.create_publisher(String,prefix+'/inventory_request',retained_qos())
        self.executor=SingleThreadedExecutor()
        for node in (self.planner,self.preview,self.client):self.executor.add_node(node)
        self.request=dict(inventory=json.loads((ROOT/'examples/faces/inventory.json').read_text()),
                          config=json.loads((ROOT/'examples/faces/config.json').read_text()),face_aware=True)

    def tearDown(self):
        self.executor.shutdown()
        for node in (self.planner,self.preview,self.client):node.destroy_node()
        rclpy.shutdown()

    def count(self,namespace):
        return sum(m.ns==namespace and m.action==Marker.ADD for m in self.markers[-1].markers)

    def wait(self,status,confirmed,**expected):
        self.publisher.publish(string_message(self.request))
        end=time.monotonic()+10
        while time.monotonic()<end:
            self.executor.spin_once(timeout_sec=.01)
            ready=self.events and self.events[-1]['status']==status and self.markers and self.count('bricks')==confirmed
            if ready and all(self.count(ns)==count for ns,count in expected.items()):return
        self.fail(str(self.events[-3:]))

    def test_complete_action_sequence_depletes_source_and_places_twelve(self):
        self.wait('completed',12,source=0,held=0)
        self.assertEqual(self.count('source'),0)
        self.assertEqual(self.count('held'),0)
        self.assertEqual(self.count('cell'),2)
        self.assertEqual(self.count('tool'),1)
        self.assertEqual(self.events[-1]['phase'],'retreat')

    def test_failed_orientation_preserves_held_brick(self):
        self.preview.fail_step,self.preview.fail_phase=5,'orient'
        self.wait('stopped',4,source=7,held=1)
        self.assertEqual(self.count('held'),1)
        self.assertEqual(self.count('source'),7)
        self.assertIsNotNone(self.events[-1]['held_brick'])
        self.assertEqual(self.events[-1]['phase'],'orient')

    def test_failed_confirmation_keeps_unconfirmed_brick_visible(self):
        self.preview.fail_step,self.preview.fail_phase=5,'confirm'
        self.wait('stopped',4,unconfirmed=1,held=0)
        self.assertEqual(self.count('unconfirmed'),1)
        self.assertEqual(self.count('held'),0)
        self.assertIsNotNone(self.events[-1]['placed_unconfirmed'])

    def test_unknown_pick_is_quarantined_from_available_source(self):
        self.preview.fail_step,self.preview.fail_phase,self.preview.unknown=5,'pick',True
        self.wait('stopped',4,source=7,held=0)
        self.assertEqual(self.count('source'),7)
        self.assertEqual(self.count('held'),0)
        self.assertIsNotNone(self.events[-1]['uncertain_brick'])

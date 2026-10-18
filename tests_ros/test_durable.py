import json
from pathlib import Path
import tempfile
import time
import unittest
import test_cell
from integration.journal import Journal
from ros_bridge.cell_node import CellExecutionNode
from ros_bridge.nodes import string_message

ROOT=Path(__file__).resolve().parents[1]


class DurableRosTests(unittest.TestCase):
    count=test_cell.CellRosTests.count
    wait=test_cell.CellRosTests.wait

    def setUp(self):
        test_cell.CellRosTests.setUp(self)
        self.tmp=tempfile.TemporaryDirectory()
        self.journal=Journal(Path(self.tmp.name)/'state.sqlite3')
        self.preview.journal=self.journal
        self.preview.destroy_timer(self.preview.timer)
        self.preview.timer=self.preview.create_timer(.02,self.preview.tick)
        self.request['snapshot']=json.loads((ROOT/'examples/perception/snapshot.json').read_text())

    def tearDown(self):
        test_cell.CellRosTests.tearDown(self)
        self.journal.close()
        self.tmp.cleanup()

    def test_ros_actions_are_durable_and_repeated_request_keeps_the_pallet(self):
        self.wait('completed',12,source=0,held=0)
        row=self.journal.inspect(self.journal.latest_run_id())
        self.assertEqual(row['checkpoint']['cursor'],96)
        self.assertEqual(len(row['checkpoint']['confirmed']),12)
        self.assertIsNone(row['pending'])
        self.events.clear()
        self.publisher.publish(string_message(self.request))
        end=time.monotonic()+5
        while time.monotonic()<end:
            self.executor.spin_once(timeout_sec=.02)
            if self.events and self.events[-1]['status']=='request_refused':break
        self.assertEqual(self.events[-1]['status'],'request_refused')
        self.assertEqual(self.count('bricks'),12)
        self.assertEqual(self.journal.inspect(row['run_id'])['checkpoint'],row['checkpoint'])

    def test_reopening_a_failed_cell_restores_view_without_resuming(self):
        self.preview.fail_step,self.preview.fail_phase=5,'orient'
        self.wait('stopped',4,source=7,held=1)
        run_id=self.journal.latest_run_id()
        before=self.journal.inspect(run_id)
        cell=self.preview.cell.config
        # Recreate only the viewer, using its existing topic namespace.
        prefix=self.preview.subscription.topic_name.rsplit('/',1)[0]
        self.executor.remove_node(self.preview)
        self.preview.destroy_node()
        self.preview=CellExecutionNode(cell,prefix,period=.001,journal=self.journal)
        self.executor.add_node(self.preview)
        for _ in range(20):self.executor.spin_once(timeout_sec=.01)
        self.assertTrue(self.preview.view_only)
        self.assertEqual(len(self.preview.session.confirmed),4)
        self.assertIsNotNone(self.preview.session.held_brick)
        self.assertEqual(self.journal.inspect(run_id)['checkpoint'],before['checkpoint'])
        self.assertIsNone(self.preview.runner)

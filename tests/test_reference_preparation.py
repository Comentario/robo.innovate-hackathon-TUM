from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace

from execution import SimulatedAdapter
from integration import prepare
from integration.journal import Journal
from arm_bridge.recovery import prepare_home,save_robot_checkpoint,load_robot_checkpoint

ROOT=Path(__file__).resolve().parents[1]


class ReferencePreparationTests(unittest.TestCase):
    def setUp(self):
        read=lambda p:json.loads((ROOT/p).read_text())
        snapshot,_,job=prepare(read('examples/perception/snapshot.json'),read('examples/faces/config.json'),read('config/cell.json'))
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite3';self.journal=Journal(self.path)
        class ReferenceFault(SimulatedAdapter):backend='panda_moveit_kinematic'
        runner=self.journal.create(snapshot,job,ReferenceFault(1,'approach_pick',True));runner.advance()
        self.row=self.journal.inspect(runner.run_id)
        self.adapter=SimpleNamespace(mode='simulation_only',backend='panda_moveit_kinematic',job=self.row['job'],capture_scene=lambda:(None,{'joints':{'panda_joint1':0.},'objects':{},'attached':[]}),visual_epoch_ns=time.time_ns(),visual_start_ns=time.monotonic_ns())

    def tearDown(self):self.journal.close();self.tmp.cleanup()

    def test_unknown_home_move_is_durable_and_not_automatically_retried(self):
        calls=[]
        def fail():calls.append(True);raise TimeoutError('injected_home_ack_timeout')
        self.adapter.move_to_recovery_home=fail
        with self.assertRaises(TimeoutError):prepare_home(self.journal,self.row,self.adapter)
        self.journal.close();self.journal=Journal(self.path)
        saved=self.journal.db.execute('SELECT status,payload FROM reference_preparations').fetchone()
        self.assertEqual(saved['status'],'unknown');self.assertEqual(json.loads(saved['payload'])['outcome'],'unknown')
        with self.assertRaises(sqlite3.IntegrityError):prepare_home(self.journal,self.row,self.adapter)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.journal.inspect(self.row['run_id']),self.row)

    def test_robot_checkpoint_is_bound_to_current_run_and_survives_reopening(self):
        saved=save_robot_checkpoint(self.journal,self.row,self.adapter)
        self.journal.close();self.journal=Journal(self.path)
        self.assertEqual(load_robot_checkpoint(self.journal,self.row),saved)
        changed=deepcopy(self.row);changed['checkpoint']['cursor']+=1
        with self.assertRaisesRegex(ValueError,'stale'):load_robot_checkpoint(self.journal,changed)

    def test_wrong_job_or_non_reference_adapter_cannot_prepare_a_move(self):
        self.adapter.job=deepcopy(self.adapter.job);self.adapter.job['job_id']='different'
        with self.assertRaises(ValueError):prepare_home(self.journal,self.row,self.adapter)
        self.assertEqual(self.journal.db.execute('SELECT COUNT(*) FROM reference_preparations').fetchone()[0],0)
        with self.assertRaises(ValueError):self.journal.recover_reference_simulation(self.row['run_id'],{},SimulatedAdapter(),expected_proposal_digest='irrelevant')


if __name__=='__main__':unittest.main()

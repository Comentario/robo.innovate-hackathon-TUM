from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from execution import SimulatedAdapter
from integration import prepare
from integration.intake import normalize_snapshot
from integration.journal import Journal
from integration.validation import validate_final,plan_digest

ROOT=Path(__file__).resolve().parents[1]


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=json.loads((ROOT/'examples/perception/snapshot.json').read_text())
        self.config=json.loads((ROOT/'examples/faces/config.json').read_text())
        self.cell=json.loads((ROOT/'config/cell.json').read_text())
        _,self.plan,self.job=prepare(self.snapshot,self.config,self.cell)
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'state.sqlite3'

    def tearDown(self):self.tmp.cleanup()

    def test_real_snapshot_can_plan_but_requires_measured_poses_for_execution(self):
        value=deepcopy(self.snapshot);value['source']='perception'
        _,plan,job=prepare(value,self.config)
        self.assertIsNone(job)
        self.assertEqual(plan,self.plan)
        with self.assertRaises(ValueError):prepare(value,self.config,self.cell)
        value.update(source_poses=deepcopy(self.job['source_poses']),frame='world',units='m')
        _,_,job=prepare(value,self.config,self.cell)
        self.assertEqual(job['source_poses'],value['source_poses'])
        value['frame']='camera'
        with self.assertRaises(ValueError):prepare(value,self.config,self.cell)

    def test_input_rejects_duplicate_ids_and_does_not_infer_unknown_faces(self):
        value=deepcopy(self.snapshot)
        value['items'].append(value['items'][0])
        with self.assertRaises(ValueError):normalize_snapshot(value)
        self.assertTrue(all(p['visible_face']!='top' for p in self.plan['placements']))

    def test_checkpoint_survives_restart_without_replaying_acknowledged_actions(self):
        journal=Journal(self.path);first=SimulatedAdapter()
        runner=journal.create(self.snapshot,self.job,first)
        for _ in range(10):runner.advance()
        run_id=runner.run_id
        self.assertEqual(runner.session.held_brick,self.plan['placements'][1]['brick_id'])
        journal.close()
        journal=Journal(self.path);second=SimulatedAdapter()
        restored=journal.resume_simulation(run_id,second)
        while restored.session.status not in ('completed','stopped'):restored.advance()
        ids=[a['action_id'] for a in first.calls+second.calls]
        self.assertEqual(len(ids),96)
        self.assertEqual(len(set(ids)),96)
        self.assertEqual(len(restored.session.confirmed),12)
        journal.close()

    def test_crash_after_dispatch_requires_reconciliation(self):
        class Crash(SimulatedAdapter):
            def perform(self,command):raise SystemExit('simulated process crash')
        journal=Journal(self.path)
        runner=journal.create(self.snapshot,self.job,Crash())
        with self.assertRaises(SystemExit):runner.advance()
        run_id=runner.run_id;journal.close()
        journal=Journal(self.path)
        row=journal.inspect(run_id)
        self.assertEqual(row['status'],'dispatch_unacknowledged')
        self.assertIsNotNone(row['pending'])
        with self.assertRaises(ValueError):journal.resume_simulation(run_id,SimulatedAdapter())
        journal.close()

    def test_stale_executor_and_second_cycle_are_rejected(self):
        one=Journal(self.path);runner=one.create(self.snapshot,self.job,SimulatedAdapter())
        two=Journal(self.path);adapter=SimulatedAdapter()
        stale=two.resume_simulation(runner.run_id,adapter)
        runner.advance()
        with self.assertRaises(ValueError):stale.advance()
        self.assertEqual(adapter.calls,[])
        with self.assertRaises(ValueError):two.create(self.snapshot,self.job,SimulatedAdapter())
        changed=deepcopy(self.snapshot);changed['snapshot_id']='new-snapshot'
        with self.assertRaises(ValueError):two.create(changed,self.job,SimulatedAdapter())
        one.close();two.close()

    def test_stopped_run_keeps_held_state_and_cannot_auto_resume(self):
        journal=Journal(self.path);runner=journal.create(self.snapshot,self.job,SimulatedAdapter(5,'orient'))
        while runner.session.status not in ('completed','stopped'):runner.advance()
        row=journal.inspect(runner.run_id)
        self.assertEqual(len(row['checkpoint']['confirmed']),4)
        self.assertEqual(row['checkpoint']['held_brick'],self.plan['placements'][4]['brick_id'])
        with self.assertRaises(ValueError):journal.resume_simulation(runner.run_id,SimulatedAdapter())
        journal.close()

    def observation(self):
        return dict(schema_version='pallet-observation-0.1',observation_id='obs-001',source='synthetic',
                    run_id='run-001',plan_digest=plan_digest(self.plan),placements=deepcopy(self.plan['placements']))

    def test_final_validator_requires_evidence_and_detects_missing_wrong_and_duplicate(self):
        self.assertEqual(validate_final(self.plan)['status'],'awaiting_observation')
        observation=self.observation()
        valid=validate_final(self.plan,observation,run_id='run-001')
        self.assertEqual(valid['status'],'passed');self.assertFalse(valid['independent'])
        for kind in ('missing','tone','face','id','duplicate'):
            bad=deepcopy(observation)
            if kind=='missing':bad['placements'].pop()
            elif kind=='duplicate':bad['placements'].append(bad['placements'][0])
            else:bad['placements'][0][{'tone':'color_group','face':'visible_face','id':'brick_id'}[kind]]='wrong'
            with self.subTest(kind=kind):self.assertEqual(validate_final(self.plan,bad)['status'],'failed')
        with self.assertRaises(ValueError):validate_final(self.plan,observation,run_id='other')

    def test_observation_identity_is_immutable_and_validation_persists(self):
        journal=Journal(self.path);runner=journal.create(self.snapshot,self.job,SimulatedAdapter())
        observation=self.observation();observation['run_id']=runner.run_id
        result=validate_final(self.plan,observation,run_id=runner.run_id)
        journal.save_validation(runner.run_id,observation,result)
        self.assertEqual(journal.latest_validation(runner.run_id),result)
        observation['source']='perception'
        with self.assertRaises(ValueError):journal.save_validation(runner.run_id,observation,result)
        journal.close()

    def test_view_restore_preserves_state_without_enabling_motion(self):
        journal=Journal(self.path);runner=journal.create(self.snapshot,self.job,SimulatedAdapter())
        for _ in range(10):runner.advance()
        before=journal.inspect(runner.run_id)['checkpoint']
        view,row=journal.restore_simulation_view(runner.run_id)
        self.assertEqual(view.status,'stopped')
        self.assertEqual(view.cursor,10)
        self.assertEqual(view.held_brick,runner.session.held_brick)
        self.assertEqual(journal.inspect(runner.run_id)['checkpoint'],before)
        journal.close()

    def test_cli_pause_resume_and_report_keep_observation_pending(self):
        output=Path(self.tmp.name)/'report.json'
        def invoke(*args):
            return subprocess.run([sys.executable,'-m','integration',*args,'--state',str(self.path),'--output',str(output)],cwd=ROOT,capture_output=True,text=True)
        paused=invoke('run','--pause-after','10')
        self.assertEqual(paused.returncode,4,paused.stdout+paused.stderr)
        resumed=invoke('resume')
        self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
        result=json.loads(output.read_text())
        self.assertEqual(result['final_validation']['status'],'awaiting_observation')
        self.assertEqual(len(result['execution_report']['confirmed_placements']),12)
        html=output.with_suffix('.html').read_text()
        self.assertIn('No independent final observation',html)
        self.assertIn('<html lang="en">',html)
        repeated=invoke('run')
        self.assertEqual(repeated.returncode,2)

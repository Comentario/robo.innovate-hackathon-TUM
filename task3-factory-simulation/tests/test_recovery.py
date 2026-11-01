from copy import deepcopy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from execution import SimulatedAdapter, ActionResult
from integration import prepare
from integration.journal import Journal
from integration.recovery import assess_recovery,basis_digest
from integration.validation import plan_digest

ROOT=Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=json.loads((ROOT/'examples/perception/snapshot.json').read_text())
        self.config=json.loads((ROOT/'examples/faces/config.json').read_text())
        self.cell=json.loads((ROOT/'config/cell.json').read_text())
        _,self.plan,self.job=prepare(self.snapshot,self.config,self.cell)
        self.tmp=tempfile.TemporaryDirectory()
        self.journal=Journal(Path(self.tmp.name)/'recovery.sqlite3')

    def tearDown(self):self.journal.close();self.tmp.cleanup()

    def stopped(self,phase='pick',unknown=True):
        runner=self.journal.create(self.snapshot,self.job,SimulatedAdapter(5,phase,unknown))
        while runner.session.status not in ('stopped','completed'):runner.advance()
        return runner,self.journal.inspect(runner.run_id)

    def observation(self,row,count=4):
        placed=deepcopy(self.plan['placements'][:count]);ids={p['brick_id'] for p in placed}
        return dict(schema_version='cell-reconciliation-0.1',run_id=row['run_id'],plan_digest=plan_digest(row['job']['plan']),
            basis_digest=basis_digest(row),observation_id='recheck-001',source='synthetic',coverage='complete',
            gripper={'state':'empty'},robot={'state':'safe_home'},placements=placed,
            inventory=[deepcopy(b) for b in self.snapshot['items'] if b['id'] not in ids],missing_ids=[],
            frame='world',units='m',source_poses={bid:deepcopy(p) for bid,p in self.job['source_poses'].items() if bid not in ids})

    def test_recovery_never_picks_preserved_bricks_and_parent_is_immutable(self):
        parent,row=self.stopped();observation=self.observation(row)
        proposal=assess_recovery(row,observation)
        self.assertEqual(proposal['status'],'ready')
        adapter=SimulatedAdapter()
        runner=self.journal.recover_simulation(parent.run_id,observation,adapter,expected_proposal_digest=proposal['proposal_digest'])
        self.assertEqual(len(runner.session.confirmed),4)
        self.assertEqual(len(runner.session.job['commands']),64)
        while runner.session.status not in ('stopped','completed'):runner.advance()
        self.assertEqual(runner.session.status,'completed')
        self.assertEqual(len(runner.session.confirmed),12)
        preserved={p['brick_id'] for p in self.plan['placements'][:4]}
        self.assertTrue(all(c['brick_id'] not in preserved and c['step']>=5 for c in adapter.calls))
        self.assertTrue(set(c['action_id'] for c in adapter.calls).isdisjoint(e['action_id'] for e in row['checkpoint']['events']))
        after=self.journal.inspect(parent.run_id)
        self.assertEqual(after['status'],'superseded');self.assertEqual(after['checkpoint'],row['checkpoint'])
        self.assertIsNone(after['pending'])
        with self.assertRaises(ValueError):self.journal.recover_simulation(parent.run_id,observation,adapter,expected_proposal_digest=proposal['proposal_digest'])

    def test_unknown_place_can_be_observed_as_placed_without_repeating_it(self):
        parent,row=self.stopped('place');o=self.observation(row,5)
        proposal=assess_recovery(row,o)
        self.assertEqual(proposal['status'],'ready')
        self.assertEqual(proposal['job']['commands'][0]['step'],6)
        self.assertEqual(len(proposal['preserved_placements']),5)

    def test_missing_brick_replaced_without_changing_pattern_or_recipe(self):
        _,row=self.stopped();o=self.observation(row)
        missing=self.plan['placements'][4]['brick_id']
        brick=next(b for b in o['inventory'] if b['id']==missing)
        replacement=deepcopy(brick);replacement['id']='replacement_01'
        o['inventory']=[b for b in o['inventory'] if b['id']!=missing]+[replacement]
        o['missing_ids']=[missing];o['source_poses']['replacement_01']=o['source_poses'].pop(missing)
        p=assess_recovery(row,o)
        self.assertEqual(p['status'],'ready')
        self.assertIn(dict(step=5,old_brick_id=missing,new_brick_id='replacement_01'),p['replacements'])
        self.assertEqual(p['job']['plan']['blend'],self.plan['blend'])
        self.assertEqual(p['job']['plan']['metrics'],self.plan['metrics'])
        self.assertEqual(p['job']['plan']['placements'][:4],self.plan['placements'][:4])

    def test_unsafe_or_incomplete_evidence_blocks_without_dispatch(self):
        parent,row=self.stopped()
        for mutation,kind in [('held','gripper_not_verified_empty'),('home','robot_not_verified_at_safe_home'),('coverage','incomplete_coverage'),('missing','unaccounted_original_ids'),('prefix','non_prefix_or_unexpected_pallet'),('face','preserved_placement_mismatch'),('pose','invalid_source_pose'),('stock','insufficient_compatible_stock')]:
            o=self.observation(row)
            if mutation=='held':o['gripper']={'state':'holding','brick_id':self.plan['placements'][4]['brick_id']}
            elif mutation=='home':o['robot']={'state':'unknown'}
            elif mutation=='coverage':o['coverage']='partial'
            elif mutation=='missing':o['inventory'].pop();o['source_poses'].pop(next(reversed(o['source_poses'])))
            elif mutation=='prefix':o['placements'].pop(1)
            elif mutation=='face':o['placements'][0]['visible_face']='unobserved'
            elif mutation=='pose':o['source_poses'][o['inventory'][0]['id']]['position_m'][0]=100
            else:
                b=o['inventory'].pop();o['missing_ids'].append(b['id']);o['source_poses'].pop(b['id'])
            with self.subTest(mutation=mutation):
                p=assess_recovery(row,o)
                self.assertEqual(p['status'],'blocked');self.assertIn(kind,[i['kind'] for i in p['issues']]);self.assertIsNone(p['job'])
                with self.assertRaises(ValueError):self.journal.recover_simulation(parent.run_id,o,SimulatedAdapter(),expected_proposal_digest=p['proposal_digest'])
        self.assertEqual(self.journal.inspect(parent.run_id),row)
        self.assertEqual(self.journal.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)

    def test_stale_evidence_and_modified_proposal_are_refused(self):
        parent,row=self.stopped();o=self.observation(row)
        bad=deepcopy(o);bad['basis_digest']='stale'
        with self.assertRaisesRegex(ValueError,'stale'):assess_recovery(row,bad)
        bad=deepcopy(o);bad['run_id']='another'
        with self.assertRaises(ValueError):assess_recovery(row,bad)
        with self.assertRaisesRegex(ValueError,'proposal'):
            self.journal.recover_simulation(parent.run_id,o,SimulatedAdapter(),expected_proposal_digest='modified')
        self.assertEqual(self.journal.inspect(parent.run_id),row)

    def test_pending_dispatch_is_archived_and_late_ack_cannot_resurrect_parent(self):
        test=self
        class RecoverDuringDispatch(SimulatedAdapter):
            def perform(self,command):
                if command['step']==5 and command['phase']=='place':
                    row=test.journal.inspect(parent.run_id)
                    self.pending=deepcopy(row['pending'])
                    o=test.observation(row,5)
                    p=assess_recovery(row,o)
                    self.child=test.journal.recover_simulation(parent.run_id,o,SimulatedAdapter(),expected_proposal_digest=p['proposal_digest'])
                return ActionResult('succeeded')
        adapter=RecoverDuringDispatch();parent=self.journal.create(self.snapshot,self.job,adapter)
        with self.assertRaisesRegex(ValueError,'late acknowledgement'):
            while parent.session.status not in ('stopped','completed'):parent.advance()
        row=self.journal.inspect(parent.run_id)
        self.assertEqual(row['status'],'superseded');self.assertEqual(row['pending'],adapter.pending)
        self.assertEqual(len(adapter.child.session.confirmed),5)
        while adapter.child.session.status not in ('stopped','completed'):adapter.child.advance()
        self.assertEqual(len(adapter.child.session.confirmed),12)

    def test_full_pallet_observation_requires_no_further_actions(self):
        parent,row=self.stopped('place');o=self.observation(row,12)
        p=assess_recovery(row,o)
        self.assertEqual(p['status'],'ready');self.assertEqual(p['job']['commands'],[])
        adapter=SimulatedAdapter()
        child=self.journal.recover_simulation(parent.run_id,o,adapter,expected_proposal_digest=p['proposal_digest'])
        self.assertEqual(child.session.status,'completed');self.assertEqual(len(child.session.confirmed),12)
        self.assertIsNone(child.advance());self.assertEqual(adapter.calls,[])

    def test_overlapping_source_bricks_are_blocked(self):
        _,row=self.stopped();o=self.observation(row)
        ids=list(o['source_poses']);o['source_poses'][ids[1]]=deepcopy(o['source_poses'][ids[0]])
        p=assess_recovery(row,o)
        self.assertEqual(p['status'],'blocked')
        self.assertIn('overlapping_source_poses',[i['kind'] for i in p['issues']])

    def test_multiface_assignment_does_not_consume_the_only_light_candidate_for_dark(self):
        def brick(bid,back):
            return dict(id=bid,faces={'front':{'color_group':'dark'},'back':back},allowed_orientations=[{'id':'front_out','visible_face':'front'},{'id':'back_out','visible_face':'back'}])
        old=[brick('old_a',{'color_group':'light'}),brick('old_b',None)]
        snapshot=dict(schema_version='inventory-snapshot-0.1',snapshot_id='two-face-demo',source='synthetic',face_aware=True,items=old)
        _,_,job=prepare(snapshot,dict(rows=1,columns=2,layers=1,target_ratios={'dark':1,'light':1},mode='mixed',shortage_policy='reject'),self.cell)
        runner=self.journal.create(snapshot,job,SimulatedAdapter(1,'approach_pick',True));runner.advance()
        row=self.journal.inspect(runner.run_id);o=self.observation(row,0)
        o['inventory']=[brick('alpha_new',{'color_group':'light'}),brick('beta_new',None)]
        o['missing_ids']=['old_a','old_b'];o['source_poses']={'alpha_new':job['source_poses']['old_a'],'beta_new':job['source_poses']['old_b']}
        p=assess_recovery(row,o)
        self.assertEqual(p['status'],'ready')
        mapping={v['color_group']:v['brick_id'] for v in p['job']['plan']['placements']}
        self.assertEqual(mapping,{'dark':'beta_new','light':'alpha_new'})

    def test_cli_assesses_then_continues_and_refuses_a_replay(self):
        parent,row=self.stopped();o=self.observation(row)
        directory=Path(self.tmp.name);evidence=directory/'evidence.json';evidence.write_text(json.dumps(o))
        report=directory/'proposal.json'
        common=[sys.executable,'-m','integration.recovery']
        args=['--state',str(directory/'recovery.sqlite3'),'--run-id',parent.run_id,'--observations',str(evidence)]
        result=subprocess.run(common+['assess',*args,'--output',str(report)],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        p=json.loads(report.read_text());self.assertTrue(report.with_suffix('.html').exists())
        result=subprocess.run(common+['continue',*args,'--proposal-digest',p['proposal_digest'],'--output',str(directory/'continued.json')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        outcome=json.loads((directory/'continued.json').read_text())['continuation']
        self.assertEqual(outcome['actions'],64);self.assertEqual(outcome['confirmed'],12)
        self.assertEqual(outcome['final_validation'],'awaiting_observation')
        result=subprocess.run(common+['continue',*args,'--proposal-digest',p['proposal_digest'],'--output',str(directory/'replay.json')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(self.journal.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],2)

    def test_robot_backend_cannot_be_recovered_as_acknowledgements(self):
        _,row=self.stopped();o=self.observation(row);p=assess_recovery(row,o)
        job=deepcopy(row['job']);job['execution_backend']='panda_moveit_kinematic'
        self.journal.db.execute('UPDATE runs SET job=? WHERE run_id=?',(json.dumps(job),row['run_id']))
        with self.assertRaisesRegex(ValueError,'robot adapters'):
            self.journal.recover_simulation(row['run_id'],o,SimulatedAdapter(),expected_proposal_digest=p['proposal_digest'])


if __name__=='__main__':unittest.main()

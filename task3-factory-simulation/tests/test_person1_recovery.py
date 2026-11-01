"""Preserve the producer's classified staged batch throughout recovery."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from execution import SimulatedAdapter
from integration.journal import Journal
from integration.person1_simulation import prepare_person1_simulation
from integration.recovery import assess_recovery,basis_digest
from integration.validation import plan_digest

ROOT=Path(__file__).resolve().parents[1]


class Person1RecoveryTests(unittest.TestCase):
    inventory_fixture='examples/person1/inventory_with_color.json'
    def setUp(self):
        read=lambda name:json.loads((ROOT/name).read_text())
        self.bundle=prepare_person1_simulation(read(self.inventory_fixture),read('config/cell_panda.json'))
        self.folder=tempfile.TemporaryDirectory();self.journal=Journal(Path(self.folder.name)/'state.sqlite3')
        parent=self.journal.create(self.bundle['staged_snapshot'],self.bundle['job'],SimulatedAdapter(5,'approach_pick',True))
        while parent.session.status not in ('stopped','completed'):parent.advance()
        self.row=self.journal.inspect(parent.run_id)
        prefix=deepcopy(self.row['job']['plan']['placements'][:4]);placed={p['brick_id'] for p in prefix}
        self.observation=dict(schema_version='cell-reconciliation-0.1',run_id=parent.run_id,plan_digest=plan_digest(self.row['job']['plan']),basis_digest=basis_digest(self.row),observation_id='person1-reference-test',source='synthetic',coverage='complete',gripper={'state':'empty'},robot={'state':'safe_home'},placements=prefix,inventory=[deepcopy(b) for b in self.row['snapshot']['items'] if b['id'] not in placed],missing_ids=[],frame='world',units='m',source_poses={bid:deepcopy(pose) for bid,pose in self.row['job']['source_poses'].items() if bid not in placed})

    def tearDown(self):self.journal.close();self.folder.cleanup()

    def test_child_preserves_recipe_ids_scores_and_producer_metadata(self):
        before=deepcopy(self.row)
        proposal=assess_recovery(self.row,self.observation)
        self.assertEqual(proposal['status'],'ready')
        self.assertEqual(proposal['replacements'],[])
        self.assertEqual(proposal['job']['person1_handoff'],self.bundle['handoff'])
        self.assertEqual(proposal['job']['plan'],self.bundle['plan'])
        self.assertEqual(proposal['snapshot']['producer'],self.bundle['staged_snapshot']['producer'])
        self.assertEqual(len(proposal['job']['commands']),64)
        self.assertEqual(min(c['step'] for c in proposal['job']['commands']),5)
        child=self.journal.recover_simulation(self.row['run_id'],self.observation,SimulatedAdapter(),expected_proposal_digest=proposal['proposal_digest'])
        while child.session.status not in ('stopped','completed'):child.advance()
        self.assertEqual(child.session.status,'completed')
        self.assertEqual(len(child.session.confirmed),12)
        self.assertEqual(len(child.session.events),64)
        self.assertEqual(child.session.confirmed,self.bundle['plan']['placements'])
        saved=self.journal.inspect(child.run_id)
        original={b['id']:(b['color_group'],b['score']) for b in self.bundle['staged_snapshot']['items']}
        actual={b['id']:(b['color_group'],b['score']) for b in saved['snapshot']['items']}
        self.assertEqual(actual,original)
        parent=self.journal.inspect(self.row['run_id'])
        self.assertEqual(parent['checkpoint'],before['checkpoint']);self.assertEqual(parent['pending'],before['pending'])
        self.assertEqual(parent['status'],'superseded')

    def test_class_or_score_changes_cannot_be_smuggled_into_reconciliation(self):
        for field,value in [('color_group','other_group'),('score',.999)]:
            observation=deepcopy(self.observation);observation['inventory'][0][field]=value
            proposal=assess_recovery(self.row,observation)
            self.assertEqual(proposal['status'],'blocked')
            self.assertIn('person1_producer_classification_changed',{i['kind'] for i in proposal['issues']})
            self.assertIsNone(proposal['job'])
            self.assertEqual(self.journal.inspect(self.row['run_id']),self.row)

    def test_unstaged_ids_are_not_added_as_if_already_present_in_scene(self):
        observation=deepcopy(self.observation)
        old=observation['inventory'][0]['id'];new='not_in_this_staged_batch'
        observation['inventory'][0]['id']=new
        observation['source_poses'][new]=observation['source_poses'].pop(old)
        proposal=assess_recovery(self.row,observation)
        self.assertEqual(proposal['status'],'blocked')
        self.assertIn('person1_unrecognized_staged_id',{i['kind'] for i in proposal['issues']})


class Person1ThreeGroupRecoveryTests(Person1RecoveryTests):
    inventory_fixture='examples/person1/inventory_three_groups.json'


if __name__=='__main__':unittest.main()

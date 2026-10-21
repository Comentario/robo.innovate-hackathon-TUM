"""Reference labels are explicit operator evidence, never automatic detector ground truth."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from integration.person1_reference import template,evaluate,render_report

ROOT=Path(__file__).resolve().parents[1]


class ReferenceReviewTests(unittest.TestCase):
    def setUp(self):
        fixture=ROOT/'examples/person1'
        self.inventory=json.loads((fixture/'inventory_with_color.json').read_text())
        self.image=(fixture/'bricks_70.png').read_bytes()
        self.config=json.loads((fixture/'config.json').read_text())
        self.review=template(self.inventory,self.image)

    def evaluate(self,review=None):return evaluate(self.inventory,self.image,self.review if review is None else review,self.config)

    def add_labels(self):
        self.review.update(reviewer='TEST FIXTURE - not human evidence',group_definitions={'color_group_1':'TEST definition one','color_group_2':'TEST definition two'})
        self.review['annotations']=[{'id':'brick_001','reference_group':'color_group_1'}, {'id':'brick_002','reference_group':'color_group_1'}, {'id':'brick_022','reference_group':'uncertain','note':'TEST uncertainty'}]

    def test_empty_template_has_no_inferred_labels_or_accuracy(self):
        self.assertEqual(self.review['annotations'],[])
        result=self.evaluate()
        self.assertEqual(result['status'],'awaiting_reference_labels')
        self.assertEqual(result['coverage'],0)
        self.assertEqual(len(result['unreviewed_ids']),70)
        self.assertFalse(result['threshold_validated'])
        self.assertIsNone(result['recommended_threshold'])
        self.assertTrue(all(row['agreement_fraction'] is None for row in result['thresholds']))

    def test_partial_reference_preserves_denominators_and_uncertainty(self):
        self.add_labels();before=deepcopy(self.review)
        result=self.evaluate()
        self.assertEqual(result['classified'],2)
        self.assertEqual(result['uncertain_ids'],['brick_022'])
        self.assertEqual(len(result['unreviewed_ids']),67)
        row=next(r for r in result['thresholds'] if r['threshold']==.5)
        self.assertEqual((row['accepted_count'],row['reviewed_accepted'],row['agreement_count'],row['disagreement_count'],row['unreviewed_or_uncertain_accepted']),(57,2,1,1,55))
        self.assertEqual(row['agreement_fraction'],.5)
        self.assertEqual(row['disagreement_ids'],['brick_002'])
        high=next(r for r in result['thresholds'] if r['threshold']==.75)
        self.assertIsNone(high['agreement_fraction'])
        self.assertEqual((high['discarded_agreement_count'],high['discarded_disagreement_count']),(1,1))
        self.assertFalse(high['plan_feasible'])
        self.assertEqual(result['confusion']['color_group_1']['color_group_2'],1)
        self.assertEqual(self.review,before)
        modified=deepcopy(self.review);modified['annotations'][0]['note']='A revised review note'
        self.assertNotEqual(result['reference_sha256'],self.evaluate(modified)['reference_sha256'])

    def test_even_complete_agreement_does_not_validate_a_threshold(self):
        self.add_labels()
        self.review['annotations']=[dict(id=b['id'],reference_group=b['color_group']) for b in self.inventory['bricks']]
        result=self.evaluate()
        self.assertEqual(result['status'],'operator_review_complete')
        self.assertEqual(result['coverage'],1.)
        self.assertFalse(result['physical_validation'])
        self.assertFalse(result['threshold_validated'])
        self.assertIsNone(result['recommended_threshold'])

    def test_wrong_capture_or_invalid_annotations_are_rejected(self):
        self.add_labels()
        changes=[lambda v:v.update(image_sha256='other'),lambda v:v.update(inventory_sha256='other'),lambda v:v.update(image_id='other'),lambda v:v.update(reviewer=''),lambda v:v['group_definitions'].update(color_group_1=''),lambda v:v.update(predictions_visible_during_session='false'),lambda v:v['annotations'].append(v['annotations'][0]),lambda v:v['annotations'][0].update(id='unknown-id'),lambda v:v['annotations'][0].update(reference_group='dark')]
        for change in changes:
            value=deepcopy(self.review);change(value)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.evaluate(value)
        with self.assertRaises(ValueError):evaluate(self.inventory,b'not a PNG',self.review,self.config)

    def test_geometry_exclusions_cannot_be_overridden_by_operator_color_label(self):
        self.inventory['bricks'][0]['possible_merge']=True
        self.review=template(self.inventory,self.image);self.add_labels()
        result=self.evaluate();row=result['thresholds'][0]
        self.assertEqual(row['reviewed_accepted'],1)
        self.assertEqual(row['discarded_agreement_count'],1)

    def test_cli_empty_evaluation_is_explicit_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            reference=Path(folder)/'reference.json';reference.write_text(json.dumps(self.review))
            output=Path(folder)/'evaluation'
            command=[sys.executable,'-m','integration.person1_reference','evaluate','--annotations',str(reference),'--output-dir',str(output)]
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('awaiting_reference_labels',result.stdout)
            self.assertTrue((output/'index.html').exists())
            before=(output/'evaluation.json').read_bytes()
            self.assertEqual(subprocess.run(command,cwd=ROOT,capture_output=True).returncode,2)
            self.assertEqual((output/'evaluation.json').read_bytes(),before)


if __name__=='__main__':unittest.main()

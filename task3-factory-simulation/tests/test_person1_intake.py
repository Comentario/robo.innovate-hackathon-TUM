"""Contract and execution-boundary checks for the delivered perception inventory."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from integration import prepare
from integration.person1_intake import convert_inventory

ROOT=Path(__file__).resolve().parents[1]


class Person1IntakeTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/'examples/person1/inventory_with_color.json').read_text())
        self.config=json.loads((ROOT/'examples/person1/config.json').read_text())

    def test_real_delivery_filtered_and_planned_without_relabeling_or_mutation(self):
        before=deepcopy(self.value)
        snapshot,audit=convert_inventory(self.value,min_score=.5)
        self.assertEqual(audit['counts'],{'color_group_1':13,'color_group_2':44})
        self.assertEqual(len(audit['excluded']),13)
        _,plan,job=prepare(snapshot,self.config)
        self.assertIsNone(job)
        self.assertEqual(plan['blend'],{'color_group_1':6,'color_group_2':6})
        self.assertEqual(len({p['brick_id'] for p in plan['placements']}),12)
        self.assertEqual(self.value,before)
        self.assertFalse(snapshot['face_aware'])
        self.assertEqual(snapshot['source'],'perception')

    def test_real_pixels_cannot_be_dispatched_as_synthetic_grid_poses(self):
        snapshot,_=convert_inventory(self.value,min_score=.5)
        cell=json.loads((ROOT/'config/cell_panda.json').read_text())
        with self.assertRaisesRegex(ValueError,'measured source_poses'):prepare(snapshot,self.config,cell)
        self.assertNotIn('source_poses',snapshot)
        self.assertNotIn('frame',snapshot)

    def test_score_filter_changes_snapshot_identity_and_unknown_is_excluded(self):
        first,_=convert_inventory(self.value,min_score=0.)
        second,_=convert_inventory(self.value,min_score=.5)
        self.assertNotEqual(first['snapshot_id'],second['snapshot_id'])
        self.value['bricks'][0]['color_group']='unknown'
        _,audit=convert_inventory(self.value,min_score=0.)
        self.assertEqual(audit['excluded'][0]['reasons'],['unknown_color'])

    def test_uniform_and_three_group_exports_do_not_require_three_fixed_shades(self):
        for names,centers in [(['uniform'],[[50,0,0]]),(['color_group_1','color_group_2','color_group_3'],[[20,0,0],[50,0,0],[80,0,0]])]:
            value=deepcopy(self.value)
            value['color_estimation'].update(selected_k=len(names),group_centers_lab=centers)
            for i,b in enumerate(value['bricks']):b['color_group']=names[i%len(names)];b['color_score']=1.
            snapshot,_=convert_inventory(value,min_score=.5)
            self.assertEqual({b['color_group'] for b in snapshot['items']},set(names))

    def test_partial_merged_and_ineligible_detections_are_not_planned(self):
        for flag,val in [('is_partial',True),('possible_merge',True),('eligible_for_color',False)]:
            value=deepcopy(self.value);value['bricks'][0][flag]=val
            snapshot,audit=convert_inventory(value,min_score=0.)
            self.assertNotIn('brick_001',{b['id'] for b in snapshot['items']})
            self.assertIn('ineligible_geometry',audit['excluded'][0]['reasons'])

    def test_malformed_or_ambiguous_exports_are_refused(self):
        changes=[lambda v:v.update(processing_status='partial'),lambda v:v['color_estimation'].update(status='inconclusive'),
            lambda v:v['color_estimation'].update(selected_k=True),lambda v:v['color_estimation'].update(group_centers_lab=[[float('nan'),0,0],[90,0,0]]),
            lambda v:v['bricks'][1].update(id='brick_001'),lambda v:v['bricks'][0].update(color_score=float('nan')),
            lambda v:v['bricks'][0].update(color_group='dark'),lambda v:v['bricks'][0]['bbox_px'].update(x=-1),
            lambda v:v['bricks'][0]['center_px'].update(x=9999),lambda v:v['bricks'][0].update(is_partial='false')]
        for change in changes:
            value=deepcopy(self.value);change(value)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):convert_inventory(value,min_score=.5)
        for threshold in [True,-1,2,float('inf')]:
            with self.assertRaises(ValueError):convert_inventory(self.value,min_score=threshold)

    def test_original_demo_recipe_is_not_silently_mapped_onto_relative_groups(self):
        snapshot,_=convert_inventory(self.value,min_score=.5)
        old=json.loads((ROOT/'config/mixed.json').read_text())
        with self.assertRaises(ValueError):prepare(snapshot,old)


if __name__=='__main__':unittest.main()

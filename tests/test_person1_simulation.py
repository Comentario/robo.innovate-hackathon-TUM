"""The producer owns classification; staging owns only synthetic robot geometry."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from integration import prepare
from integration.person1_simulation import prepare_person1_simulation
from execution import ExecutionSession,SimulatedAdapter

ROOT=Path(__file__).resolve().parents[1]


class Person1SimulationTests(unittest.TestCase):
    def setUp(self):
        self.inventory=json.loads((ROOT/'examples/person1/inventory_with_color.json').read_text())
        self.cell=json.loads((ROOT/'config/cell_panda.json').read_text())

    def test_original_labels_and_scores_feed_plan_and_96_simulated_actions(self):
        before=deepcopy(self.inventory)
        bundle=prepare_person1_simulation(self.inventory,self.cell)
        self.assertEqual(bundle['handoff']['eligible_count'],70)
        self.assertEqual(bundle['handoff']['excluded'],[])
        self.assertFalse(bundle['handoff']['additional_score_filter'])
        self.assertEqual(len(bundle['handoff']['unstaged_eligible_ids']),58)
        original={b['id']:b for b in self.inventory['bricks']}
        for item in bundle['staged_snapshot']['items']:
            self.assertEqual(item['color_group'],original[item['id']]['color_group'])
            self.assertEqual(item['score'],original[item['id']]['color_score'])
        self.assertEqual(bundle['observed_snapshot']['source'],'perception')
        self.assertEqual(bundle['staged_snapshot']['source'],'synthetic')
        self.assertNotIn('source_poses',bundle['observed_snapshot'])
        self.assertEqual(len(bundle['job']['source_poses']),12)
        self.assertEqual(len(bundle['job']['commands']),96)
        session=ExecutionSession(bundle['job'],SimulatedAdapter())
        while session.status not in ('stopped','completed'):session.advance()
        self.assertEqual(session.status,'completed')
        self.assertEqual(len(session.confirmed),12)
        self.assertEqual(self.inventory,before)

    def test_no_additional_gate_discards_even_the_lowest_delivered_score(self):
        bundle=prepare_person1_simulation(self.inventory,self.cell)
        self.assertEqual(len(bundle['observed_snapshot']['items']),70)
        self.assertAlmostEqual(min(b['score'] for b in bundle['observed_snapshot']['items']),.001)
        with self.assertRaisesRegex(ValueError,'measured source_poses'):
            prepare(bundle['observed_snapshot'],bundle['handoff']['recipe'],self.cell)

    def test_received_group_count_is_not_replaced_by_our_old_shades(self):
        for count in (1,3):
            value=deepcopy(self.inventory)
            names=['uniform'] if count==1 else ['color_group_1','color_group_2','color_group_3']
            centers=[[50,0,0]] if count==1 else [[20,2,1],[50,4,3],[80,6,5]]
            value['color_estimation'].update(selected_k=count,group_centers_lab=centers)
            for i,brick in enumerate(value['bricks']):brick['color_group']=names[i%count]
            bundle=prepare_person1_simulation(value,self.cell)
            self.assertEqual(bundle['plan']['blend'],dict.fromkeys(names,12//count))
            self.assertEqual(set(bundle['handoff']['group_centers_lab']),set(names))
            self.assertFalse(bundle['staged_snapshot']['face_aware'])

    def test_explicit_recipe_is_honored_and_unavailable_classes_are_not_invented(self):
        config=dict(rows=2,columns=3,layers=2,target_ratios={'color_group_1':1,'color_group_2':2},mode='mixed',shortage_policy='reject')
        bundle=prepare_person1_simulation(self.inventory,self.cell,config)
        self.assertEqual(bundle['plan']['blend'],{'color_group_1':4,'color_group_2':8})
        old=json.loads((ROOT/'config/mixed.json').read_text())
        with self.assertRaises(ValueError):prepare_person1_simulation(self.inventory,self.cell,old)


if __name__=='__main__':unittest.main()

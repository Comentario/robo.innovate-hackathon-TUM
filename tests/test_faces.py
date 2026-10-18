from copy import deepcopy
import json
from pathlib import Path
import unittest

from demo import run_demo, validate_plan
from planning.faces import make_face_plan

ROOT = Path(__file__).resolve().parents[1]


def brick(bid, **faces):
    return dict(id=bid, faces={f:dict(color_group=g) if g else None for f,g in faces.items()},
                allowed_orientations=[dict(id=f'{f}_out', visible_face=f) for f in faces])


class FacePlanningTests(unittest.TestCase):
    def test_matching_preserves_flexible_brick_for_scarce_shade(self):
        inventory = [brick('a', front='dark', back='light'), brick('b', front='dark')]
        original = deepcopy(inventory)
        plan = make_face_plan(inventory, rows=1, columns=2, target_ratios=dict(dark=1, light=1))
        chosen = {p['brick_id']:p for p in plan['placements']}
        self.assertEqual(chosen['a']['visible_face'], 'back')
        self.assertEqual(chosen['a']['color_group'], 'light')
        self.assertEqual(chosen['b']['color_group'], 'dark')
        self.assertEqual(inventory, original)
        validate_plan(plan, inventory)

    def test_unknown_and_forbidden_faces_never_selected(self):
        inventory = [brick('a', front='dark', back='light', top=None)]
        inventory[0]['allowed_orientations'] = [dict(id='front_out', visible_face='front'),
                                               dict(id='top_out', visible_face='top')]
        with self.assertRaises(ValueError):
            make_face_plan(inventory, rows=1, columns=1, target_ratios=dict(light=1))
        plan = make_face_plan(inventory, rows=1, columns=1, target_ratios=dict(dark=1))
        self.assertEqual(plan['placements'][0]['visible_face'], 'front')
        self.assertEqual(plan['face_policy']['unknown_allowed_faces'], {'a':['top']})
        plan['placements'][0]['visible_face'] = 'top'
        with self.assertRaises(ValueError):
            validate_plan(plan, inventory)

    def test_one_brick_cannot_supply_two_faces_as_two_bricks(self):
        with self.assertRaises(ValueError):
            make_face_plan([brick('a', front='dark', back='light')], rows=1, columns=2,
                           target_ratios=dict(dark=1, light=1))

    def test_redistribution_and_face_demo_failure(self):
        inventory = [brick('a', front='dark'), brick('b', front='dark')]
        plan = make_face_plan(inventory, rows=1, columns=2, target_ratios=dict(dark=1,light=1),
                              shortage_policy='redistribute')
        self.assertEqual(plan['metrics']['ratio_l1_error'], 1)
        config = dict(rows=1, columns=2, target_ratios=dict(dark=1))
        report = run_demo(inventory, config, face_aware=True, fail_step=2)
        self.assertEqual(len(report['confirmed_placements']), 1)
        self.assertEqual(report['status'], 'stopped')

    def test_example_selects_faces_for_recipe_deterministically(self):
        inventory = json.loads((ROOT/'examples/faces/inventory.json').read_text())
        config = json.loads((ROOT/'examples/faces/config.json').read_text())
        plan = make_face_plan(inventory, **config)
        self.assertEqual(plan, make_face_plan(list(reversed(inventory)), **config))
        self.assertEqual(plan['blend'], dict(dark=4, medium=4, light=4))
        self.assertEqual(len({p['brick_id'] for p in plan['placements']}), 12)
        self.assertTrue(any(p['visible_face'] == 'back' for p in plan['placements']))
        self.assertTrue(all(p['visible_face'] != 'top' for p in plan['placements']))
        validate_plan(plan, inventory)

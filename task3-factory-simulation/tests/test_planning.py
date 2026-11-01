import copy
import unittest
from collections import Counter
from planning import make_plan


def stock(**groups):
    return [dict(id=f'{group}_{i}', color_group=group)
            for group, count in groups.items() for i in range(count)]


class PlanningTests(unittest.TestCase):
    def test_complete_unique_supported_and_deterministic(self):
        inventory = stock(dark=8, medium=8, light=8)
        original = copy.deepcopy(inventory)
        plan = make_plan(inventory, rows=2, columns=3, layers=2)
        self.assertEqual(plan, make_plan(list(reversed(inventory)), rows=2, columns=3, layers=2))
        self.assertEqual(inventory, original)
        places = plan['placements']
        self.assertEqual(len({p['brick_id'] for p in places}), 12)
        self.assertEqual(Counter(p['color_group'] for p in places), dict(dark=4, medium=4, light=4))
        self.assertEqual([(p['layer'], p['row'], p['column']) for p in places],
                         [(l,r,c) for l in range(2) for r in range(2) for c in range(3)])
        self.assertEqual([p['step'] for p in places], list(range(1,13)))

    def test_two_tones_avoid_neighbors(self):
        plan = make_plan(stock(dark=4, light=4), rows=2, columns=2, layers=2)
        self.assertEqual(plan['metrics']['same_tone_neighbors'], 0)
        self.assertEqual(plan['metrics']['neighbor_pairs'], 12)

    def test_recipe_and_shortage_are_reported(self):
        plan = make_plan(stock(dark=1, light=8), rows=2, columns=2,
                         target_ratios=dict(dark=1, light=1))
        self.assertEqual(plan['blend'], dict(dark=1, light=3))
        self.assertEqual(plan['metrics']['ratio_l1_error'], 0.5)

    def test_default_preserves_proportions(self):
        plan = make_plan(stock(dark=6, light=2), rows=1, columns=4)
        self.assertEqual(plan['blend'], dict(dark=3, light=1))

    def test_missing_category_reported(self):
        plan = make_plan(stock(light=4), rows=1, columns=4,
                         target_ratios=dict(dark=1, light=1))
        self.assertEqual(plan['blend'], dict(dark=0, light=4))
        self.assertEqual(plan['metrics']['ratio_l1_error'], 1)

    def test_smooth_uses_tone_distance_and_keeps_recipe(self):
        inventory = stock(dark=2, medium=2, light=2)
        tones = dict(dark=0, medium=0.5, light=1)
        mixed = make_plan(inventory, rows=1, columns=6)
        smooth = make_plan(inventory, rows=1, columns=6, mode='smooth', tone_values=tones)
        def distance(plan):
            groups = [p['color_group'] for p in plan['placements']]
            return sum(abs(tones[a] - tones[b]) for a,b in zip(groups, groups[1:])) / 5
        self.assertLess(distance(smooth), distance(mixed))
        self.assertEqual(smooth['blend'], mixed['blend'])
        self.assertAlmostEqual(smooth['metrics']['mean_neighbor_tone_distance'], distance(smooth))

    def test_strict_recipe_rejects_substitution_but_allows_rounding(self):
        with self.assertRaises(ValueError):
            make_plan(stock(dark=1, light=8), rows=1, columns=4,
                      target_ratios=dict(dark=1, light=1), shortage_policy='reject')
        plan = make_plan(stock(dark=3, light=3), rows=1, columns=3,
                         target_ratios=dict(dark=1, light=1), shortage_policy='reject')
        self.assertEqual(sum(plan['blend'].values()), 3)

    def test_invalid_policy(self):
        for options in (dict(mode='unknown'), dict(shortage_policy='unknown'),
                        dict(mode='smooth'), dict(mode='smooth', tone_values={'dark': 2})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                make_plan(stock(dark=2), rows=1, columns=2, **options)

    def test_invalid_contracts(self):
        cases = [([], {}), (stock(dark=1), {}),
                 ([dict(id='x', color_group='dark')]*2, {}),
                 ([dict(id=1, color_group='dark')], {}),
                 (stock(dark=4), dict(target_ratios={'dark': 0})),
                 (stock(dark=4), dict(target_ratios={'dark': float('nan')})),
                 (stock(dark=4), dict(target_ratios={'dark': -1})),
                 (stock(dark=4), dict(target_ratios={'light': 1})),
                 (stock(dark=4), dict(rows=True)),
                 (stock(dark=4), dict(columns=0))]
        for inventory, options in cases:
            with self.subTest(options=options, inventory=inventory):
                args = dict(rows=1, columns=2)
                args.update(options)
                with self.assertRaises(ValueError):
                    make_plan(inventory, **args)


if __name__ == '__main__':
    unittest.main()

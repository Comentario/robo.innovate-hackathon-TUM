from collections import Counter
import unittest
from planning import make_plan


def stock(**counts):
    return [dict(id=f'{g}_{i}', color_group=g) for g,n in counts.items() for i in range(n)]


class LocalBalanceTests(unittest.TestCase):
    def test_mixed_balances_each_layer_and_row_when_exactly_feasible(self):
        plan = make_plan(stock(dark=4, medium=4, light=4), rows=2, columns=3, layers=2)
        quality = plan['metrics']['distribution']
        for layer in quality['layers']:
            self.assertEqual(layer['counts'], dict(dark=2, medium=2, light=2))
            self.assertEqual(layer['distribution_l1_error'], 0)
        for row in quality['rows']:
            self.assertEqual(row['counts'], dict(dark=1, medium=1, light=1))

    def test_availability_error_is_separate_from_distribution(self):
        plan = make_plan(stock(dark=12), rows=2, columns=3, layers=2,
                         target_ratios=dict(dark=1, medium=1, light=1))
        self.assertGreater(plan['metrics']['ratio_l1_error'], 1)
        for layer in plan['metrics']['distribution']['layers']:
            self.assertEqual(layer['distribution_l1_error'], 0)
            self.assertGreater(layer['recipe_l1_error'], 1)

    def test_uneven_and_single_cell_plans_keep_counts_and_unique_ids(self):
        for shape in ((1,1,1),(2,2,3),(3,5,2)):
            rows,columns,layers = shape
            capacity = rows*columns*layers
            inventory = stock(dark=capacity, medium=capacity, light=capacity)
            plan = make_plan(inventory, rows=rows, columns=columns, layers=layers)
            self.assertEqual(Counter(p['color_group'] for p in plan['placements']), Counter(plan['blend']))
            self.assertEqual(len({p['brick_id'] for p in plan['placements']}), capacity)

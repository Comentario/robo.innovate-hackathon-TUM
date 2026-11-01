"""Independent checks of selective correction and capacity accounting."""
import unittest
from greenfield.layer_study import plan_layer,valid_mix,synthetic_layers,LayerRepairStudy

class LayerStudyTests(unittest.TestCase):
    def test_preserves_an_already_valid_layer(self):
        grid=[(r+c)%3 for r in range(4) for c in range(10)]
        self.assertEqual(plan_layer(grid,[True]*40),grid)
    def test_rejects_vertical_triples_without_discarding_the_mix_constraint(self):
        old=[(r+c)%3 for r in range(4) for c in range(10)]
        new=plan_layer(old,[True]*40,[old,old])
        self.assertTrue(valid_mix(new,[old,old]));self.assertTrue(all(a!=b for a,b in zip(old,new)))
    def test_stock_and_pallet_accounting_and_faster_parallel_correction(self):
        layers=synthetic_layers(18,stacks=2)
        slow=LayerRepairStudy(layers,1,5.).run();fast=LayerRepairStudy(layers,2,5.).run()
        self.assertLess(fast['seconds'],slow['seconds'])
        for result in (slow,fast):
            self.assertEqual(result['input_bricks'],1600);self.assertEqual(result['processed_bricks'],1600)
            self.assertEqual(result['shipped_bricks']+result['partial_bricks'],1600)
            self.assertEqual(1600+result['initial_spares']+result['replenished_spares'],1600+result['rejected_bricks']+result['final_spare_stock'])
    def test_no_rejects_are_reintroduced_when_every_input_is_bad(self):
        result=LayerRepairStudy(synthetic_layers(2,defect_rate=1.,stacks=2),2).run()
        self.assertEqual(result['rejected_bricks'],1600);self.assertEqual(result['good_bricks_returned_to_stock'],0)
        self.assertEqual(result['repaired_positions'],1600);self.assertTrue(result['material_balance_ok'])
    def test_availability_sensitivity_is_explicit_and_slower(self):
        layers=synthetic_layers(8,stacks=2)
        nominal=LayerRepairStudy(layers,2,5.,1.).run();derated=LayerRepairStudy(layers,2,5.,.85).run()
        self.assertAlmostEqual(derated['shipped_bph']/nominal['shipped_bph'],.85)
    def test_invalid_resource_assumptions_are_rejected(self):
        for heads,cycle,availability in [(0,5,1),(3,5,1),(1,0,1),(1,5,0),(1,5,1.1)]:
            with self.assertRaises(ValueError):LayerRepairStudy([[],[]],heads,cycle,availability)

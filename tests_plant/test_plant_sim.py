"""Independent material, routing, fault and capacity contracts for Task 3."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from plant_sim.model import Plant

ROOT = Path(__file__).resolve().parents[1]


class PlantContracts(unittest.TestCase):
    def config(self, **changes):
        c = json.loads((ROOT/'config/plant_demo.json').read_text())
        c['input_stacks'] = 1
        c.update(changes)
        return c

    def test_exact_material_balance_and_pallet_boundary(self):
        r = Plant(self.config(input_stacks=2)).run()
        k = r['kpis']
        self.assertEqual(r['status'], 'completed')
        self.assertEqual((k['output_bricks'], k['full_output_pallets'], k['partial_output_pallet_bricks']), (1600,2,480))
        self.assertEqual(k['bad_output_bricks'], 0)
        material = r['material']
        ids = [b['id'] for b in material]
        self.assertEqual(len(ids), len(set(ids)))
        output = r['pallets'][0]+r['pallets'][1]+r['partial_pallet']
        self.assertEqual(len(output), len(set(output)))
        self.assertEqual(set(output), {b['id'] for b in material if b['location']=='output'})
        self.assertEqual(k['initial_reserve']+k['input_bricks'], sum(r['material_locations'].values()))
        self.assertEqual(k['quality_replacements'], sum(not b['good'] and b['origin']=='input' for b in material))
        self.assertEqual(k['reserve_remaining']+k['quality_replacements'], k['initial_reserve'])

    def test_inspection_only_after_separation_pair_only_after_both_layers(self):
        r = Plant(self.config()).run()
        separated, corrected = {}, {}
        for e in r['events']:
            if e['kind']=='operation_end' and e['station']=='separator':
                separated[e['pair']]=e['t']
            if e['kind']=='inspection':
                self.assertIn(e['pair'], separated)
                self.assertGreaterEqual(e['t'], separated[e['pair']])
                self.assertEqual(len(e['ids']),40)
            if e['kind']=='layer_corrected':
                corrected.setdefault(e['pair'], set()).add(e['lane'])
            if e['kind']=='operation_start' and e['station']=='pairer':
                self.assertEqual(corrected[e['pair']], {0,1})

    def test_shared_robot_never_overlaps_and_admission_is_bounded(self):
        c=self.config(defect_rate=.4, replacement_per_shade=1000)
        r=Plant(c).run()
        occupied=False
        inflight=0
        for e in r['events']:
            if e['station'].startswith('robot_') and e['kind']=='operation_start':
                self.assertFalse(occupied)
                occupied=True
            if e['station'].startswith('robot_') and e['kind']=='operation_end':
                occupied=False
            if e['kind']=='pair_admitted':
                inflight+=1
                self.assertLessEqual(inflight,c['inflight_pairs'])
            if e['kind']=='pair_completed':
                inflight-=1
        self.assertFalse(occupied)
        self.assertEqual(inflight,0)
        self.assertTrue(all(x<=c['buffer_pairs'] for x in r['buffer_max_occupancy'].values()))

    def test_stockout_does_not_remove_an_unreplaceable_brick(self):
        r=Plant(self.config(replacement_per_shade=0,defect_rate=1)).run()
        self.assertEqual(r['status'],'blocked')
        self.assertEqual(r['kpis']['rejected_bricks'],0)
        self.assertEqual(r['kpis']['output_bricks'],0)
        self.assertTrue(r['kpis']['material_balance_ok'])
        self.assertIn('supply',r['reason'])

    def test_end_limit_timeout_halts_all_drives_without_resume(self):
        r=Plant(self.config(fault={'station':'separator','pair':3})).run()
        self.assertEqual(r['status'],'blocked')
        self.assertIn('end_limit timeout',r['reason'])
        alarm=next(e for e in r['events'] if e['kind']=='alarm')
        self.assertFalse(any(e['kind']=='operation_start' and e['t']>alarm['t'] for e in r['events']))
        signals={}
        for e in r['events']:
            if e['kind']=='signal' and e['name']=='drive_enabled':
                signals[e['station']]=e['value']
        self.assertFalse(any(signals.values()))
        self.assertTrue(r['kpis']['material_balance_ok'])

    def test_hidden_truth_is_not_an_operational_quality_gate(self):
        r=Plant(self.config(defect_rate=1,false_accept_rate=1)).run()
        self.assertEqual(r['status'],'completed')
        self.assertEqual(r['kpis']['bad_output_bricks'],800)
        self.assertEqual(r['kpis']['quality_replacements'],0)
        r=Plant(self.config(defect_rate=0,false_reject_rate=1,replacement_per_shade=1000)).run()
        self.assertEqual(r['kpis']['good_bricks_rejected'],800)

    def test_capacity_changes_affect_output_without_changing_input(self):
        c=self.config(defect_rate=.4,replacement_per_shade=1000)
        one=Plant(c).run()
        c['correction_robots']=2
        two=Plant(c).run()
        self.assertGreater(two['kpis']['conforming_bricks_per_hour'],one['kpis']['conforming_bricks_per_hour'])
        self.assertEqual(one['kpis']['quality_replacements'],two['kpis']['quality_replacements'])
        def inputs(r):
            return [(b['id'],b['shade'],b['good']) for b in r['material'] if b['origin']=='input']
        self.assertEqual(inputs(one),inputs(two))

    def test_mixing_exchanges_have_material_and_cycle_cost(self):
        c=self.config(input_pattern='stratified',replacement_per_shade=1000)
        base=Plant(c).run()
        c['mixing_budget_per_layer']=16
        mixed=Plant(c).run()
        self.assertEqual(mixed['status'],'completed')
        self.assertGreater(mixed['kpis']['mix_exchanges'],0)
        self.assertLess(mixed['kpis']['mean_layer_recipe_l1'],base['kpis']['mean_layer_recipe_l1'])
        self.assertLess(mixed['kpis']['output_bricks_per_hour'],base['kpis']['output_bricks_per_hour'])
        self.assertEqual(mixed['kpis']['reuse_buffer_bricks'],mixed['kpis']['mix_exchanges'])
        self.assertTrue(mixed['kpis']['material_balance_ok'])

    def test_reproducible_seed_and_horizon_accounting(self):
        c=self.config()
        self.assertEqual(Plant(c).run(),Plant(c).run())
        c['max_simulation_seconds']=150
        r=Plant(c).run()
        self.assertEqual(r['status'],'horizon_reached')
        self.assertTrue(r['kpis']['material_balance_ok'])
        self.assertGreater(r['kpis']['unprocessed_or_inflight_bricks'],0)

    def test_invalid_geometry_and_rates_rejected(self):
        c=self.config()
        for bad in (-1,float('nan'),float('inf')):
            x=deepcopy(c);x['arrival_bricks_per_hour']=bad
            with self.assertRaises(ValueError):Plant(x)
        c['geometry']['input_layers']=19
        with self.assertRaises(ValueError):Plant(c)


if __name__=='__main__':
    unittest.main()

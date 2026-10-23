import json
from pathlib import Path
import unittest
from plant_sim.model import Plant
from plant_sim.mechanics import compile_mechanics,validate_mechanics
from plant_sim.clearance import audit_clearances

ROOT=Path(__file__).resolve().parents[1]

class AutomationContracts(unittest.TestCase):
    def config(self):return json.loads((ROOT/'config/plant_demo.json').read_text())

    def test_infeed_time_is_distance_over_speed_plus_debounce(self):
        c=self.config();c['input_stacks']=1
        a=Plant(c).run();c['automation']['infeed_m_s']=.2;b=Plant(c).run()
        def first(r):return next(e for e in r['events'] if e['kind']=='operation_start' and e['station']=='infeed')
        self.assertAlmostEqual(first(a)['duration'],5.5/.4+.2)
        self.assertAlmostEqual(first(b)['duration'],5.5/.2+.2)
        for report in (a,b):
            for e in report['events']:
                if e['kind']=='sequence_step' and e['step']['kind']=='travel':
                    q=e['step'];self.assertAlmostEqual(q['duration_s'],q['distance_m']/q['speed_m_s'],places=7)

    def test_every_operation_duration_equals_its_sequence(self):
        r=Plant(self.config()).run()
        for e in r['events']:
            if e['kind']=='operation_start':
                self.assertAlmostEqual(e['duration'],sum(q['duration_s'] for q in e['motion_plan']['steps']),places=7)
        self.assertEqual(r['automation']['timing']['dominant_active_load'],'correction_robots')
        self.assertAlmostEqual(r['kpis']['output_bricks_per_hour'],1600*3600/r['simulated_seconds'],places=3)

    def test_legacy_seconds_do_not_drive_engineered_timing(self):
        c=self.config();c['input_stacks']=1;a=Plant(c).run()
        c['seconds']={'dehack':9999,'conveyor':1234};b=Plant(c).run()
        self.assertEqual(a['simulated_seconds'],b['simulated_seconds'])

    def test_join_nests_are_exclusive_and_released_after_completion(self):
        r=Plant(self.config()).run();occupied={}
        for e in r['events']:
            if e['kind']=='pair_admitted':
                self.assertNotIn(e['nest'],occupied);occupied[e['nest']]=e['pair']
            if e['kind']=='nest_released':self.assertEqual(occupied.pop(e['nest']),e['pair'])
        self.assertEqual(occupied,{})
        gates={}
        for e in r['events']:
            if e['kind']=='interlock_granted':
                self.assertNotIn(e['gate'],gates);gates[e['gate']]=e['pair']
            if e['kind']=='interlock_released':self.assertEqual(gates.pop(e['gate']),e['pair'])
        self.assertFalse(gates)

    def test_inspection_and_correction_have_separate_positions(self):
        r=Plant(self.config()).run();m=compile_mechanics(r)
        self.assertGreater(m['layout']['correction_x']-m['layout']['inspection_x'],1.)
        for e in r['events']:
            if e['kind']=='operation_start' and e['station'].startswith('robot_') and e['destination']!='layer':
                first=e['motion_plan']['brick_tracks'][e['brick']][0]['points'][0]
                self.assertLess(abs(first[1]-m['layout']['correction_x']),.15)

    def test_payload_paths_do_not_cross_fixed_equipment(self):
        r=Plant(self.config()).run();m=compile_mechanics(r)
        self.assertTrue(validate_mechanics(m)['continuous_brick_tracks'])
        result=audit_clearances(m)
        self.assertTrue(result['passed'],result['collisions'])
        self.assertGreater(result['tested_segments'],10000)

    def test_fast_axes_change_time_without_changing_input_quality(self):
        c=self.config();c['input_stacks']=1;a=Plant(c).run()
        c['automation']['robot_xy_m_s']*=2;c['automation']['robot_z_m_s']*=2;b=Plant(c).run()
        self.assertLess(b['simulated_seconds'],a['simulated_seconds'])
        self.assertEqual(b['kpis']['quality_replacements'],a['kpis']['quality_replacements'])

    def test_mix_reuse_path_clears_separator_structure(self):
        c=self.config();c['input_stacks']=1;c['input_pattern']='stratified';c['mixing_budget_per_layer']=4;c['replacement_per_shade']=1000
        r=Plant(c).run();result=audit_clearances(compile_mechanics(r))
        self.assertGreater(r['kpis']['mix_exchanges'],0)
        self.assertTrue(result['passed'],result['collisions'])

    def test_invalid_speed_rejected(self):
        for value in (0,-1,float('nan')):
            c=self.config();c['automation']['infeed_m_s']=value
            with self.assertRaises(ValueError):Plant(c)

if __name__=='__main__':unittest.main()

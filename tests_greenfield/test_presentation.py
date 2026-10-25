"""Presentation accounting must not alter or inflate the production result."""
import copy,json,unittest
from pathlib import Path
from greenfield.presentation import build_presentation,union_seconds
ROOT=Path(__file__).resolve().parents[1]
class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.report={'config':{'cells':8,'input_stacks':4},'mechanics':{'bay_z':[0,4,8,12],'tracks':{'INFEED-0':[{'t0':0,'t1':2},{'t0':1,'t1':3}],'ROW-SHUTTLE-0':[{'t0':0,'t1':1}]}},'timing':{'dehack_0':{'travel_s':2}},'kpis':{'shipped_good':2240,'full_pallets':4,'input_bricks':3200},'simulated_seconds':2073.7157979}
    def test_hourly_equivalent_uses_shipped_bricks_and_full_batch_time(self):
        original=copy.deepcopy(self.report);p=build_presentation(self.report)
        self.assertAlmostEqual(p['production']['normalized_bph'],3888.6717303143523)
        self.assertEqual(self.report,original)
        self.assertEqual(p['counts']['presence'],188);self.assertEqual(p['counts']['inspection_controllers'],16);self.assertEqual(p['counts']['controllers'],42)
    def test_budget_range_is_counted_once_then_integrated(self):
        p=build_presentation(self.report)
        for i in (0,1):
            self.assertAlmostEqual(p['hardware_usd'][i],sum(x['quantity']*x['unit_cost_usd'][i] for x in p['items']))
            self.assertAlmostEqual(p['investment_usd'][i],p['hardware_usd'][i]*(1+p['scenario']['integration_fraction'][i]))
    def test_energy_and_tariff_normalize_to_the_same_shipped_output(self):
        p=build_presentation(self.report)
        for i in (0,1):
            self.assertAlmostEqual(p['batch_energy_kwh'][i],p['average_power_kw'][i]*self.report['simulated_seconds']/3600)
            self.assertAlmostEqual(p['kwh_per_1000_shipped'][i],p['batch_energy_kwh'][i]/2240*1000)
            self.assertAlmostEqual(p['electricity_usd_per_1000'][i],p['kwh_per_1000_shipped'][i]*.1)
    def test_command_duty_does_not_double_count_overlapping_intervals(self):
        self.assertEqual(union_seconds([(0,2),(1,3),(5,6)]),4)
        p=build_presentation(self.report);d=next(x for x in p['items'] if x['id']=='pushers')['duty_fraction']
        self.assertAlmostEqual(d,3/(24*self.report['simulated_seconds']))

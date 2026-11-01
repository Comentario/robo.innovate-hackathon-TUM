"""Checks of the descending discard variant, using its generated report."""
import os,json,math,unittest
from pathlib import Path
from greenfield.interference import sweep_hit

@unittest.skipUnless(os.environ.get('GREENFIELD_DECLINE_REPORT'),'Needs generated decline report')
class DeclineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=json.loads(Path(os.environ['GREENFIELD_DECLINE_REPORT']).read_text())
    def test_no_discard_elevator_or_vertical_lift_cycle_exists(self):
        r=self.r;self.assertTrue(r['config']['declining_discard'])
        self.assertFalse(any(i.startswith('DISCARD-LIFT-') for i in r['mechanics']['initial']))
        self.assertEqual(r['mechanics']['discard_elevators'],0)
        self.assertFalse(any(e['kind']=='step' and e['station'].endswith('_discard_lift') for e in r['events']))
    def test_decline_is_downward_and_under_twenty_degrees(self):
        strokes=[s for seq in self.r['mechanics']['tracks'].values() for s in seq if s['label']=='Powered downward diagonal reject transfer']
        self.assertEqual(len(strokes),self.r['kpis']['discard_bricks'])
        for s in strokes:
            self.assertLess(s['to'][0],s['from'][0]);self.assertLess(s['to'][1],s['from'][1])
            angle=math.degrees(math.atan2(s['from'][1]-s['to'][1],s['from'][0]-s['to'][0]))
            self.assertGreater(angle,19);self.assertLess(angle,20)
    def test_full_batch_is_accounted_and_delivered(self):
        self.assertEqual(self.r['status'],'completed_with_residual_stock')
        self.assertEqual(self.r['kpis']['inspected'],3200);self.assertTrue(self.r['kpis']['material_balance_ok'])

class InclinedBoxTests(unittest.TestCase):
    def test_rotated_brick_has_larger_vertical_envelope(self):
        angle=.35;co,si=math.cos(angle),math.sin(angle);axes=[[co,si,0],[-si,co,0],[0,0,1]]
        floor={'min':[0,0,-1],'max':[1,.05,1]};half=[.1225,.0345,.0335]
        self.assertIsNone(sweep_hit([.5,.13,0],[.5,.13,0],half,floor,moving_axes=axes))
        self.assertIsNotNone(sweep_hit([.5,.09,0],[.5,.09,0],half,floor,moving_axes=axes))

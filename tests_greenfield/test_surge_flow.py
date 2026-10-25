"""Integration checks for bounded, same-height approved-stock accumulation."""
import json,os,unittest
from pathlib import Path
from collections import Counter
from greenfield.report import audit

@unittest.skipUnless(os.environ.get('GREENFIELD_SCENE_REPORT'),'Needs a generated report')
class SurgeFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=json.loads(Path(os.environ['GREENFIELD_SCENE_REPORT']).read_text())
    def test_no_aerial_picker_exists_or_executes(self):
        r=self.r;self.assertFalse(any(k.startswith('PICKER-') for k in r['mechanics']['initial']))
        self.assertFalse(any(s['label'] in ('Lift above approved stock','Automatic reserve return') for seq in r['mechanics']['tracks'].values() for s in seq))
    def test_every_surge_transfer_remains_at_conveyor_height(self):
        count=0
        for identity,seq in self.r['mechanics']['tracks'].items():
            for s in seq:
                if not s['station'].endswith('_surge'):continue
                expected=1.2845 if identity.startswith('B') else 1.25
                self.assertAlmostEqual(s['from'][1],expected);self.assertAlmostEqual(s['to'][1],expected);count+=1
        self.assertGreater(count,100)
    def test_whole_belt_moves_all_stored_pieces_by_the_same_displacement(self):
        r=self.r;count=0
        for e in r['events']:
            if e['kind']!='surge_belt_index':continue
            for identity in e['ids']:
                s=next(s for s in r['mechanics']['tracks'][identity] if s['label']=='Index entire reversible surge belt' and abs(s['t0']-e['t'])<1e-6)
                self.assertAlmostEqual(s['to'][0]-s['from'][0],e['delta_m']);self.assertEqual(s['from'][1:],s['to'][1:])
            count+=1
        self.assertGreater(count,10)
    def test_capacity_is_finite_and_every_output_keeps_spatial_constraints(self):
        r=self.r;self.assertEqual(r['status'],'completed_with_residual_stock');self.assertEqual(r['kpis']['input_bricks'],r['kpis']['inspected'])
        self.assertTrue(all(p['peak']<=r['config']['surge_slots_per_shade'] for p in r['surge_peaks']));self.assertTrue(audit(r)['mass_balance'])
    def test_rows_can_start_consuming_before_ten_observed_bricks_are_available(self):
        r=self.r;counts=[]
        for cell in range(8):
            first=min(s['t1'] for seq in r['mechanics']['tracks'].values() for s in seq if s['station']==f'cell_{cell}_selector' and s['label']=='Feed row inlet')
            counts.append(sum(e['kind']=='inspection' and e.get('decision')=='accepted' and e['station']==f'cell_{cell}_vision' and e['t']<=first for e in r['events']))
        self.assertTrue(any(n<10 for n in counts),counts)
    def test_sorter_uses_the_servo_ramp_instead_of_the_roller_ramp(self):
        for i in range(8):
            for s in self.r['mechanics']['tracks'][f'SORTER-{i}']:
                self.assertEqual(s['motion']['acceleration'],self.r['config']['motion_acceleration']['servo'])
    def test_band_handoffs_never_move_one_brick_while_stored_stock_is_stationary(self):
        r=self.r;m=r['mechanics'];count=0
        for identity,seq in m['tracks'].items():
            if not identity.startswith('B'):continue
            cell=next(b['cell'] for b in r['material'] if b['id']==identity)
            for s in seq:
                if not s['station'].endswith('_surge') or abs(s['to'][0]-s['from'][0])<1e-6:continue
                if abs(s['from'][2]-s['to'][2])>1e-6:continue
                if not any(abs(s['from'][2]-(m['cell_z'][cell]+1.55+.4*k))<1e-6 for k in range(3)):continue
                self.assertEqual(s['label'],'Index entire reversible surge belt');count+=1
        self.assertGreater(count,100)

    def test_dispatch_pressure_uses_observed_stock_and_penalizes_tone_imbalance(self):
        from greenfield.twin import TwinPlant
        plant=TwinPlant(self.r['config']);items=list(plant.material.values())
        for k,b in enumerate(items[:19]):
            b['cell']=0 if k<10 else 1;b['observed']='accepted';b['location']='accepted_buffer';b['shade']=plant.c['shades'][0 if k<10 else (k-10)%3]
        self.assertGreater(plant.dispatch_pressure(0),plant.dispatch_pressure(1))
        for b in items[:10]:b['observed']=None
        self.assertLess(plant.dispatch_pressure(0)[0],plant.dispatch_pressure(1)[0])

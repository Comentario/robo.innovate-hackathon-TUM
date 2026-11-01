"""Continuous-flow demo: encoder coupling, row dosing, completion and quality."""
import json,math,os,unittest
from pathlib import Path
from greenfield.flow import FlowPlant,loop_pose
from greenfield.clearance import pose

ROOT=Path(__file__).parents[1]
class EncoderTests(unittest.TestCase):
    def test_closed_path_and_tangent_orientation(self):
        for s in (0,.4,4.4,10.8,12.8,20.,25.5):
            p,a=loop_pose(s,-2,21.6);q,b=loop_pose(s+25.6,-2,21.6)
            for x,y in zip(p,q):self.assertAlmostEqual(x,y)
            self.assertAlmostEqual(math.cos(a),math.cos(b));self.assertAlmostEqual(math.sin(a),math.sin(b))
    def test_shared_drive_moves_every_occupant_and_compacts_exactly(self):
        c=json.loads((ROOT/'config/greenfield_flow.json').read_text());p=FlowPlant(c);ids=['B00000','B00001']
        for slot,identity in zip((0,4),ids):
            p.loop_stock[0][slot]=identity;p.positions[identity]=loop_pose(slot*.4,p.cell_z[0],p.loop_end)[0];p.initial[identity]=p.positions[identity][:]
        def two_ticks():
            for _ in range(2):
                yield from p.loop_advance(0,.4,1.5,1.5)
                p.loop_stock[0]={(k+1)%p.loop_slots:v for k,v in p.loop_stock[0].items()}
        p.env.process(two_ticks());p.env.run()
        for identity in ids:
            self.assertEqual(len(p.tracks[identity]),1);s=p.tracks[identity][0]
            self.assertAlmostEqual(s['loop_s1']-s['loop_s0'],.8)
            self.assertAlmostEqual(s['t1']-s['t0'],.8/1.5)
            self.assertAlmostEqual(s['motion']['start_speed'],s['motion']['end_speed'])
    def test_spacing_exceeds_rotating_brick_diagonal(self):
        radius=2/math.pi;minimum=2*radius*math.sin(.4/(2*radius))
        self.assertGreater(minimum,math.hypot(.245,.067))

@unittest.skipUnless(os.environ.get('GREENFIELD_FLOW_REPORT'),'Needs generated continuous-flow demo report')
class FlowReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=json.loads(Path(os.environ['GREENFIELD_FLOW_REPORT']).read_text())
    def test_complete_batch_and_delivery_exceeds_three_thousand(self):
        r=self.r;self.assertEqual(r['status'],'completed_with_residual_stock')
        self.assertEqual(r['kpis']['inspected'],3200);self.assertEqual(r['kpis']['full_pallets'],4)
        self.assertEqual(r['kpis']['shipped_bricks'],2240);self.assertTrue(r['kpis']['material_balance_ok'])
        self.assertGreater(r['kpis']['released_good_bph'],3000)
        self.assertAlmostEqual(r['kpis']['released_good_bph'],2240*3600/r['simulated_seconds'],places=2)
    def test_reserve_and_translating_grade_selectors_are_absent(self):
        r=self.r
        self.assertEqual(r['config']['accepted_overflow_capacity'],0);self.assertEqual(r['kpis']['overflow_routes'],0)
        self.assertEqual(r['mechanics']['loop_drives'],8);self.assertEqual(r['mechanics']['surge_belt_drives'],0)
        self.assertFalse(any(k.startswith(('SORTER-','SELECTOR-','PICKER-','DISCARD-LIFT-')) for k in r['mechanics']['initial']))
        self.assertLessEqual(max(r['mechanics']['loop_peaks']),r['config']['loop_capacity'])
    def test_all_remaining_bricks_share_each_transverse_belt_index(self):
        r=self.r;count=0
        for e in r['events']:
            if e['kind']!='transverse_belt_index':continue
            times=[]
            for identity in e['ids']:
                s=next(s for s in r['mechanics']['tracks'][identity] if abs(s['t0']-e['t'])<1e-6 and s['label']=='Index all occupants of transverse dosing belt')
                self.assertAlmostEqual(s['to'][2]-s['from'][2],-.067);times.append((s['t0'],s['t1']))
            self.assertEqual(len(set(times)),1);count+=1
        self.assertEqual(count,320*9)
    def test_one_wide_paddle_stroke_per_ten_brick_row(self):
        events=[e for e in self.r['events'] if e['kind']=='row_intake_push']
        self.assertEqual(len(events),320);self.assertTrue(all(len(e['ids'])==10 for e in events))
    def test_encoder_tracks_and_quality_are_preserved(self):
        r=self.r;speed=r['config']['loop_m_s'];count=0
        for seq in r['mechanics']['tracks'].values():
            for s in seq:
                if 'loop_s0' not in s:continue
                self.assertAlmostEqual(s['loop_s1']-s['loop_s0'],s['motion']['distance'],places=6)
                if s['motion']['end_speed']:
                    self.assertAlmostEqual(s['t1']-s['t0'],s['motion']['distance']/speed,places=6)
                count+=1
        self.assertGreater(count,2000);self.assertEqual(r['kpis']['bad_placed'],0)
        self.assertEqual(r['kpis']['monochrome_rows'],0);self.assertEqual(r['kpis']['monochrome_columns'],0)
        self.assertTrue(r['sampled_clearance']['passed'])

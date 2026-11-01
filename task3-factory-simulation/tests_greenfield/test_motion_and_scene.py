import json,os,unittest
from pathlib import Path
from greenfield.motion import profile,fraction
from greenfield.interference import sweep_hit,audit_scene
from greenfield.report import audit
from greenfield.model import pattern

class MotionAndSceneTests(unittest.TestCase):
    def test_short_stroke_cannot_instantly_reach_commanded_speed(self):
        p=profile(.01,1,1)
        self.assertAlmostEqual(p['duration'],.2);self.assertAlmostEqual(p['peak'],.1)
        self.assertEqual(fraction(0,p),0);self.assertEqual(fraction(p['duration'],p),1)
        self.assertAlmostEqual(fraction(.1,p),.5)
    def test_long_stroke_has_acceleration_cruise_and_deceleration(self):
        p=profile(2,1,2)
        self.assertAlmostEqual(p['duration'],2.5)
        values=[fraction(k*.025,p) for k in range(101)]
        self.assertEqual(values,sorted(values));self.assertAlmostEqual(values[50],.5)
    def test_sweep_detects_obstacle_missed_by_endpoint_sampling(self):
        o={'min':[.49,-.02,-.02],'max':[.51,.02,.02]}
        self.assertIsNotNone(sweep_hit([0,0,0],[1,0,0],[.01]*3,o))
        self.assertIsNone(sweep_hit([0,.1,0],[1,.1,0],[.01]*3,o))
    def test_contact_at_table_surface_is_permitted_but_penetration_is_not(self):
        o={'min':[0,0,0],'max':[1,1,1]}
        self.assertIsNone(sweep_hit([.2,1.1,.5],[.8,1.1,.5],[.1]*3,o))
        self.assertIsNotNone(sweep_hit([.2,1.09,.5],[.8,1.09,.5],[.1]*3,o))
    def test_no_three_equal_shades_in_any_layer_direction(self):
        for shift in range(12):
            q=[13,13,13];q[shift%3]+=1;g=pattern(4,10,q,shift,2)
            self.assertFalse(any(g[r*10+c]==g[r*10+c+1]==g[r*10+c+2] for r in range(4) for c in range(8)))
            self.assertFalse(any(g[r*10+c]==g[(r+1)*10+c]==g[(r+2)*10+c] for r in range(2) for c in range(10)))
    def test_oriented_rail_does_not_fill_its_axis_aligned_envelope(self):
        k=2**-.5;o={'min':[.06,.06,-.05],'max':[.94,.94,.05],'center':[.5,.5,0],'half':[.6,.02,.05],'axes':[[k,k,0],[-k,k,0],[0,0,1]]}
        self.assertIsNone(sweep_hit([0,.7,0],[.1,.7,0],[.01]*3,o))
        self.assertIsNotNone(sweep_hit([.2,.2,0],[.8,.8,0],[.01]*3,o))
    def test_through_running_profile_preserves_velocity_without_stopping(self):
        p=profile(.3,.3,1,.3,.3)
        self.assertAlmostEqual(p['duration'],1);self.assertEqual(p['accel_time'],0);self.assertEqual(p['decel_time'],0)
        for t in [0,.2,.5,.9,1]:self.assertAlmostEqual(fraction(t,p),t)
    def test_stop_profile_keeps_real_braking_distance(self):
        p=profile(.3,.3,1,.3,0)
        self.assertAlmostEqual(p['duration'],1.15);self.assertAlmostEqual(p['decel_time'],.3)
        with self.assertRaises(ValueError):profile(.01,.3,1,.3,0)
    @unittest.skipUnless(os.environ.get('GREENFIELD_SCENE_REPORT'),'Needs coordinated report')
    def test_nonzero_boundary_speed_has_continuous_time_and_reserved_braking_zone(self):
        r=json.loads(Path(os.environ['GREENFIELD_SCENE_REPORT']).read_text());count=0
        for identity,seq in r['mechanics']['tracks'].items():
            for k,s in enumerate(seq[:-1]):
                if not s.get('motion',{}).get('end_speed'):continue
                nxt=seq[k+1];count+=1
                self.assertAlmostEqual(nxt['t0'],s['t1'],places=6)
                self.assertAlmostEqual(s['motion']['end_speed'],nxt['motion']['start_speed'])
        self.assertGreater(count,100)
        for e in r['events']:
            if e['kind']=='coordinated_zone_release' and e['end_speed']>0:self.assertTrue(e['braking_zone_reserved'])
    @unittest.skipUnless(os.environ.get('GREENFIELD_SCENE_REPORT') and os.environ.get('GREENFIELD_SCENE_GEOMETRY'),'Needs report and exported scene geometry')
    def test_actual_material_and_reserve_paths_clear_exported_static_scene(self):
        r=json.loads(Path(os.environ['GREENFIELD_SCENE_REPORT']).read_text());scene=json.loads(Path(os.environ['GREENFIELD_SCENE_GEOMETRY']).read_text())
        result=audit_scene(r,scene);self.assertTrue(result['passed'],result['examples'])
        audit(r)

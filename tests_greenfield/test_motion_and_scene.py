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
    @unittest.skipUnless(os.environ.get('GREENFIELD_SCENE_REPORT'),'Needs exported scene geometry')
    def test_actual_material_and_reserve_paths_clear_exported_static_scene(self):
        r=json.loads(Path(os.environ['GREENFIELD_SCENE_REPORT']).read_text());scene=json.loads(Path(os.environ['GREENFIELD_SCENE_GEOMETRY']).read_text())
        result=audit_scene(r,scene);self.assertTrue(result['passed'],result['examples'])
        audit(r)

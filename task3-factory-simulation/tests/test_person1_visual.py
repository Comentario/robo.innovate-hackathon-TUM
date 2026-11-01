"""Verify review decisions against the actual intake and planner, not a browser approximation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from demo.person1_visual import build_data,render
from integration import prepare
from integration.person1_intake import convert_inventory

ROOT=Path(__file__).resolve().parents[1]


class Person1VisualTests(unittest.TestCase):
    def setUp(self):
        fixture=ROOT/'examples/person1'
        self.inventory=json.loads((fixture/'inventory_with_color.json').read_text())
        self.config=json.loads((fixture/'config.json').read_text())
        self.image=(fixture/'bricks_70.png').read_bytes()

    def test_every_displayed_plan_matches_real_planner_and_preserves_partition(self):
        before=deepcopy(self.inventory)
        data=build_data(self.inventory,self.config,self.image)
        ids={b['id'] for b in self.inventory['bricks']}
        for case in data['scenarios']:
            accepted=set(case['accepted_ids']);excluded={b['id'] for b in case['excluded']}
            self.assertEqual(accepted|excluded,ids)
            self.assertFalse(accepted&excluded)
            if case['plan']:
                snapshot,audit=convert_inventory(self.inventory,min_score=case['threshold'])
                _,expected,_=prepare(snapshot,self.config)
                self.assertEqual(case['plan'],expected)
                planned=[p['brick_id'] for p in case['plan']['placements']]
                self.assertEqual(len(set(planned)),12)
                self.assertTrue(set(planned)<=accepted)
                self.assertIsNone(case['error'])
            else:self.assertIsInstance(case['error'],str)
        self.assertEqual(self.inventory,before)
        default=next(s for s in data['scenarios'] if s['threshold']==.5)
        self.assertEqual((len(default['accepted_ids']),len(default['excluded'])),(57,13))
        for threshold in (.75,.9,.95):
            self.assertIsNone(next(s for s in data['scenarios'] if s['threshold']==threshold)['plan'])

    def test_mismatched_or_non_png_source_is_refused(self):
        value=deepcopy(self.inventory);value['image_size_px']['width']+=1
        with self.assertRaisesRegex(ValueError,'dimensions'):build_data(value,self.config,self.image)
        with self.assertRaisesRegex(ValueError,'PNG'):build_data(self.inventory,self.config,b'not a PNG')

    def test_bundle_is_offline_and_escapes_producer_text(self):
        value=deepcopy(self.inventory);value['bricks'][0]['id']='</script><img src=x onerror=alert(1)>'
        data=build_data(value,self.config,self.image)
        page=render(data,self.image)
        payload=page.split('<script id="review-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload),data)
        self.assertNotIn('</script>',payload)
        self.assertIn('data:image/png;base64,',page)
        self.assertNotIn('<script src=',page)
        self.assertNotIn('fetch(',page)
        self.assertNotIn('/*INLINE_',page)

    def test_cli_creates_bundle_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'review'
            command=[sys.executable,'-m','demo.person1_visual','--output-dir',str(output)]
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((output/'index.html').exists())
            self.assertTrue((output/'review.json').exists())
            before=(output/'index.html').read_bytes()
            again=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(again.returncode,2)
            self.assertEqual((output/'index.html').read_bytes(),before)


if __name__=='__main__':unittest.main()

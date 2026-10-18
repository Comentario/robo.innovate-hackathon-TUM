import json
from pathlib import Path
import unittest

from demo.browser import build_data, render_page

ROOT = Path(__file__).resolve().parents[1]


class BrowserDemoTests(unittest.TestCase):
    def test_browser_data_uses_verified_plans_and_failure_confirmations(self):
        data = build_data(ROOT)
        self.assertEqual(len(data['scenarios']), 5)
        for scenario in data['scenarios']:
            for pair in scenario['results'].values():
                normal, failure = pair['normal'], pair['failure']
                if normal['status'] == 'rejected':
                    self.assertEqual(normal['events'], [])
                    self.assertEqual(failure['status'], 'rejected')
                    continue
                self.assertEqual(normal['status'], 'completed')
                self.assertEqual(len(normal['confirmed_placements']), 12)
                self.assertEqual(failure['status'], 'stopped')
                self.assertEqual(len(failure['confirmed_placements']), 4)
                self.assertEqual(normal['plan'], failure['plan'])
        faces = data['scenarios'][3]['results']['mixed/reject']['normal']
        self.assertEqual(faces['plan']['blend'], dict(dark=4, medium=4, light=4))
        locked = data['scenarios'][4]['results']['mixed/reject']['normal']
        self.assertEqual(locked['status'], 'rejected')

    def test_local_bundle_escapes_json_and_has_no_external_asset_dependencies(self):
        payload = dict(scenarios=[dict(name='</script><img src=x>')])
        page = render_page(payload, ROOT/'demo/web')
        self.assertNotIn('</script><img', page)
        self.assertIn('\\u003c/script>', page)
        self.assertNotIn('__DEMO_DATA__', page)
        self.assertNotIn('/*INLINE_', page)
        self.assertNotIn('<script src=', page)
        self.assertNotIn('<link ', page)
        self.assertIn('<html lang="en">', page)

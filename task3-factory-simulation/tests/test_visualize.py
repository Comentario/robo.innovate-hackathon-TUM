import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from planning.visualize import compare_scenarios, main, render_svg

ROOT = Path(__file__).resolve().parents[1]


class VisualComparisonTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / 'data/scenarios.json').read_text())

    def test_scenarios_policies_and_same_inventory(self):
        original = copy.deepcopy(self.spec)
        report = compare_scenarios(self.spec)
        self.assertEqual(original, self.spec)
        self.assertEqual(report, compare_scenarios(self.spec))
        self.assertEqual(len(report['scenarios']), 3)
        for index, scenario in enumerate(report['scenarios']):
            results = scenario['results']
            self.assertEqual(len(results), 4)
            self.assertEqual([r['status'] for r in results[:2]],
                             ['planned'] * 2 if index == 0 else ['rejected'] * 2)
            for r in results[2:]:
                self.assertEqual(r['status'], 'planned')
                ids = [p['brick_id'] for p in r['plan']['placements']]
                self.assertEqual(len(set(ids)), 12)
                for group, count in r['plan']['blend'].items():
                    self.assertLessEqual(count, scenario['stock'].get(group, 0))
            self.assertEqual(results[2]['plan']['blend'], results[3]['plan']['blend'])
            if index:
                self.assertGreater(results[2]['plan']['metrics']['ratio_l1_error'], 0)
        # Compare tone metrics against the planner's own metric in smooth mode.
        for scenario in report['scenarios']:
            result = scenario['results'][3]
            self.assertAlmostEqual(result['comparison_metrics']['mean_neighbor_tone_distance'],
                                   result['plan']['metrics']['mean_neighbor_tone_distance'])

    def test_svg_has_all_planned_bricks_and_escapes_labels(self):
        self.spec['scenarios'][0]['name'] = '<script>&"'
        report = compare_scenarios(self.spec)
        svg = render_svg(report)
        root = ET.fromstring(svg)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        bricks = root.findall('.//s:g[@class="brick"]', ns)
        expected = sum(len(r['plan']['placements']) for s in report['scenarios']
                       for r in s['results'] if r['status'] == 'planned')
        self.assertEqual(len(bricks), expected)
        self.assertIn('&lt;script&gt;&amp;', svg)
        self.assertEqual(len(root.findall('.//s:script', ns)), 0)
        self.assertIn('REJECTED', svg)

    def test_invalid_scenarios_fail_before_rendering(self):
        for change in (dict(target_ratios={'dark': 0}), dict(shape={'rows': 0}),
                       dict(tone_values={'dark': float('nan')}), dict(scenarios=[])):
            spec = dict(self.spec, **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare_scenarios(spec)

    def test_cli_writes_portable_svg_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'comparison.svg'
            with patch('sys.argv', ['visualize', '--scenarios', str(ROOT / 'data/scenarios.json'),
                                    '--output', str(output)]):
                self.assertEqual(main(), 0)
            ET.parse(output)
            self.assertEqual(len(json.loads(output.with_suffix('.json').read_text())['scenarios']), 3)

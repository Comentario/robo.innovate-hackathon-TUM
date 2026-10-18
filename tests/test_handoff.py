"""Consumer-facing checks for the documented handoff over the JSON CLI."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/handoff'


class HandoffTests(unittest.TestCase):
    def run_planner(self, inventory):
        return subprocess.run([sys.executable, '-m', 'planning', str(inventory),
                               '--config', str(EXAMPLE / 'config.json')], cwd=ROOT,
                              capture_output=True, text=True)

    def test_json_can_be_consumed_against_source_inventory(self):
        result = self.run_planner(EXAMPLE / 'inventory.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = {b['id']: b for b in json.loads((EXAMPLE / 'inventory.json').read_text())}
        # Validate both the live CLI and the checked-in example as a consumer would.
        plans = [json.loads(result.stdout), json.loads((EXAMPLE / 'plan.json').read_text())]
        for plan in plans:
            with self.subTest(source='live' if plan is plans[0] else 'reference'):
                self.assertEqual(plan['schema_version'], '0.2')
                self.assertEqual(plan['policy']['shortage_policy'], 'reject')
                positions = plan['placements']
                self.assertEqual(len(positions), 12)
                self.assertEqual(len({p['brick_id'] for p in positions}), 12)
                self.assertEqual([p['step'] for p in positions], list(range(1,13)))
                self.assertEqual([(p['layer'],p['row'],p['column']) for p in positions],
                                 [(l,r,c) for l in range(2) for r in range(2) for c in range(3)])
                for p in positions:
                    self.assertIn(p['brick_id'], source)
                    self.assertEqual(p['color_group'], source[p['brick_id']]['color_group'])
                self.assertEqual(Counter(p['color_group'] for p in positions),
                                 dict(dark=4, medium=4, light=4))

    def test_missing_brick_produces_no_executable_plan(self):
        inventory = json.loads((EXAMPLE / 'inventory.json').read_text())[:-1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.json'
            path.write_text(json.dumps(inventory))
            result = self.run_planner(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('insufficient eligible inventory', result.stderr)

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from demo import run_demo, simulate_plan
from planning import make_plan

ROOT = Path(__file__).resolve().parents[1]


class IntegrationDemoTests(unittest.TestCase):
    def setUp(self):
        self.inventory = json.loads((ROOT / 'examples/handoff/inventory.json').read_text())
        self.config = json.loads((ROOT / 'examples/handoff/config.json').read_text())

    def test_complete_run_confirms_every_brick_without_mutating_inputs(self):
        original = deepcopy(self.inventory)
        report = run_demo(self.inventory, self.config)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(len(report['confirmed_placements']), 12)
        self.assertEqual(report['remaining_inventory'], [])
        self.assertEqual(original, self.inventory)

    def test_failure_stops_before_pick_and_preserves_unconfirmed_stock(self):
        report = run_demo(self.inventory, self.config, fail_step=5)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual([p['step'] for p in report['confirmed_placements']], [1,2,3,4])
        consumed = {p['brick_id'] for p in report['confirmed_placements']}
        self.assertEqual({b['id'] for b in report['remaining_inventory']},
                         {b['id'] for b in self.inventory} - consumed)
        failures = [e for e in report['events'] if e['event'] == 'placement_failed']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['step'], 5)
        self.assertEqual(len(report['events'][-1]['brick_ids']), 8)
        self.assertFalse(report['resume_supported'])

    def test_short_inventory_emits_no_execution_events(self):
        report = run_demo(self.inventory[:-1], self.config)
        self.assertEqual(report['status'], 'rejected')
        self.assertEqual(report['events'], [])
        self.assertEqual(report['confirmed_placements'], [])

    def test_consumer_rejects_tampered_plans_before_execution(self):
        base = make_plan(self.inventory, **self.config)
        for corruption in ('duplicate', 'category', 'coordinate', 'step', 'blend', 'schema'):
            plan = deepcopy(base)
            if corruption == 'duplicate':
                plan['placements'][1]['brick_id'] = plan['placements'][0]['brick_id']
            elif corruption == 'category':
                plan['placements'][0]['color_group'] = 'unknown'
            elif corruption == 'coordinate':
                plan['placements'][0]['layer'] = 1
            elif corruption == 'step':
                plan['placements'][0]['step'] = 4
            elif corruption == 'blend':
                plan['blend']['dark'] = 100
            else:
                plan['schema_version'] = 'unknown'
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                simulate_plan(plan, self.inventory)

    def test_cli_success_and_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            for failure, code, expected in ((None, 0, 12), (1, 3, 0), (5, 3, 4), (12, 3, 11)):
                output = Path(directory) / 'report.json'
                args = [sys.executable, '-m', 'demo', '--output', str(output)]
                if failure is not None:
                    args += ['--fail-step', str(failure)]
                result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                report = json.loads(output.read_text())
                self.assertEqual(len(report['confirmed_placements']), expected)
                self.assertIn('SIMULATION ONLY', result.stdout)

    def test_invalid_failure_step_rejected(self):
        for step in (0, 13, True):
            with self.subTest(step=step), self.assertRaises(ValueError):
                run_demo(self.inventory, self.config, fail_step=step)

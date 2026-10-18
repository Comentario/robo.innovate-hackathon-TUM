import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_config_modes_and_override(self):
        for mode in ('mixed', 'smooth'):
            result = subprocess.run([sys.executable, '-m', 'planning', 'data/inventory.json',
                                     '--config', f'config/{mode}.json', '--layers', '1'],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan['policy']['mode'], mode)
            self.assertEqual(len(plan['placements']), 6)

    def test_invalid_cli_is_actionable(self):
        result = subprocess.run([sys.executable, '-m', 'planning', 'data/inventory.json',
                                 '--rows', '0', '--columns', '3'], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('positive integers', result.stderr)

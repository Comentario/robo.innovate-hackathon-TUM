"""Pin saved observations and supervise the CPU-only comparison."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Saved-data batch evaluation requires default Pueue')
    started = time.monotonic()
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Source review required')
    complete = False
    code = None
    try:
        for path, digest in protocol['input_sha256'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Pinned saved observation changed: '+path)
        code = subprocess.run([sys.executable, str(HERE/'evaluate.py'), '--inputs', str(HERE/'protocol.json'),
            '--output', str(ROOT/'output')], timeout=10., check=False).returncode
        report = json.loads((ROOT/'output/evaluation.json').read_text())
        complete = code == 0 and report.get('evaluation_complete') is True
        if not complete:
            raise RuntimeError('Comparison incomplete; preserve UNKNOWN')
    finally:
        elapsed = time.monotonic()-started
        prior = protocol['prior_case_seconds']
        path = ROOT/'output/evaluation.json'
        record = {'mode': 'saved_contact_screen_comparison', 'evaluation_complete': complete,
            'evaluation_returncode': code, 'actual_seconds': elapsed,
            'prior_case_wall_seconds': prior, 'cumulative_case_seconds': prior+elapsed,
            'case_limit_seconds': 1800, 'within_budget': elapsed <= 15 and prior+elapsed <= 1800,
            'physics_steps': 0, 'proceed_gate_passed': False, 'grasp_retry_authorized': False,
            'policy_installed': False, 'automatic_retry': False,
            'audit_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main()

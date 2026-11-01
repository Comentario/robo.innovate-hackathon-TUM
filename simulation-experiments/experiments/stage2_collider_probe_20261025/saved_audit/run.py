"""Verify fixed saved inputs and emit the repaired failure audit; no simulation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Default Pueue required')
    started = time.monotonic()
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Saved-audit source review required')
    for path, digest in protocol['input_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Saved capture changed: '+path)
    clock = Path(protocol['prior_supervisor'])
    if hashlib.sha256(clock.read_bytes()).hexdigest() != protocol['prior_supervisor_sha256']:
        raise RuntimeError('Prior cost changed')
    code = subprocess.run([sys.executable, str(HERE.parent/'evaluate.py'),
        '--input', str(Path(protocol['source_snapshot'])/'output'), '--output', str(ROOT/'audit')],
        timeout=6., check=False).returncode
    elapsed = time.monotonic()-started
    report_path = ROOT/'audit/evaluation.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    record = {'audit_returncode': code, 'audit_completed': bool(report),
        'expected_result': 'UNKNOWN', 'capture_reinterpreted_as_success': report.get('proceed_gate_passed') is True,
        'physics_steps': 0, 'actual_seconds': elapsed, 'prior_case_wall_seconds': protocol['prior_case_seconds'],
        'cumulative_case_seconds': protocol['prior_case_seconds']+elapsed, 'case_limit_seconds': 1800,
        'proceed_gate_passed': False, 'grasp_retry_authorized': False,
        'within_budget': elapsed <= 10 and protocol['prior_case_seconds']+elapsed <= 1800}
    (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record, indent=2)+'\n')
    if code or not report or report.get('status') != 'UNKNOWN' or report.get('proceed_gate_passed') is not False:
        raise RuntimeError('Missing failure audit or unexpected result; no promotion')


if __name__ == '__main__':
    main()

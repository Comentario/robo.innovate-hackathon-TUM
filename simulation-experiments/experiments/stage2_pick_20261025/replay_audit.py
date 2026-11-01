"""One independently reviewed scoring correction; never launch simulation."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--prior-supervisor', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Audit replay must use default Pueue')
    protocol = json.loads((HERE/'protocol.json').read_text())
    prior_record = json.loads(args.prior_supervisor.read_text())
    prior = float(prior_record['cumulative_case_seconds'])
    limit = protocol['budget']['capture_plus_independent_audit_seconds_per_case']
    if not math.isfinite(prior) or not 0 < prior < limit:
        raise RuntimeError('Invalid original failed-invocation time charge')
    if (prior_record['case'] != 'I' or prior_record['mode'] != 'control'
            or prior_record['proceed_gate_passed'] is not False):
        raise RuntimeError('Only the original failed I-control audit may be corrected')
    audit = ROOT/'audit'
    audit.mkdir(exist_ok=False)
    command = [sys.executable, str(HERE/'evaluation/evaluate.py'), '--case', 'I',
               '--mode', 'control', '--input', str(args.input), '--output', str(audit),
               '--replay-prior-supervisor', str(args.prior_supervisor)]
    started = time.monotonic()
    child = None
    accepted = False

    def cancelled(number, _frame):
        if child is not None:
            finish_child(child)
        raise SystemExit(128+number)

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        with (audit/'process.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            try:
                code = child.wait(timeout=limit-prior-7.)
            except subprocess.TimeoutExpired:
                finish_child(child)
                raise TimeoutError('Corrected audit exhausted remaining case budget')
        result = json.loads((audit/'evaluation.json').read_text())
        if code or result.get('proceed_gate_passed') is not True:
            raise RuntimeError('Corrected independent control audit failed')
        accepted = True
    finally:
        elapsed = time.monotonic()-started
        record = {'case': 'I', 'mode': 'control', 'execution_kind': 'audit_only_correction',
                  'input_capture': str(args.input.resolve()), 'new_simulation_steps': 0,
                  'original_failed_pipeline_sha256': sha(args.prior_supervisor),
                  'original_capture_wall_seconds': prior_record['phases'][0]['capture_wall_seconds'],
                  'prior_case_wall_seconds': prior,
                  'actual_capture_plus_audit_seconds': elapsed,
                  'cumulative_case_seconds': prior+elapsed, 'case_limit_seconds': limit,
                  'within_budget': prior+elapsed <= limit,
                  'proceed_gate_passed': accepted and prior+elapsed <= limit,
                  'audit_sha256': sha(audit/'evaluation.json') if (audit/'evaluation.json').exists() else None,
                  'automatic_retry': False}
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record, indent=2)+'\n')
    if prior+elapsed > limit:
        raise RuntimeError('Cumulative case budget exceeded')


if __name__ == '__main__':
    main()

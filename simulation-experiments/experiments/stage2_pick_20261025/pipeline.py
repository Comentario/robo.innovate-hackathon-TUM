"""One queued capture and independent audit within the frozen case budget."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--case', choices=('I', 'H'), required=True)
    parser.add_argument('--mode', choices=('control', 'pick'), required=True)
    parser.add_argument('--predecessor-control', type=Path)
    parser.add_argument('--predecessor-development', type=Path)
    parser.add_argument('--prior-case-supervisor', type=Path)
    parser.add_argument('--prior-wall-seconds', type=float, default=0.)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Use the default Pueue queue')
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Frozen source review has not authorized execution')
    case_limit = protocol['budget']['capture_plus_independent_audit_seconds_per_case']
    prior = args.prior_wall_seconds
    if not math.isfinite(prior) or not 0 <= prior < case_limit:
        raise RuntimeError('Invalid recorded prior case runtime')
    limit = case_limit-prior
    if args.mode == 'pick' and args.predecessor_control is None:
        raise RuntimeError('Pick requires a passing matched stationary control')
    if args.case == 'H' and args.predecessor_development is None:
        raise RuntimeError('Reserved case requires independent development success')

    output, audit = ROOT/'output', ROOT/'audit'
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    child = None
    records = []
    accepted = False

    def terminate():
        if child is not None and child.poll() is None:
            finish_child(child)

    def cancelled(number, _frame):
        terminate()
        raise SystemExit(128+number)

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        final = ROOT/'experiments/final_workcell_20261024'
        command = [sys.executable, str(HERE/'run_pick.py'), '--case', args.case,
                   '--mode', args.mode, '--output', str(output),
                   '--geometry', str(final/'geometry.json'),
                   '--cameras', str(ROOT/'experiments/stage1_20261025/source_views_v1.json'),
                   '--appearance', str(final/'appearance_config.json'),
                   '--headless', '--enable_cameras', '--device', 'cpu']
        capture_started = time.monotonic()
        reason = 'returned'
        # Leave time for the independent audit and bounded child cleanup.
        capture_cutoff = limit-67.
        if capture_cutoff <= 0:
            raise TimeoutError('Insufficient remaining case budget for capture and audit')
        with (output/'process.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            try:
                while child.poll() is None:
                    if (output/'failure.json').exists():
                        reason = 'capture_failure'
                        break
                    if (output/'capture_complete.json').exists():
                        reason = 'capture_marker_cleanup'
                        break
                    if time.monotonic()-started >= capture_cutoff:
                        reason = 'capture_budget_exhausted'
                        break
                    time.sleep(.1)
            finally:
                returncode = finish_child(child)
        capture_wall = time.monotonic()-capture_started
        complete = ((output/'capture_complete.json').exists()
                    and not (output/'failure.json').exists())
        supervisor = {'case': args.case, 'mode': args.mode,
                      'capture_completed': complete, 'capture_wall_seconds': capture_wall,
                      'child_returncode': returncode, 'cleanup_result': reason,
                      'prior_case_wall_seconds': prior, 'case_limit_seconds': case_limit,
                      'independent_audit_required': True}
        (output/'supervisor.json').write_text(json.dumps(supervisor, indent=2)+'\n')
        records.append({'phase': 'capture', **supervisor})

        command = [sys.executable, str(HERE/'evaluation/evaluate.py'),
                   '--case', args.case, '--mode', args.mode,
                   '--input', str(output), '--output', str(audit)]
        for flag in ('predecessor_control', 'predecessor_development', 'prior_case_supervisor'):
            value = getattr(args, flag)
            if value is not None:
                command += ['--'+flag.replace('_', '-'), str(value)]
        remaining = limit-(time.monotonic()-started)-7.
        if remaining <= 0:
            raise TimeoutError('Case budget exhausted before independent audit')
        before = time.monotonic()
        child = subprocess.Popen(command, start_new_session=True)
        try:
            audit_code = child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            terminate()
            raise TimeoutError('Independent audit exceeded remaining case budget')
        finally:
            records.append({'phase': 'audit', 'wall_seconds': time.monotonic()-before})
        verdict = json.loads((audit/'evaluation.json').read_text())
        if not complete or audit_code or not verdict.get('proceed_gate_passed', False):
            raise RuntimeError('Independent phase gate failed; retain evidence and stop')
        accepted = True
    finally:
        elapsed = time.monotonic()-started
        record = {'case': args.case, 'mode': args.mode, 'phases': records,
                  'actual_capture_plus_audit_seconds': elapsed,
                  'prior_case_wall_seconds': prior,
                  'cumulative_case_seconds': prior+elapsed,
                  'case_limit_seconds': case_limit,
                  'within_budget': prior+elapsed <= case_limit,
                  'proceed_gate_passed': accepted and prior+elapsed <= case_limit,
                  'audit_sha256': hashlib.sha256((audit/'evaluation.json').read_bytes()).hexdigest()
                      if (audit/'evaluation.json').exists() else None,
                  'automatic_retry': False}
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record, indent=2)+'\n')
    if prior+elapsed > case_limit:
        raise RuntimeError('Cumulative case budget exceeded')


if __name__ == '__main__':
    main()

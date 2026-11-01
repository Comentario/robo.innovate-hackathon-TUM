"""One shared <=30s saved-data diagnostic, with no simulation or inference."""
import argparse
import json
import os
from pathlib import Path
import signal
import time

STARTED = time.monotonic()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prior-supervisor', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Use default Pueue for all saved-array processing')
    args.output.mkdir(parents=True, exist_ok=False)
    prior_record = json.loads(args.prior_supervisor.read_text())
    prior = float(prior_record['cumulative_case_seconds'])
    result = {'scope': 'One fixed first-candidate clearance replay and cache equivalence check',
              'case': 'I', 'mode': 'diagnostic', 'new_physics_steps': 0,
              'prior_case_wall_seconds': prior, 'case_limit_seconds': 1200,
              'diagnostic_limit_seconds': 30, 'automatic_retry': False,
              'proceed_gate_passed': False}

    def expired(*_):
        raise TimeoutError('Shared30s diagnostic deadline exhausted')

    signal.signal(signal.SIGALRM, expired)
    signal.signal(signal.SIGTERM, expired)
    # Keep a small allowance for saving the partial result and process exit.
    deadline = STARTED+28.
    signal.setitimer(signal.ITIMER_REAL, max(.001, deadline-time.monotonic()))
    try:
        from cache_compare import run as compare_cache
        from clearance_replay import run as replay_clearance
        cache = compare_cache(args.output, deadline)
        result['cache_equivalence_passed'] = cache.get('equivalence_passed', False)
        clearance = replay_clearance(args.input, args.output, deadline)
        result['clearance_replay_completed'] = clearance.get('completed', False)
        result['completed'] = result['cache_equivalence_passed'] and result['clearance_replay_completed']
    except Exception as error:
        result.update(completed=False, error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        elapsed = time.monotonic()-STARTED
        result.update(actual_capture_plus_audit_seconds=elapsed,
                      cumulative_case_seconds=prior+elapsed,
                      within_diagnostic_budget=elapsed <= 30,
                      within_budget=prior+elapsed <= 1200)
        text = json.dumps(result, indent=2, allow_nan=False)+'\n'
        (args.output/'diagnostic_summary.json').write_text(text)
        (args.output.parent/'pipeline_supervisor.json').write_text(text)
    if not result.get('completed') or not result['within_diagnostic_budget'] or not result['within_budget']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

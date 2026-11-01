"""Bound the one diagnostic child, including known native shutdown stalls."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Default Pueue is mandatory')
    here = Path(__file__).resolve().parent
    protocol = json.loads((here/'protocol.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy(); env['OSQP_EPSILON'] = '1e-4'
    command = [args.python, str(here/'run_fixture.py'), '--output', str(args.output), '--headless', '--device', 'cpu']
    with (args.output/'process.log').open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        def cancelled(number, _frame):
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            raise SystemExit(128+number)
        signal.signal(signal.SIGTERM, cancelled); signal.signal(signal.SIGINT, cancelled)
        start, marker_time, reason = time.monotonic(), None, None
        try:
            while child.poll() is None:
                if (args.output/'failure.json').exists(): reason = 'setup_or_capture_failure'; break
                if (args.output/'diagnostic_complete.json').exists():
                    if marker_time is None: marker_time = time.monotonic()
                    if time.monotonic()-marker_time > protocol['cleanup_grace_s']:
                        reason = 'shutdown_stall_after_observation'; break
                if time.monotonic()-start > protocol['wall_limit_s']:
                    reason = 'timeout'; break
                time.sleep(.2)
        finally:
            code = finish_child(child)
    complete = (args.output/'diagnostic_complete.json').exists() and reason not in ('timeout','setup_or_capture_failure')
    if complete:
        report = json.loads((args.output/'diagnostic_report.json').read_text())
        complete = report['diagnostic_completed'] and 0 <= report['steps_executed'] <= protocol['maximum_steps'] == 8
    (args.output/'supervisor.json').write_text(json.dumps({'diagnostic_completed':bool(complete),
        'idle_validated':False,'full300_validated':False,'child_returncode':code,
        'cleanup_result':reason or 'returned','wall_seconds':time.monotonic()-start},indent=2)+'\n')
    if not complete: raise RuntimeError('Diagnostic incomplete; preserve failure and process log')


if __name__ == '__main__': main()

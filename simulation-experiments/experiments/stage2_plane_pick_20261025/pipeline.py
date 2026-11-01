"""One bounded I capture and independent native extraction audit."""
import hashlib
import json
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
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Default Pueue required')
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Source review required')
    output = ROOT/'output'
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    child = None
    records = []
    accepted = False

    def cancel(number, _frame):
        if child is not None and child.poll() is None:
            finish_child(child)
        raise SystemExit(128+number)

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        final = ROOT/'experiments/final_workcell_20261024'
        command = [sys.executable, str(HERE/'run_pick.py'), '--case', 'I', '--mode', 'pick',
            '--output', str(output), '--geometry', str(final/'geometry.json'),
            '--cameras', str(ROOT/'experiments/stage1_20261025/source_views_v1.json'),
            '--appearance', str(final/'appearance_config.json'), '--headless', '--enable_cameras', '--device', 'cpu']
        before = time.monotonic()
        reason = 'returned'
        with (output/'process.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while child.poll() is None:
                    if (output/'plane_pick_complete.json').exists():
                        reason = 'complete_marker_cleanup'
                        break
                    if (output/'failure.json').exists():
                        reason = 'capture_failure'
                        break
                    if time.monotonic()-started >= protocol['capture_cutoff_seconds']:
                        reason = 'capture_budget_exhausted'
                        break
                    time.sleep(.1)
            finally:
                code = finish_child(child)
        records.append({'phase': 'capture', 'wall_seconds': time.monotonic()-before,
                        'returncode': code, 'cleanup': reason})
        complete = (output/'plane_pick_complete.json').exists() and not (output/'failure.json').exists()
        remaining = min(protocol['audit_limit_seconds'], 340.-(time.monotonic()-started))
        if remaining <= 0:
            raise TimeoutError('No independent audit time remains')
        (output/'supervisor.json').write_text(json.dumps({
            'capture_completed': complete, 'capture_wall_seconds': records[-1]['wall_seconds'],
            'child_returncode': records[-1]['returncode'], 'cleanup': reason,
            'prior_case_seconds': protocol['prior_case_seconds'],
            'remaining_audit_seconds': remaining, 'elapsed_before_audit_seconds': time.monotonic()-started,
            'maximum_active_seconds': protocol['maximum_active_seconds'],
            'aggregate_case_ceiling_seconds': protocol['aggregate_case_ceiling_seconds']
        }, indent=2)+'\n')
        before = time.monotonic()
        child = subprocess.Popen([sys.executable, str(HERE/'evaluate.py'), '--input', str(output),
            '--output', str(ROOT/'audit')], start_new_session=True)
        try:
            code = child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            finish_child(child)
            raise TimeoutError('Independent audit timeout; no retry')
        records.append({'phase': 'audit', 'wall_seconds': time.monotonic()-before, 'returncode': code})
        report = json.loads((ROOT/'audit/evaluation.json').read_text())
        accepted = complete and code == 0 and report.get('physics_extraction_passed') is True
        if not accepted:
            raise RuntimeError('I native extraction baseline failed; preserve evidence and stop')
    finally:
        elapsed = time.monotonic()-started
        path = ROOT/'audit/evaluation.json'
        prior = protocol['prior_case_seconds']
        record = {'mode': 'unverified_plane_position_pick_I', 'phases': records,
            'actual_capture_plus_audit_seconds': elapsed, 'prior_case_wall_seconds': prior,
            'cumulative_case_seconds': prior+elapsed, 'case_limit_seconds': 2200,
            'previous_case_limit_seconds': 1800, 'within_budget': elapsed <= 360 and prior+elapsed <= 2200,
            'physics_extraction_passed': accepted, 'transfer_authorized': False,
            'online_held_identity': 'UNKNOWN', 'automatic_retry': False, 'H_authorized': False,
            'audit_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main()

"""Bounded foreground idle child; cleanup timeout is separate from test success."""
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


def main(diagnostic=False, velocity16=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', required=True)
    parser.add_argument('--osqp-epsilon', choices=('1e-4','1e-6'), help='Coupled native numerical setting; diagnostic only')
    parser.add_argument('--contact-observer', action='store_true', help='Public raw contact observation; diagnostic only')
    args = parser.parse_args()
    if args.osqp_epsilon and not (diagnostic or velocity16):
        parser.error('Numerical epsilon variants are restricted to diagnostics')
    if velocity16 and (diagnostic or args.osqp_epsilon != '1e-4' or args.contact_observer):
        parser.error('Velocity16 round requires explicit baseline epsilon1e-4 and no contact observer')
    if args.contact_observer and (not diagnostic or args.osqp_epsilon != '1e-4'):
        parser.error('Contact observation requires diagnostic and explicit baseline epsilon1e-4')
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Idle smoke requires default Pueue')
    directory = Path(__file__).resolve().parent
    final = ROOT/'experiments/final_workcell_20261024'
    args.output.mkdir(parents=True, exist_ok=True)
    command = [args.python, str(directory/('run_velocity16.py' if velocity16 else 'diagnose_breakage.py' if diagnostic else 'run_idle.py')), '--geometry', str(final/'geometry.json'),
        '--cameras', str(final/'cameras_realism.json'), '--appearance', str(final/'appearance_config.json'),
        '--output', str(args.output), '--views', 'all', '--headless', '--enable_cameras', '--device', 'cpu']
    child_env = os.environ.copy()
    if args.osqp_epsilon is not None:
        child_env['OSQP_EPSILON'] = args.osqp_epsilon
    child_env['ROBO_CONTACT_OBSERVER'] = '1' if args.contact_observer else '0'
    (args.output/'numerical_environment.json').write_text(json.dumps({
        'OSQP_EPSILON_present': 'OSQP_EPSILON' in child_env,
        'OSQP_EPSILON_raw': child_env.get('OSQP_EPSILON'),
        'requested': args.osqp_epsilon,
        'scope': 'Couples solver eps_abs/eps_rel, G lower bound and stage2 capacity interior margin; no physical-threshold or break-selection change'},indent=2)+'\n')
    with (args.output/'process.log').open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=child_env)
        def cancelled(signum, _frame):
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            raise SystemExit(128+signum)
        signal.signal(signal.SIGTERM, cancelled)
        signal.signal(signal.SIGINT, cancelled)
        start, marker_time, reason = time.monotonic(), None, None
        try:
            while child.poll() is None:
                if (args.output/'failure.json').exists():
                    reason = 'idle_failure'; break
                if (args.output/('velocity16_complete.json' if velocity16 else 'diagnostic_complete.json' if diagnostic else 'idle_complete.json')).exists():
                    if marker_time is None: marker_time = time.monotonic()
                    if time.monotonic()-marker_time > 5:
                        reason = 'cleanup_stall_after_diagnostic' if diagnostic else 'cleanup_stall_after_validated_idle'; break
                if time.monotonic()-start > 180:
                    reason = 'idle_timeout'; break
                time.sleep(.2)
        finally:
            code = finish_child(child)
    marker_name = 'velocity16_complete.json' if velocity16 else 'diagnostic_complete.json' if diagnostic else 'idle_complete.json'
    success = reason not in ('idle_failure', 'idle_timeout') and (args.output/marker_name).exists()
    if success:
        marker = json.loads((args.output/marker_name).read_text())
        report = json.loads((args.output/('diagnostic_report.json' if diagnostic else 'idle_report.json')).read_text())
        if diagnostic:
            success = marker['diagnostic_completed'] and report['diagnostic_completed'] and not marker['idle_validated']
            success &= 0 <= report['steps_executed'] <= report['maximum_steps'] == 8
        else:
            success = marker['idle_validated'] and report['idle_validated'] and not marker['capture_validated']
            success &= report['postassembly_physics_steps'] == report['protocol']['steps'] == 120
            if velocity16: success &= marker['terminal_runtime_readback_verified'] and marker['idle_candidate_only']
    result = {'idle_validated': bool(success) and not diagnostic, 'diagnostic_completed': bool(success) and diagnostic,
        'idle_candidate_only': bool(success) and velocity16,
        'capture_validated': False, 'child_returncode': code,
        'cleanup_result': reason or 'returned', 'seconds': time.monotonic()-start,
        'limitations': 'Idle smoke only; no grasping, updated-tip collision or hardware validation'}
    (args.output/'supervisor.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    if not success:
        raise RuntimeError('Idle smoke failed; preserve process.log and idle/failure reports')


if __name__ == '__main__':
    main()

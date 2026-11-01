"""One bounded PGS phase; capture completion never substitutes independent audit."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('A','B','C'),required=True)
    parser.add_argument('--python',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    protocol = json.loads((HERE/'protocol.json').read_text())
    args.output.mkdir(parents=True,exist_ok=False)
    if args.phase == 'A':
        command = [args.python,str(ROOT/'experiments/stage2_eccentric_20261025/run_fixture.py'),
            '--protocol',str(HERE/'A_fixture.json'),'--output',str(args.output),'--headless','--device','cpu']
        marker_name = 'diagnostic_complete.json'
    else:
        final = ROOT/'experiments/final_workcell_20261024'
        command = [args.python,str(HERE/'run_pgs.py'),'--phase',args.phase,
            '--geometry',str(final/'geometry.json'),'--cameras',str(final/'cameras_realism.json'),
            '--appearance',str(final/'appearance_config.json'),'--output',str(args.output),
            '--views','all','--headless','--enable_cameras','--device','cpu']
        if args.phase == 'C': command += ['--case','H_mix','--benchmark',str(ROOT/protocol['reserved_manifest'])]
        marker_name = 'pgs_idle_complete.json'
    env = os.environ.copy(); env['OSQP_EPSILON'] = '1e-4'
    # Contact-report observation belongs to the preserved diagnostic only.
    env.pop('ROBO_CONTACT_OBSERVER',None)
    with (args.output/'process.log').open('w') as log:
        child = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        def cancelled(number,_frame):
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            raise SystemExit(128+number)
        signal.signal(signal.SIGTERM,cancelled); signal.signal(signal.SIGINT,cancelled)
        start, completed_at, reason = time.monotonic(),None,None
        try:
            while child.poll() is None:
                if (args.output/'failure.json').exists(): reason='first_failure'; break
                if (args.output/marker_name).exists():
                    if completed_at is None: completed_at=time.monotonic()
                    if time.monotonic()-completed_at > 5: reason='shutdown_stall_after_capture'; break
                if time.monotonic()-start > protocol['maximum_phase_wall_seconds']: reason='timeout'; break
                time.sleep(.2)
        finally:
            code=finish_child(child)
    completed=(args.output/marker_name).exists() and reason not in ('timeout','first_failure')
    result={'phase':args.phase,'capture_completed':completed,'independent_proceed_audit_required':True,
        'proceed_gate_passed':False,'idle_candidate_only':args.phase!='A',
        'child_returncode':code,'cleanup_result':reason or 'returned','wall_seconds':time.monotonic()-start}
    (args.output/'supervisor.json').write_text(json.dumps(result,indent=2)+'\n')
    if not completed: raise RuntimeError('PGS phase failed/incomplete; preserve first failure, do not advance')


if __name__ == '__main__': main()

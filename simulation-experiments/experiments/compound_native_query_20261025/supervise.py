"""One bounded unchanged-compound active-query child; cleanup is charged to the same 180s budget."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    protocol=json.loads((HERE/'protocol.json').read_text());limit=protocol['capture_plus_independent_audit_wall_s']-protocol['prior_consumed_active_seconds']
    args.output.mkdir(parents=True,exist_ok=False);final=ROOT/'experiments/final_workcell_20261024'
    command=[args.python,str(HERE/'run_query.py'),'--output',str(args.output),
        '--candidate',str(HERE/'inputs/compound.json'),'--offline-audit',str(HERE/'inputs/offline_audit.json'),
        '--offline-manifest',str(HERE/'inputs/offline_manifest.json'),
        '--geometry',str(final/'geometry.json'),'--cameras',str(final/'cameras_realism.json'),
        '--appearance',str(final/'appearance_config.json'),'--views','all','--headless','--enable_cameras','--device','cpu']
    env=os.environ.copy();env['OSQP_EPSILON']='1e-4';env.pop('ROBO_CONTACT_OBSERVER',None)
    # Existing finish_child has <=2s SIGTERM wait + <=5s SIGKILL wait.
    # Reserve that time INSIDE the total budget, including failed captures.
    cleanup_reserve=7.;started=time.monotonic();reason=None;code=None
    with (args.output/'process.log').open('w') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        def cancelled(number,_frame):
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            raise SystemExit(128+number)
        signal.signal(signal.SIGTERM,cancelled);signal.signal(signal.SIGINT,cancelled)
        try:
            while child.poll() is None:
                if (args.output/'failure.json').exists():reason='setup_or_query_failure';break
                if (args.output/'active_query_complete.json').exists():reason='observation_marker_cleanup';break
                remaining=limit-(time.monotonic()-started)
                if remaining<=cleanup_reserve:reason='budget_exhaustion_with_cleanup_reserve';break
                time.sleep(min(.1,max(0.,remaining-cleanup_reserve)))
        finally:code=finish_child(child)
    elapsed=time.monotonic()-started
    complete=(args.output/'active_query_complete.json').exists() and not (args.output/'failure.json').exists() and elapsed<limit
    record={'observation_completed':complete,'proceed_gate_passed':False,'child_returncode':code,
        'cleanup_result':reason or 'returned','capture_wall_seconds':elapsed,
        'remaining_audit_wall_seconds':max(0.,limit-elapsed),'capture_plus_audit_limit_s':limit,
        'cleanup_reserved_inside_limit_s':cleanup_reserve,'independent_audit_required':True,
        'old_R3_G_status':'FAILED and closed; no contact eligibility'}
    (args.output/'supervisor.json').write_text(json.dumps(record,indent=2)+'\n')
    if not complete:raise RuntimeError('Active query incomplete; partial evidence preserved, no retry')


if __name__=='__main__':main()

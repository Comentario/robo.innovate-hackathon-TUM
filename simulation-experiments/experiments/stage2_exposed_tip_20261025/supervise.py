"""Foreground one frozen G/D/R capture with bounded cleanup; no retries."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['output','python','phase']:p.add_argument('--'+name,required=True)
    p.add_argument('--geometry-audit',type=Path);p.add_argument('--side-authorization',type=Path);p.add_argument('--predecessor-D',type=Path)
    a=p.parse_args();out=Path(a.output)
    if a.phase=='G':raise RuntimeError('Closed G cannot be rerun by the reassessed contact launcher')
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    out.mkdir(parents=True,exist_ok=False)
    final=ROOT/'experiments/final_workcell_20261024'
    command=[a.python,str(HERE/'run_contact.py'),'--phase',a.phase,'--output',str(out),'--geometry',str(final/'geometry.json'),'--cameras',str(final/'cameras_realism.json'),'--appearance',str(final/'appearance_config.json'),'--views','all','--headless','--enable_cameras','--device','cpu']
    for flag in ['geometry_audit','side_authorization','predecessor_D']:
        value=getattr(a,flag)
        if value is not None:command+=['--'+flag.replace('_','-'),str(value)]
    marker='exposed_G_complete.json' if a.phase=='G' else 'contact_complete.json'
    started=time.monotonic();limit=180.;reserve=7.;reason=None
    with (out/'process.log').open('w') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def cancel(number,_frame):
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            raise SystemExit(128+number)
        signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
        try:
            while child.poll() is None:
                if (out/'failure.json').exists():reason='capture_failure';break
                if (out/marker).exists():reason='completed_marker_cleanup';break
                remaining=limit-(time.monotonic()-started)
                if remaining<=reserve:reason='capture_budget_exhausted';break
                time.sleep(min(.1,max(.001,remaining-reserve)))
        finally:code=finish_child(child)
    elapsed=time.monotonic()-started
    complete=(out/marker).exists() and not (out/'failure.json').exists() and elapsed<limit
    record={'phase':a.phase,'capture_completed':complete,'observation_completed':complete,'child_returncode':code,'cleanup_result':reason or 'returned','capture_wall_seconds':elapsed,'remaining_audit_seconds':max(0.,limit-elapsed),'capture_plus_audit_limit_s':limit,'contact_validated':False,'independent_audit_required':True,'maximum_phase_attempts':1}
    (out/'supervisor.json').write_text(json.dumps(record,indent=2)+'\n')
    if not complete:raise SystemExit(1)


if __name__=='__main__':main()

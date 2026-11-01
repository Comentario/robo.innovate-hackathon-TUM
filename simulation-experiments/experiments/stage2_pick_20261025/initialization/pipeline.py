"""One diagnostic capture/audit; charge it to the retained final-round clock."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    protocol=json.loads((HERE/'protocol.json').read_text())
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or not protocol['execution_authorized']:
        raise RuntimeError('Reviewed default-queue diagnostic required')
    output,audit=ROOT/'output',ROOT/'audit';output.mkdir()
    started=time.monotonic();child=None;accepted=False;phases=[]
    prior=protocol['prior_case_seconds']

    def stop():
        if child is not None and child.poll() is None:
            finish_child(child)

    def cancelled(number,_frame):
        stop();raise SystemExit(128+number)

    signal.signal(signal.SIGTERM,cancelled);signal.signal(signal.SIGINT,cancelled)
    try:
        final=ROOT/'experiments/final_workcell_20261024'
        command=[sys.executable,str(HERE/'diagnostic.py'),'--output',str(output),
                 '--geometry',str(final/'geometry.json'),
                 '--cameras',str(ROOT/'experiments/stage1_20261025/source_views_v1.json'),
                 '--appearance',str(final/'appearance_config.json'),
                 '--headless','--enable_cameras','--device','cpu']
        begin=time.monotonic();reason='returned'
        with (output/'process.log').open('w') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while child.poll() is None:
                if (output/'failure.json').exists():reason='capture_failure';break
                if (output/'diagnostic_complete.json').exists():reason='capture_complete';break
                if time.monotonic()-started>=45:reason='capture_budget';break
                time.sleep(.1)
            code=finish_child(child)
        complete=(output/'diagnostic_complete.json').exists() and not (output/'failure.json').exists()
        record={'capture_completed':complete,'capture_wall_seconds':time.monotonic()-begin,
                'prior_case_wall_seconds':prior,'diagnostic_limit_seconds':60,
                'aggregate_case_ceiling_seconds':1800,'cleanup_result':reason,'child_returncode':code}
        (output/'supervisor.json').write_text(json.dumps(record,indent=2)+'\n');phases.append(record)
        remaining=56-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('No diagnostic audit budget remains')
        before=time.monotonic()
        child=subprocess.Popen([sys.executable,str(HERE/'evaluate.py'),'--input',str(output),'--output',str(audit)],start_new_session=True)
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            stop();raise TimeoutError('Independent diagnostic audit budget')
        phases.append({'audit_seconds':time.monotonic()-before})
        result=json.loads((audit/'evaluation.json').read_text())
        accepted=complete and result.get('proceed_gate_passed') is True
    finally:
        stop();elapsed=time.monotonic()-started
        record={'case':'I','mode':'initialization_diagnostic','phases':phases,
                'actual_capture_plus_audit_seconds':elapsed,'prior_case_wall_seconds':prior,
                'cumulative_case_seconds':prior+elapsed,'diagnostic_limit_seconds':60,
                'case_limit_seconds':1800,'within_budget':elapsed<=60 and prior+elapsed<=1800,
                'proceed_gate_passed':accepted and elapsed<=60 and prior+elapsed<=1800,
                'audit_sha256':hashlib.sha256((audit/'evaluation.json').read_bytes()).hexdigest() if (audit/'evaluation.json').exists() else None,
                'automatic_retry':False}
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record,indent=2)+'\n')
    if not record['proceed_gate_passed']:
        raise RuntimeError('Final initialization hypothesis did not pass; preserve evidence and stop')


if __name__=='__main__':main()

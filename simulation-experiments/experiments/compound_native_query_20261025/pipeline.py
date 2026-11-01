"""One native observation and independent audit inside one default-queue job."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
if os.environ.get('ROBO_PUEUE_JOB')!='1':
    raise RuntimeError('Default Pueue required')
started=time.monotonic();limit=180.;prior=float(json.loads((HERE/'protocol.json').read_text())['prior_consumed_active_seconds']);records=[]
capture=ROOT/'output';audit=ROOT/'audit'
child=None
def cancelled(number,_frame):
    if child is not None and child.poll() is None:
        try: os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        try: child.wait(timeout=2.)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5.)
    raise SystemExit(128+number)
signal.signal(signal.SIGTERM,cancelled);signal.signal(signal.SIGINT,cancelled)
try:
    before=time.monotonic()
    child=subprocess.Popen([sys.executable,str(HERE/'supervise.py'),'--python',sys.executable,'--output',str(capture)],start_new_session=True)
    try:
        code=child.wait(timeout=limit-prior-7.)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid,signal.SIGTERM)
        try: child.wait(timeout=2.)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5.)
        raise RuntimeError('Outer capture budget exhausted; no retry')
    records.append({'phase':'capture','returncode':code,'actual_process_wall_seconds':time.monotonic()-before})
    remaining=limit-prior-(time.monotonic()-started)
    if remaining<=7. or not (capture/'supervisor.json').exists():
        raise RuntimeError('No independent audit budget/capture record remains')
    inputs=HERE/'inputs'
    command=[sys.executable,str(HERE/'evaluation/evaluate.py'),'--input',str(capture),'--output',str(audit),'--capture-protocol',str(HERE/'protocol.json')]
    names={'stl':'tip.stl','config':'proxy_config.json','reference':'proxy_reference.json','compound':'compound.json','offline-audit':'offline_audit.json','baseline-metadata':'baseline_metadata.json','baseline-geometry':'baseline_geometry.json'}
    for flag,name in names.items():command.extend(['--'+flag,str(inputs/name)])
    before=time.monotonic()
    try:
        child=subprocess.Popen(command,start_new_session=True)
        try:
            audit_code=child.wait(timeout=max(.001,remaining-7.))
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGTERM)
            try: child.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5.)
            raise RuntimeError('Independent audit budget exhausted; no retry')
    finally:
        records.append({'phase':'audit','actual_process_wall_seconds':time.monotonic()-before})
    records[-1]['returncode']=audit_code
    if code or audit_code:
        raise RuntimeError('Native capture or audit incomplete; saved evidence only, no retry')
finally:
    elapsed=time.monotonic()-started
    (ROOT/'pipeline_supervisor.json').write_text(json.dumps({'phases':records,'current_process_seconds':elapsed,'prior_consumed_active_seconds':prior,'actual_cumulative_process_seconds':prior+elapsed,'limit_seconds':limit,'within_budget':prior+elapsed<=limit,'aggregate_maximum_native_executions':3,'contact_authorized':False,'physical_registration_validated':False})+'\n')
if prior+elapsed>limit:raise SystemExit(1)

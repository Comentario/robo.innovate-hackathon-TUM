"""One phase capture and independent audit inside the same180s queue budget."""
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
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--phase',choices=['G','D','R'],required=True)
p.add_argument('--geometry-audit',type=Path);p.add_argument('--side-authorization',type=Path);p.add_argument('--predecessor-D',type=Path)
a=p.parse_args()
if a.phase=='G':raise RuntimeError('G is closed as failed; reproduce only from the immutable1778 snapshot')
if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
if a.phase!='G':
    import hashlib
    if a.geometry_audit is None or a.side_authorization is None:raise RuntimeError('Missing geometry evidence/side authorization')
    original=json.loads(a.geometry_audit.read_text());permission=json.loads(a.side_authorization.read_text())
    digest=hashlib.sha256(a.geometry_audit.read_bytes()).hexdigest()
    if original.get('phase')!='G' or original.get('proceed_gate_passed') is not False:raise RuntimeError('Original global G failure must remain explicit')
    if permission.get('schema')!='exposed-tip-lateral-authorization-v1' or permission.get('authorization')!='D_then_conditional_R_lateral_only' or permission.get('global_G_passed') is not False or permission.get('geometry_audit_sha256')!=digest:raise RuntimeError('Invalid separate side-only permission')
    if a.phase=='R':
        if a.predecessor_D is None:raise RuntimeError('Missing reserved predecessor')
        d=json.loads(a.predecessor_D.read_text())
        if d.get('phase')!='D' or d.get('proceed_gate_passed') is not True:raise RuntimeError('Reserved requires independent lateral D pass')
started=time.monotonic();limit=180.;records=[];child=None

def stop_child():
    if child is not None and child.poll() is None:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=2.)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5.)

def cancelled(number,_frame):
    stop_child();raise SystemExit(128+number)
signal.signal(signal.SIGTERM,cancelled);signal.signal(signal.SIGINT,cancelled)

def execute(command,phase):
    global child
    remaining=limit-(time.monotonic()-started)
    if remaining<=7.:raise TimeoutError('No phase+cleanup time remains')
    before=time.monotonic();child=subprocess.Popen(command,start_new_session=True)
    try:code=child.wait(timeout=remaining-7.)
    except subprocess.TimeoutExpired:
        stop_child();raise TimeoutError('Phase budget exhausted; no retry')
    finally:records.append({'phase':phase,'actual_process_wall_seconds':time.monotonic()-before})
    records[-1]['returncode']=code;return code

try:
    capture=ROOT/'output';audit=ROOT/'audit';inputs=HERE/'inputs'
    command=[sys.executable,str(HERE/'supervise.py'),'--phase',a.phase,'--python',sys.executable,'--output',str(capture)]
    extra=[]
    for flag in ['geometry_audit','side_authorization','predecessor_D']:
        value=getattr(a,flag)
        if value is not None:extra+=['--'+flag.replace('_','-'),str(value)]
    capture_code=execute(command+extra,'capture')
    if not (capture/'supervisor.json').exists():raise RuntimeError('Missing capture supervisor; no invented outcome')
    command=[sys.executable,str(HERE/'evaluation/evaluate.py'),'--phase',a.phase,'--input',str(capture),'--output',str(audit),'--stl',str(inputs/'tip.stl'),'--baseline-metadata',str(inputs/'baseline_metadata.json'),'--baseline-geometry',str(inputs/'baseline_geometry.json')]
    audit_code=execute(command+extra,'audit')
    verdict=json.loads((audit/'evaluation.json').read_text()) if (audit/'evaluation.json').exists() else {}
    if capture_code or audit_code or verdict.get('proceed_gate_passed') is not True:raise RuntimeError('Independent phase gate did not pass; preserve evidence and stop')
finally:
    elapsed=time.monotonic()-started
    (ROOT/'pipeline_supervisor.json').write_text(json.dumps({'phase':a.phase,'phases':records,'actual_capture_plus_audit_seconds':elapsed,'limit_seconds':limit,'within_budget':elapsed<=limit,'maximum_phase_attempts':1,'native_grasp_or_extraction_validated':False})+'\n')
if elapsed>limit:raise SystemExit(1)

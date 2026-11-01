"""One position-only dwell pick using an exactly bridged matched control."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child

def main():
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    plan=json.loads((HERE/'protocol.json').read_text())
    if not plan['execution_authorized']:raise RuntimeError('Final source review required')
    started=time.monotonic();child=None;records=[];accepted=False
    def cancel(number,_frame):
        if child is not None and child.poll() is None:finish_child(child)
        raise SystemExit(128+number)
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    output=ROOT/'pick';output.mkdir(exist_ok=False)
    try:
        final=ROOT/'experiments/final_workcell_20261024'
        cmd=[sys.executable,str(HERE/'run_fixture.py'),'--mode','pick','--output',str(output),
            '--geometry',str(final/'geometry.json'),'--cameras',str(ROOT/'experiments/stage1_20261025/source_views_v1.json'),
            '--appearance',str(final/'appearance_config.json'),'--headless','--enable_cameras','--device','cpu',
            '--predecessor-control',plan['original_control_audit']['path'],'--control-capture',plan['original_control_capture_directory']]
        before=time.monotonic();reason='returned'
        with (output/'process.log').open('w') as log:
            child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while child.poll() is None:
                    if (output/'fixture_complete.json').exists():reason='complete_marker_cleanup';break
                    if (output/'failure.json').exists():reason='capture_failure';break
                    if time.monotonic()-started>=plan['capture_cutoff_seconds']:reason='capture_budget_exhausted';break
                    time.sleep(.1)
            finally:code=finish_child(child)
        duration=time.monotonic()-before;complete=(output/'fixture_complete.json').exists() and not (output/'failure.json').exists()
        records.append({'phase':'capture','wall_seconds':duration,'returncode':code,'cleanup':reason,'capture_completed':complete})
        remaining=min(plan['audit_limit_seconds'],138-(time.monotonic()-started))
        if remaining<=1:raise TimeoutError('No shared audit time remains')
        (output/'supervisor.json').write_text(json.dumps({'capture_completed':complete,'capture_wall_seconds':duration,'child_returncode':code,
            'remaining_audit_seconds':remaining,'prior_case_seconds':plan['prior_case_seconds'],'current_case_elapsed_seconds':time.monotonic()-started,
            'maximum_active_seconds':150,'aggregate_case_ceiling_seconds':2500},indent=2)+'\n')
        before=time.monotonic();child=subprocess.Popen([sys.executable,str(HERE/'evaluate.py'),'--mode','pick','--input',str(output),
            '--output',str(ROOT/'audit'),'--predecessor-control',plan['original_control_audit']['path']],start_new_session=True)
        try:code=child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            finish_child(child);raise TimeoutError('One independent audit timed out; no retry')
        records.append({'phase':'audit','wall_seconds':time.monotonic()-before,'returncode':code})
        report=json.loads((ROOT/'audit/evaluation.json').read_text());accepted=complete and code==0 and report.get('proceed_gate_passed') is True
        if not accepted:raise RuntimeError('Position-only timing comparison failed; preserve and stop')
    finally:
        elapsed=time.monotonic()-started;prior=plan['prior_case_seconds'];p=ROOT/'audit/evaluation.json'
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps({'schema':'free-position-dwell-supervisor-v1','phases':records,
            'actual_capture_plus_audit_seconds':elapsed,'prior_case_seconds':prior,'cumulative_case_seconds':prior+elapsed,'case_limit_seconds':2500,
            'maximum_active_seconds':150,'within_budget':elapsed<=150 and prior+elapsed<=2500,'control_reused':True,'improvement_round':1,
            'retention_fixture_passed':accepted,'proceed_gate_passed':accepted,'physics_extraction_passed':False,'perception_credit':False,
            'transfer_authorized':False,'automatic_retry':False,'audit_sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None},indent=2)+'\n')
if __name__=='__main__':main()

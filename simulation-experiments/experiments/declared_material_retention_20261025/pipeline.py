"""One declared-material correctness regression: fresh control, then conditional pick."""
import hashlib
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
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    plan=json.loads((HERE/'protocol.json').read_text())
    if not plan['execution_authorized']:raise RuntimeError('Final source review required')
    started=time.monotonic(); child=None; records=[]; accepted=False; control_passed=False; pick_attempted=False
    def cancel(number,_frame):
        if child is not None and child.poll() is None:finish_child(child)
        raise SystemExit(128+number)
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    try:
        for mode in ('control','pick'):
            before=time.monotonic(); elapsed_before=before-started
            if mode=='pick' and (not control_passed or 285-elapsed_before<plan['minimum_remaining_before_pick_seconds']):
                raise RuntimeError('Fresh control failed or insufficient remaining budget; no pick/retry')
            output=ROOT/mode;output.mkdir(exist_ok=False)
            final=ROOT/'experiments/final_workcell_20261024'
            cmd=[sys.executable,str(HERE/'run_fixture.py'),'--mode',mode,'--output',str(output),
                '--geometry',str(final/'geometry.json'),'--cameras',str(ROOT/'experiments/stage1_20261025/source_views_v1.json'),
                '--appearance',str(final/'appearance_config.json'),'--headless','--enable_cameras','--device','cpu']
            if mode=='pick':
                cmd+=['--predecessor-control',str(ROOT/'control_audit/evaluation.json'),'--control-capture',str(ROOT/'control')]
                pick_attempted=True
            reason='returned'
            with (output/'process.log').open('w') as log:
                child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if (output/'fixture_complete.json').exists():reason='complete_marker_cleanup';break
                        if (output/'failure.json').exists():reason='capture_failure';break
                        captured=sum(r['wall_seconds'] for r in records if r['phase']=='capture')
                        if captured+time.monotonic()-before>=plan['capture_cutoff_seconds'] or time.monotonic()-started>=255:
                            reason='capture_budget_exhausted';break
                        time.sleep(.1)
                finally:code=finish_child(child)
            duration=time.monotonic()-before
            complete=(output/'fixture_complete.json').exists() and not (output/'failure.json').exists()
            records.append({'phase':'capture','mode':mode,'wall_seconds':duration,'returncode':code,'cleanup':reason,'capture_completed':complete})
            remaining=min(plan['audit_limit_seconds'],285-(time.monotonic()-started))
            if remaining<=1:raise TimeoutError('No shared audit time remains')
            (output/'supervisor.json').write_text(json.dumps({'capture_completed':complete,'capture_wall_seconds':duration,
                'child_returncode':code,'cleanup':reason,'remaining_audit_seconds':remaining,
                'prior_case_seconds':plan['prior_case_seconds']+elapsed_before,'original_prior_case_seconds':plan['prior_case_seconds'],
                'current_case_elapsed_seconds':time.monotonic()-started,'maximum_active_seconds':300,'aggregate_case_ceiling_seconds':3000},indent=2)+'\n')
            before=time.monotonic()
            cmd=[sys.executable,str(HERE/'evaluate.py'),'--mode',mode,'--input',str(output),'--output',str(ROOT/(mode+'_audit'))]
            if mode=='pick':cmd+=['--predecessor-control',str(ROOT/'control_audit/evaluation.json')]
            child=subprocess.Popen(cmd,start_new_session=True)
            try:code=child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                finish_child(child);raise TimeoutError('Shared independent audit timeout; no retry')
            records.append({'phase':'audit','mode':mode,'wall_seconds':time.monotonic()-before,'returncode':code})
            report=json.loads((ROOT/(mode+'_audit/evaluation.json')).read_text())
            passed=complete and code==0 and report.get('proceed_gate_passed') is True
            if mode=='control':control_passed=passed
            else:accepted=passed
            if not passed:raise RuntimeError(mode+' fixture gate failed; preserve evidence and stop')
    finally:
        elapsed=time.monotonic()-started; prior=plan['prior_case_seconds']
        record={'schema':'declared-material-regression-supervisor-v1','phases':records,'actual_capture_plus_audit_seconds':elapsed,
            'prior_case_seconds':prior,'cumulative_case_seconds':prior+elapsed,'previous_case_limit_seconds':2800,'case_limit_seconds':3000,
            'maximum_active_seconds':300,'within_budget':elapsed<=300 and prior+elapsed<=3000,'control_passed':control_passed,
            'pick_attempted':pick_attempted,'improvement_round':0,'closed_old_fixture_improvements':3,'new_improvement_pool':0,'retention_fixture_passed':accepted,'proceed_gate_passed':accepted,
            'physics_extraction_passed':False,'perception_credit':False,'transfer_authorized':False,'automatic_retry':False}
        for mode in ('control','pick'):
            p=ROOT/(mode+'_audit/evaluation.json')
            record[mode+'_audit_sha256']=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps(record,indent=2)+'\n')

if __name__=='__main__':main()

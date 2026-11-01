"""One startup-only readback and JSON contract audit, sharing a60s budget."""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
plan=json.loads((HERE/'protocol.json').read_text())
SOURCE=Path(plan['source_snapshot'])
sys.path.insert(0,str(SOURCE))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child

def main():
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or not plan['execution_authorized']:raise RuntimeError('Approved default-Pueue job required')
    started=time.monotonic();child=None;records=[];accepted=False;output=ROOT/'output';output.mkdir(exist_ok=False)
    def cancel(number,_frame):
        if child is not None and child.poll() is None:finish_child(child)
        raise SystemExit(128+number)
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    try:
        final=SOURCE/'experiments/final_workcell_20261024'
        command=[sys.executable,str(HERE/'readback.py'),'--output',str(output),'--geometry',str(final/'geometry.json'),
            '--cameras',str(SOURCE/'experiments/stage1_20261025/source_views_v1.json'),'--appearance',str(final/'appearance_config.json'),
            '--headless','--enable_cameras','--device','cpu']
        before=time.monotonic();reason='returned'
        with (output/'process.log').open('w') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while child.poll() is None:
                    if (output/'readback_complete.json').exists():reason='complete_marker_cleanup';break
                    if (output/'failure.json').exists():reason='capture_failure';break
                    if time.monotonic()-started>=plan['capture_cutoff_seconds']:reason='capture_budget_exhausted';break
                    time.sleep(.1)
            finally:code=finish_child(child)
        duration=time.monotonic()-before;complete=(output/'readback_complete.json').exists() and not (output/'failure.json').exists()
        records.append({'phase':'capture','wall_seconds':duration,'returncode':code,'cleanup':reason,'capture_completed':complete})
        remaining=min(plan['audit_limit_seconds'],54-(time.monotonic()-started))
        if remaining<=0:raise TimeoutError('No shared audit time remains')
        (output/'supervisor.json').write_text(json.dumps({'capture_completed':complete,'capture_wall_seconds':duration,
            'prior_case_seconds':plan['prior_case_seconds'],'remaining_audit_seconds':remaining,'maximum_active_seconds':60,
            'aggregate_case_ceiling_seconds':2800},indent=2)+'\n')
        before=time.monotonic();child=subprocess.Popen([sys.executable,str(HERE/'evaluate.py'),'--input',str(output),'--output',str(ROOT/'audit')],start_new_session=True)
        try:code=child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            finish_child(child);raise TimeoutError('One readback audit timed out; no retry')
        records.append({'phase':'audit','wall_seconds':time.monotonic()-before,'returncode':code})
        report=json.loads((ROOT/'audit/evaluation.json').read_text());accepted=complete and code==0 and report.get('runtime_materials_verified') is True
        if not accepted:raise RuntimeError('Readback invariant/contract failed; preserve and stop')
    finally:
        elapsed=time.monotonic()-started;prior=plan['prior_case_seconds'];p=ROOT/'audit/evaluation.json'
        (ROOT/'pipeline_supervisor.json').write_text(json.dumps({'phases':records,'actual_capture_plus_audit_seconds':elapsed,
            'prior_case_seconds':prior,'cumulative_case_seconds':prior+elapsed,'case_limit_seconds':2800,'maximum_active_seconds':60,
            'within_budget':elapsed<=60 and prior+elapsed<=2800,'diagnostic_complete':report.get('diagnostic_complete',False) if 'report' in locals() else False,'runtime_materials_verified':accepted,'physics_extraction_passed':False,
            'physical_retry_authorized':False,'automatic_retry':False,'audit_sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None},indent=2)+'\n')
if __name__=='__main__':main()

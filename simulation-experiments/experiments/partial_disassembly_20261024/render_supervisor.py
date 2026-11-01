"""Queued foreground supervision of ten static captures; bounded post-capture Kit cleanup."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def finish_child(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    return process.returncode


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--cameras',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--python',required=True);p.add_argument('--capture-timeout',type=float,default=180)
    p.add_argument('--cleanup-timeout',type=float,default=5)
    a=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Rendering must use default Pueue')
    benchmark=json.loads(a.benchmark.read_text());a.output.mkdir(parents=True,exist_ok=True)
    adapter=Path(__file__).with_name('render_adapter.py');records=[]
    active=[None]
    def cancelled(signum, _frame):
        # Queue cancellation must not leave a GPU child outside its queued job.
        process=active[0]
        if process is not None:
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,cancelled);signal.signal(signal.SIGINT,cancelled)
    for case in benchmark['cases']:
        folder=a.output/case['split']/case['id'];folder.mkdir(parents=True,exist_ok=True)
        command=[a.python,str(adapter),'--case',case['id'],'--benchmark',str(a.benchmark),
                 '--geometry',str(a.geometry),'--cameras',str(a.cameras),'--output',str(folder),
                 '--views',','.join(benchmark['views']),'--headless','--enable_cameras','--device','cpu']
        start=time.monotonic();marker_seen=None;reason=None
        with (folder/'process.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            active[0]=process
            try:
                while process.poll() is None:
                    if (folder/'failure.json').exists():
                        reason='capture_failure';break
                    if (folder/'run_complete.json').exists():
                        if marker_seen is None:marker_seen=time.monotonic()
                        if time.monotonic()-marker_seen>a.cleanup_timeout:
                            reason='cleanup_stall_after_validated_capture';break
                    if time.monotonic()-start>a.capture_timeout:
                        reason='capture_timeout';break
                    time.sleep(.2)
            finally:
                code=finish_child(process)
                active[0]=None
        if reason in ('capture_failure','capture_timeout') or not (folder/'run_complete.json').exists():
            raise RuntimeError(f"Capture failed for {case['id']}: {reason}, exit={code}; see {folder/'process.log'}")
        marker=json.loads((folder/'run_complete.json').read_text())
        manifest=json.loads((folder/'manifest.json').read_text())
        expected=case['expected']
        actual=(manifest['brick_count'],manifest['native_connections'],manifest['native_connected_parts'])
        if not marker.get('capture_validated') or actual != (expected['active_bricks'],expected['native_connections'],expected['connected_parts']):
            raise RuntimeError(f"Capture/native graph mismatch in {case['id']}: {actual}")
        if not manifest['all_capture_states_exactly_equal']:
            raise RuntimeError('Camera capture advanced physical state')
        record={'case':case['id'],'split':case['split'],'directory':str(folder),'actual_counts':list(actual),
                'capture_validated':True,'child_returncode':code,'cleanup_result':reason or 'returned',
                'seconds':time.monotonic()-start}
        (folder/'supervisor.json').write_text(json.dumps(record,indent=2)+'\n')
        records.append(record)
        (a.output/'render_dataset.json').write_text(json.dumps({'cases':records,'views':benchmark['views']},indent=2)+'\n')
        print('STATIC_CAPTURE',json.dumps(record),flush=True)
    (a.output/'run_complete.json').write_text(json.dumps({'complete':True,'cases':len(records),'views_per_case':len(benchmark['views'])})+'\n')


if __name__=='__main__':main()

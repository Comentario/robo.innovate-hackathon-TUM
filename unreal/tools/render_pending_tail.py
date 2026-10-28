"""Use genuinely idle GPUs to pre-render the final tours' future chunks.

Outputs are rendered in isolated directories and published with an atomic
no-replace rename. The original queue remains the sole movie assembler.
"""
import argparse,concurrent.futures,ctypes,errno,hashlib,json,os,signal,subprocess,threading,time
from pathlib import Path

CHUNK=1800

def publish_no_replace(source,destination):
    """An existing destination, including an empty one, always wins the race."""
    library=ctypes.CDLL(None,use_errno=True)
    fn=getattr(library,'renameat2',None)
    if fn is None:raise RuntimeError('Atomic no-replace rename is unavailable')
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
    if fn(-100,os.fsencode(source),-100,os.fsencode(destination),1)==0:return True
    code=ctypes.get_errno()
    if code in (errno.EEXIST,errno.ENOTEMPTY):return False
    raise OSError(code,os.strerror(code),str(destination))

def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    from night_tours_worker import render_chunk,atomic,HASH,STOP
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);a=parser.parse_args();root=a.root.resolve();area=root/'Ahead';area.mkdir(exist_ok=True)
    lock=threading.RLock();state=dict(schema='brickflow.night-tail-support.v1',state='waiting_for_idle_gpus',publishedChunks=[],helpers={},pid=os.getpid())
    def report():
        with lock:
            state['updatedAt']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());atomic(root/'ahead-status.json',state)
    def snapshot():
        status=json.loads((root/'status.json').read_text());pid=int(subprocess.check_output(['systemctl','show','brickflow-final37-night.service','--value','-p','MainPID']))
        if pid<=0:return status,0
        os.kill(pid,0)
        assert 'night_tours_worker.py' in Path(f'/proc/{pid}/cmdline').read_bytes().decode()
        return status,pid
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
    report();pairs=[];parent=0
    while not STOP.is_set():
        try:
            status,parent=snapshot()
            if status['state']=='complete':
                state['state']='not_needed';report();return
            ready={r['number'] for r in status['ready']}
            if parent and status['state']=='running' and set(range(1,9))<=ready:
                active=status['active'];idle=sorted(set(range(4))-{int(g) for g in active})
                pending=sorted(v['tour'] for v in active.values() if v['tour'] in (9,10) and v['stage']=='render')
                pairs=list(zip(idle,pending))
                if pairs:break
            state['state']='waiting_for_idle_gpus';report()
        except (OSError,ValueError,KeyError,AssertionError,subprocess.SubprocessError) as e:
            state['observationError']=str(e);report()
        STOP.wait(30)
    if STOP.is_set():return
    state.update(state='supporting_tail',mainWorkerPid=parent);report()
    def support(pair):
        gpu,number=pair;plan=root/'Tours'/f'tour-{number:02}.json';tour=json.loads(plan.read_text());expected=fingerprint(plan)
        assert tour['referenceSha256']==HASH
        movie=root/'Movies'/f'Tour_{number:02}';chunks=movie/'Chunks';chunks.mkdir(exist_ok=True)
        try:
            while not STOP.is_set():
                current,pid=snapshot()
                if pid!=parent:STOP.set();break
                if str(gpu) in current['active']:STOP.set();break
                active=next((v for v in current['active'].values() if v['tour']==number and v['stage']=='render'),None)
                if not active or (movie/'delivery.json').exists():break
                head=active['firstFrame']
                choices=[f for f in range(0,tour['frames'],CHUNK) if f>=head+2*CHUNK and not (chunks/f'{f:06}-{min(f+CHUNK,tour["frames"]):06}').exists()]
                if not choices:break
                first=max(choices);last=min(first+CHUNK,tour['frames']);name=f'{first:06}-{last:06}';out=area/f'GPU_{gpu}'/f'Tour_{number:02}'/name
                with lock:state['helpers'][str(gpu)]=dict(tour=number,stage='render',firstFrame=first,lastFrame=last,output=str(out))
                report();render_chunk(root,gpu,tour,plan,out,first,last,port_base=7951)
                if STOP.is_set():break
                assert fingerprint(plan)==expected,'Camera plan changed during capture'
                current,pid=snapshot()
                if pid!=parent or str(gpu) in current['active']:STOP.set();break
                destination=chunks/name
                if publish_no_replace(out,destination):
                    audit=json.loads((destination/'verified.json').read_text())
                    with lock:state['publishedChunks'].append(dict(tour=number,gpu=gpu,first=first,last=last,sha256=audit['sha256']))
                else:
                    # Keep an independently verified fallback; never overwrite an
                    # original worker's existing directory, even while empty.
                    with lock:state['helpers'][str(gpu)]['publication']='original_directory_already_exists'
                report()
        except Exception as e:
            with lock:state['helpers'][str(gpu)]={'tour':number,'stage':'support_failed','error':str(e)}
            report();return
        with lock:state['helpers'][str(gpu)]={'tour':number,'stage':'finished'}
        report()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures=[pool.submit(support,pair) for pair in pairs]
        while not all(f.done() for f in futures) and not STOP.is_set():
            try:
                _,pid=snapshot()
                if pid!=parent:STOP.set();break
            except (OSError,ValueError,KeyError,AssertionError,subprocess.SubprocessError):
                # Re-observe the same parent; a transient observation failure
                # does not mean the original queue stopped.
                pass
            report();STOP.wait(5)
        for future in futures:future.result()
    state['state']='interrupted' if STOP.is_set() else 'assistance_finished';report()
if __name__=='__main__':main()

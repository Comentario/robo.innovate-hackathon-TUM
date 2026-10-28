"""Persistent, resumable four-GPU final37 render and editorial queue.

Each GPU owns one tour at a time. Completed chunks survive restarts. Source,
geometry and physical recording fingerprints are gates, never fallback hints.
"""
import argparse,concurrent.futures,csv,hashlib,json,os,signal,subprocess,sys,threading,time,traceback
from pathlib import Path
from composite_night_tour import compose,digest

HASH='3aa2ec3d3828a691e7020f4deca4dc86d093b69da1569b57c73865352a03f7c5'
LOCK=threading.Lock();STOP=threading.Event();ACTIVE={};STATE={}
def atomic(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2)+'\n');tmp.replace(path)
def status(root):
    with LOCK:
        STATE['updatedAt']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());STATE['active']={k:dict(v) for k,v in ACTIVE.items()}
        for entry in STATE['active'].values():
            if entry.get('chunkPath'):
                trace=Path(entry['chunkPath'])/'trace.csv'
                if trace.exists():
                    try:
                        with trace.open('rb') as f:f.seek(max(0,trace.stat().st_size-2048));lines=f.read().decode().splitlines()
                        entry['latestFrame']=int(lines[-1].split(',')[0])
                    except (ValueError,IndexError,OSError,UnicodeDecodeError):pass
        STATE['diskFreeGiB']=round(__import__('shutil').disk_usage(root).free/2**30,1)
        atomic(root/'status.json',STATE)
def process(command,log,timeout=18000,progress=None):
    with log.open('w') as out:
        p=subprocess.Popen(command,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'XDG_RUNTIME_DIR':str(Path.home()/'.cache/brickflow-final37')})
        start=time.time()
        try:
            while p.poll() is None:
                if STOP.is_set():raise RuntimeError('Service stopping; checkpoint retained')
                if time.time()-start>timeout:raise TimeoutError('Process exceeded time budget')
                if progress and progress.exists() and time.time()-progress.stat().st_mtime>600:raise TimeoutError('No new captured frame for ten minutes')
                STOP.wait(2)
            if p.returncode:raise RuntimeError(f'Process exited {p.returncode}; see {log}')
        except BaseException:
            try:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=20)
            except (ProcessLookupError,subprocess.TimeoutExpired):
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            raise

def engine_cmd(root,gpu,tour,out,first,last,width=3840,audit=False):
    base=Path.home()/'workspace';engine=base/'brickflow-cinematic/tools/unreal-5.8.4/Engine/Binaries/Linux/UnrealEditor';project=base/'brickflow-final37-native/Brickflow.uproject'
    runtime=root/'runtime.json'
    if runtime.exists():
        configured=json.loads(runtime.read_text()).get('project')
        if configured:
            project=Path(configured)
            assert project.is_absolute() and project.suffix=='.uproject' and project.is_file(),'Invalid isolated Unreal project'
    cmd=[str(engine),str(project),'/Engine/Maps/Entry','-game','-RenderOffscreen','-vulkan',f'-graphicsadapter={gpu}','-unattended','-nosound','-nosplash','-nop4','-Windowed','-ForceRes',f'-ResX={width}',f'-ResY={width*9//16}',
      f'-BrickflowReplay={root}/Assets/scene.json',f'-BrickflowTour={tour}',f'-BrickflowFilm={out}',f'-BrickflowFilmFirst={first}',f'-BrickflowFilmLast={last}','-BrickflowFilmSettle=8',
      '-BrickflowReviewLighting=candidate',f'-BrickflowReviewRig={root}/Assets/lighting.json',f'-abslog={out}/engine.log',
      '-ExecCmds=r.ScreenPercentage 100,r.AntiAliasingMethod 4,sg.ViewDistanceQuality 4,sg.ShadowQuality 4,sg.ReflectionQuality 4,r.MotionBlurQuality 0']
    if audit:cmd+=['-BrickflowSourceAudit','-nullrhi']
    return cmd

def verify_video(path,frames,width,decode=False):
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_streams','-show_format','-of','json',str(path)]))
    s=data['streams'][0];assert int(s['width'])==width and int(s['height'])==width*9//16
    assert s['r_frame_rate']=='30/1' and int(s['nb_read_frames'])==frames,(path,s.get('nb_read_frames'),frames)
    assert abs(float(data['format']['duration'])-frames/30)<.05
    packets=subprocess.Popen(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=pts_time,dts_time','-of','csv=p=0',str(path)],stdout=subprocess.PIPE,text=True)
    pts=[];last_dts=None;count=0
    for line in packets.stdout:
        cells=line.strip().split(',');p,d=map(float,cells[:2]);pts.append(p)
        if last_dts is not None:assert abs(d-last_dts-1/30)<2e-6
        last_dts=d;count+=1
    assert packets.wait()==0 and count==frames
    pts.sort();assert all(abs(b-a-1/30)<2e-6 for a,b in zip(pts,pts[1:]))
    return dict(file=path.name,bytes=path.stat().st_size,sha256=digest(path),frames=frames,width=width,height=width*9//16,fps=30,decodedFramesVerified=True,packetTimingVerified=True)

def verify_trace(path,tour,first=0,last=None):
    rows=list(csv.DictReader(path.open()));last=tour['frames'] if last is None else last
    assert len(rows)==last-first,(len(rows),last-first)
    prev=None;maxstep=0
    for i,row in enumerate(rows):
        assert int(row['frame'])==first+i and row['subject']==tour['subject']
        now=float(row['nativeSeconds']);v=(first+i)/30;s=next((s for s in tour['clock'] if v<s['videoStart']+s['duration']),tour['clock'][-1]);u=max(0,min(1,(v-s['videoStart'])/s['duration']));expected=s['nativeStart']+s['duration']*(s['rateStart']*u+(s['rateEnd']-s['rateStart'])*(u**3-.5*u**4));assert abs(expected-now)<1e-6
        if prev:
            assert now>=float(prev['nativeSeconds'])-1e-8
            step=sum((float(row['camera'+a])-float(prev['camera'+a]))**2 for a in 'XYZ')**.5;maxstep=max(maxstep,step)
            assert step<1500,'Camera discontinuity exceeds 15 metres/frame'
        prev=row
    return dict(frames=len(rows),continuousSourceClock=True,oneSubjectIdentity=True,maximumCameraStepCm=maxstep)

def render_chunk(root,gpu,tour,tourpath,out,first,last,width=3840,port_base=7901):
    out.mkdir(parents=True,exist_ok=True);video=out/'raw.mp4';done=out/'verified.json';frames=last-first
    if done.exists() and video.exists():
        report=json.loads(done.read_text())
        if report.get('referenceSha256')==HASH and report.get('frames')==frames and report.get('sha256')==digest(video):return
    for attempt in range(1,4):
        for name in ['complete.status','trace.csv']:(out/name).unlink(missing_ok=True)
        encoder=None
        try:
            port=port_base+gpu;partial=out/'raw.partial.mp4'
            enc=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning','-y','-filter_threads','2','-f','rawvideo','-pixel_format','bgra','-video_size',f'{width}x{width*9//16}','-framerate','30','-i',f'tcp://127.0.0.1:{port}?listen=1','-map','0:v','-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p','-an','-c:v','h264_nvenc','-gpu',str(gpu),'-preset','p7','-tune','hq','-rc','vbr','-cq','14','-b:v','0','-spatial-aq','1','-temporal-aq','1','-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1','-movflags','+faststart',str(partial)]
            with (out/f'encoder-{attempt}.log').open('w') as log:
                encoder=subprocess.Popen(enc,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);STOP.wait(1)
                cmd=engine_cmd(root,gpu,tourpath,out,first,last,width)+[f'-BrickflowFilmPort={port}']
                process(cmd,out/f'render-{attempt}.log',timeout=max(3600,frames*12),progress=out/'trace.csv')
                assert (out/'complete.status').exists(),'Unreal did not finish the chunk'
                assert encoder.wait(timeout=90)==0,'Encoder failed'
            trace=verify_trace(out/'trace.csv',tour,first,last);report=verify_video(partial,frames,width);partial.replace(video);report.update(referenceSha256=HASH,first=first,last=last,trace=trace);atomic(done,report);return
        except Exception as e:
            atomic(out/'last-error.json',dict(attempt=attempt,error=str(e),at=time.time()))
            if encoder and encoder.poll() is None:
                os.killpg(encoder.pid,signal.SIGTERM)
                try:encoder.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(encoder.pid,signal.SIGKILL)
            if STOP.is_set() or attempt==3:raise
            STOP.wait(10)

def tour_job(root,gpu,number,chunkframes):
    path=root/'Tours'/f'tour-{number:02}.json';tour=json.loads(path.read_text());out=root/'Movies'/f'Tour_{number:02}';out.mkdir(parents=True,exist_ok=True)
    final=out/'delivery.json'
    if final.exists():
        report=json.loads(final.read_text())
        if all((out/x['file']).exists() and digest(out/x['file'])==x['sha256'] for x in report['files']):return report
    audit=out/'CameraAudit';audit.mkdir(exist_ok=True)
    if not (audit/'verified.json').exists():
        (audit/'trace.csv').unlink(missing_ok=True);process(engine_cmd(root,gpu,path,audit,0,tour['frames'],audit=True),audit/'stdout.log',timeout=1200)
        atomic(audit/'verified.json',verify_trace(audit/'trace.csv',tour))
    chunks=[]
    for first in range(0,tour['frames'],chunkframes):
        last=min(first+chunkframes,tour['frames']);chunk=out/'Chunks'/f'{first:06}-{last:06}'
        with LOCK:ACTIVE[str(gpu)]=dict(tour=number,stage='render',firstFrame=first,lastFrame=last,totalFrames=tour['frames'],chunkPath=str(chunk))
        status(root);render_chunk(root,gpu,tour,path,chunk,first,last);chunks.append(chunk/'raw.mp4')
        with LOCK:STATE['completedChunks']=sum(1 for _ in (root/'Movies').glob('*/Chunks/*/verified.json'))
        status(root)
    concat=out/'concat.txt';concat.write_text(''.join("file '"+str(p)+"'\n" for p in chunks))
    with LOCK:ACTIVE[str(gpu)]=dict(tour=number,stage='composite',totalFrames=tour['frames'])
    status(root)
    physical=Path.home()/'workspace/brickflow-native/Saved/LightingReview'
    # An independent compositor process is bounded and killed with its group if stalled.
    command=[sys.executable,str(Path(__file__).with_name('composite_night_tour.py')),'--tour',str(path),'--concat',str(concat),'--franka',str(physical/'franka-cycle-source-1080x1920.mp4'),'--detection',str(physical/'Demo_Video1.mp4'),'--output',str(out),'--gpu',str(gpu)]
    for attempt in range(3):
        try:process(command,out/f'editorial-{attempt}.log',timeout=14400);break
        except Exception:
            if attempt==2 or STOP.is_set():raise
            STOP.wait(20)
    with LOCK:ACTIVE[str(gpu)]=dict(tour=number,stage='verify')
    status(root)
    files=[verify_video(out/'tour-4k.mp4',tour['frames'],3840),verify_video(out/'tour-1080p.mp4',tour['frames'],1920)]
    for name in ['poster.jpg','tour.json','trace.csv']:
        target=out/name
        if name=='tour.json':target.write_text(path.read_text())
        elif name=='trace.csv':target.write_text((audit/'trace.csv').read_text())
        files.append(dict(file=name,bytes=target.stat().st_size,sha256=digest(target)))
    report=dict(number=number,referenceSha256=HASH,complete=True,files=files,seconds=tour['frames']/30,subject=tour['subject'],stockPalletsAtStart=tour['stockPalletsAtStart'],inspectionNeverPaused=True,physicalOverlays=2,independentNativePlanner=False,cameraAudit=json.loads((audit/'verified.json').read_text()))
    atomic(final,report)
    # Only reproducible chunks belonging to this newly generated tour are removed.
    # Verified 4K/1080p deliveries, source events, camera trace and chunk audits remain.
    for raw in chunks:raw.unlink()
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--chunk-frames',type=int,default=1800);parser.add_argument('--smoke',action='store_true');args=parser.parse_args();root=args.root.resolve()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
    runtime=Path.home()/'.cache/brickflow-final37';runtime.mkdir(exist_ok=True);runtime.chmod(0o700)
    if args.smoke:
        tourpath=root/'Tours/tour-01.json';tour=json.loads(tourpath.read_text());render_chunk(root,1,tour,tourpath,root/'Smoke/stream',4135,4195,width=3840);print('STREAM_SMOKE_VERIFIED');return
    STATE.update(schema='brickflow.night-render-status.v1',referenceSha256=HASH,state='waiting_for_preparation',expectedTours=10,ready=[],failed=[],completedChunks=0)
    status(root)
    while not STOP.is_set():
        try:
            exported=json.loads((root/'Assets/export-status.json').read_text());audit=json.loads((root/'Assets/pose-audit.json').read_text());gate=json.loads((root/'preflight.json').read_text())
            assert exported['complete'] and exported['sourceSha256']==HASH and audit['verified'] and gate['approvedForQueue'] and gate['referenceSha256']==HASH
            assert digest(root/'Assets/replay.bin')==exported['replaySha256']
            scene=json.loads((root/'Assets/scene.json').read_text());assert digest(root/'Assets/geometry.json')==scene['geometrySha256']
            assert len(list((root/'Tours').glob('tour-??.json')))==10
            break
        except (OSError,ValueError,KeyError,AssertionError):status(root);STOP.wait(30)
    if STOP.is_set():return
    STATE['state']='running';status(root)
    remaining=list(range(1,11));queue_lock=threading.Lock()
    def worker(gpu):
        while not STOP.is_set():
            with queue_lock:
                if not remaining:break
                number=remaining.pop(0)
            try:
                report=tour_job(root,gpu,number,args.chunk_frames)
                with LOCK:STATE['ready'].append(dict(number=number,path=f'Movies/Tour_{number:02}/delivery.json',seconds=report['seconds']))
            except Exception as e:
                if STOP.is_set():return
                traceback.print_exc()
                with LOCK:STATE['failed'].append(dict(number=number,error=str(e)))
            with LOCK:ACTIVE.pop(str(gpu),None)
            status(root)
    def heartbeat():
        while not STOP.wait(15):status(root)
    threading.Thread(target=heartbeat,daemon=True).start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(worker,range(4)))
    STATE['state']='interrupted' if STOP.is_set() else 'needs_attention' if STATE['failed'] else 'complete';status(root)
    if STATE['failed']:raise SystemExit(1)
if __name__=='__main__':main()

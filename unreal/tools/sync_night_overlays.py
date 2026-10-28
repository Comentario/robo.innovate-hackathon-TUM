"""Event-aligned physical overlays, with clean native patches and 1080p delivery.

Recorded subjects remain independent. Source footage is retimed, never relabelled
or motion-generated. Camera and plant clocks remain the original final37 tours.
"""
import argparse,concurrent.futures,csv,json,math,os,signal,subprocess,sys,threading,time,traceback
from pathlib import Path
from composite_night_tour import card_assets,digest,FRANKA,DETECTION
from plan_night_tours import Clock
import night_tours_worker as W
from verify_night_composite import frame,check_rendered_clock
from PIL import ImageChops,ImageStat

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)

def source_at(o,video):
    knots=o['sourceKnots']
    for (a,x),(b,y) in zip(knots,knots[1:]):
        if video<=b:return x+(y-x)*max(0,min(1,(video-a)/(b-a)))
    return knots[-1][1]

def synced_plan(original,facts):
    t=json.loads(json.dumps(original));clock=Clock(t['sourceStart']);clock.segments=t['clock']
    tracks=facts['candidates'][0]['tracks']
    row=next(e['start'] for e in tracks if e['kind']=='raise-six-rows-each-side')
    place=next(e['end'] for e in tracks if e['kind']=='place-six-rows-on-v1')
    a,b=clock.at(row),clock.at(place)
    # Visual landmarks in the authentic 30 fps proxy: contact/lift 6.95 s;
    # deposit 10.65 s; release/withdrawal ends before the next physical cycle.
    f=dict(start=a-5.7,fadeIn=a-5.7,fadeSeconds=1.2,fadeOut=b+.45,end=b+1.65,
           sourceKnots=[[a-5.7,1.25],[a,6.95],[b,10.65],[b+1.65,12.3]],
           anchors=[dict(event='row-lift-start',nativeSeconds=row,videoSeconds=a,sourceSeconds=6.95),dict(event='row-placement-end',nativeSeconds=place,videoSeconds=b,sourceSeconds=10.65)])
    contrast=t.get('inspectionContrast')
    if contrast:
        scan=contrast['events']['inspection-entry']['start'];v=clock.at(scan)
        # Keep the authentic BAD #28 sequence, before the next GOOD result.
        d=dict(start=v+.7,fadeIn=v+.7,fadeSeconds=.35,fadeOut=v+3.3,end=v+4,
               sourceKnots=[[v+.7,0],[v+4,1.1]],anchors=[dict(event='rejected-inspection-center',nativeSeconds=scan+1.125,videoSeconds=clock.at(scan+1.125),sourceSeconds=1.1*.425/3.3)])
    else:
        scan=next(e['start'] for e in tracks if e['kind']=='inspection-entry');v=clock.at(scan)
        center=clock.at(scan+1.125);rate=(6.7-4.6)/(center-(v-2))
        end=v-2+(7.85-4.6)/rate
        d=dict(start=v-2,fadeIn=v-2,fadeSeconds=.8,fadeOut=end-.7,end=end,
               sourceKnots=[[v-2,4.6],[end,7.85]],anchors=[dict(event='good-inspection-center',nativeSeconds=scan+1.125,videoSeconds=center,sourceSeconds=6.7)])
    for o in [f,d]:
        assert all(b[0]>a[0] and b[1]>a[1] for a,b in zip(o['sourceKnots'],o['sourceKnots'][1:]))
        for anchor in o['anchors']:assert abs(source_at(o,anchor['videoSeconds'])-anchor['sourceSeconds'])<1e-7
    for segment in t['clock']:
        if segment['videoStart']<d['end'] and segment['videoStart']+segment['duration']>d['start']:assert segment['rateStart']==segment['rateEnd']==1
    t['overlays']=dict(franka=f,detection=d);t['overlayRevision']=2
    t['overlaySyncEvidence']='Manually reviewed recorded contact/deposit and same-class inspection landmarks; editorial synchronization, not paired specimen identities or independent physical validation.'
    return t

def repair_windows(old,new):
    return [(max(0,math.floor(min(old['overlays'][k]['start'],new['overlays'][k]['start'])*30)-2),min(old['frames'],math.ceil(max(old['overlays'][k]['end'],new['overlays'][k]['end'])*30)+2)) for k in ['franka','detection']]

def preserve(root,sync):
    # A verified hard link survives the original queue deleting its raw pathname.
    for n in range(1,11):
        for p in sorted((root/f'Movies/Tour_{n:02}/Chunks').glob('*/raw.mp4')):
            first,last=map(int,p.parent.name.split('-'))
            if first>7200 or last<1800 or not (p.parent/'verified.json').exists():continue
            dest=sync/f'Base/Tour_{n:02}/Chunks'/p.parent.name;dest.mkdir(parents=True,exist_ok=True)
            for name in ['raw.mp4','verified.json','trace.csv']:
                try:os.link(p.parent/name,dest/name)
                except FileExistsError:pass
                except FileNotFoundError:pass

def retime_filter(label,o,out):
    knots=o['sourceKnots'];v0,s0=knots[0]
    expr=None
    for (a,x),(b,y) in reversed(list(zip(knots,knots[1:]))):
        term=f'({a-v0:.12f}+(PTS*TB-{x-s0:.12f})*{(b-a)/(y-x):.12f})/TB'
        expr=term if expr is None else f'if(lt(PTS*TB\\,{y-s0:.12f})\\,{term}\\,{expr})'
    return f'[{label}]trim=start={s0}:end={knots[-1][1]},setpts=PTS-STARTPTS,setpts={expr},fps=30,scale=PLACEHOLDER:flags=lanczos,setsar=1,format=rgba[{out}]'

def compose(root,sync,n,tour,patches,gpu):
    out=sync/f'Movies/Tour_{n:02}';out.mkdir(parents=True,exist_ok=True)
    old=json.loads((root/f'Tours/tour-{n:02}.json').read_text());windows=repair_windows(old,tour)
    physical=Path.home()/'workspace/brickflow-native/Saved/LightingReview';franka=physical/'franka-cycle-source-1080x1920.mp4';detection=physical/'Demo_Video1.mp4'
    assert digest(franka)==FRANKA and digest(detection)==DETECTION
    card_assets(out,'franka',924,1642);card_assets(out,'detection',1536,1192)
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning','-y','-filter_complex_threads','2','-i',str(root/f'Movies/Tour_{n:02}/tour-4k.mp4')]
    for p,first,last in patches:cmd+=['-i',str(p)]
    fi=1+len(patches);di=fi+1;cmd+=['-i',str(franka),'-i',str(detection)]
    maskindex=di+1
    for name in ['franka-mask','franka-shadow','detection-mask','detection-shadow']:cmd+=['-loop','1','-framerate','30','-i',str(out/(name+'.png'))]
    graph='[0:v]fps=30,setpts=PTS-STARTPTS,scale=1920:1080:flags=lanczos,setsar=1[base0];'
    windows_expr='+'.join(f'between(n\\,{a}\\,{b-1})' for a,b in windows)
    for i,(p,first,last) in enumerate(patches):
        graph+=f'[{i+1}:v]fps=30,setpts=PTS-STARTPTS+{first}/30/TB,scale=1920:1080:flags=lanczos,setsar=1[clean{i}];'
        graph+=f'[base{i}][clean{i}]overlay=0:0:eof_action=pass:repeatlast=0:enable=\'{windows_expr}\'[base{i+1}];'
    for name,idx,mask,shadow,w,h in [('franka',fi,maskindex,maskindex+1,924,1642),('detection',di,maskindex+2,maskindex+3,1536,1192)]:
        o=tour['overlays'][name];start=o['start'];end=o['end']-start;a=o['fadeIn']-start;b=o['fadeOut']-start
        graph+=retime_filter(f'{idx}:v',o,name+'feed').replace('PLACEHOLDER',f'{w}:{h}')+';'
        graph+=f'[{mask}:v]format=gray[{name}mask];[{name}feed][{name}mask]alphamerge[{name}masked];'
        graph+=f'[{shadow}:v][{name}masked]overlay=48:48:shortest=1:format=auto,fade=t=in:st={a}:d={o["fadeSeconds"]}:alpha=1,fade=t=out:st={b}:d={end-b}:alpha=1,scale=iw/2:ih/2,setpts=PTS+{start}/TB[{name}card];'
    graph+=f'[base{len(patches)}][frankacard]overlay=1358:105:eof_action=pass:repeatlast=0:format=auto[first];[first][detectioncard]overlay=43:24:eof_action=pass:repeatlast=0:format=auto,format=yuv420p[out]'
    (out/'filtergraph.txt').write_text(graph)
    partial=out/'tour-1080p.partial.mp4';target=out/'tour-1080p.mp4'
    cmd+=['-filter_complex',graph,'-map','[out]','-frames:v',str(tour['frames']),'-an','-map_metadata','-1','-c:v','h264_nvenc','-gpu',str(gpu),'-preset','p7','-tune','hq','-rc','vbr','-cq','18','-b:v','0','-pix_fmt','yuv420p','-movflags','+faststart',str(partial)]
    W.process(cmd,out/'composite.log',timeout=10800);report=W.verify_video(partial,tour['frames'],1920);partial.replace(target);report['file']=target.name
    checks={}
    for name,source,box in [('franka',franka,(1382,129,462,821)),('detection',detection,(67,48,768,596))]:
        results=[];o=tour['overlays'][name]
        for anchor in o['anchors']:
            vf=math.ceil(anchor['videoSeconds']*30);v=vf/30;sf=round(source_at(o,v)*30)
            x,y,w,h=box;actual=frame(target,v).crop((x,y,x+w,y+h));inner=(w//10,h//10,w-w//10,h-h//10)
            candidates=[]
            for index in range(max(0,sf-2),sf+3):
                expected=frame(source,index/30,(w,h));delta=ImageChops.difference(actual.crop(inner),expected.crop(inner));candidates.append((sum(ImageStat.Stat(delta).mean)/3,index))
            error,index=min(candidates);assert error<10,(name,anchor['event'],'Source pixels differ',error)
            results.append(dict(event=anchor['event'],videoFrame=vf,sourceFrame=index,expectedSourceSeconds=anchor['sourceSeconds'],meanAbsoluteRgbError=error))
        checks[name]=results
    checks['renderedClock']=check_rendered_clock(root/f'Movies/Tour_{n:02}/Chunks',tour)
    checks.update(verified=True,overlayRevision=2,independentPhysicalValidation=False,movieSha256=report['sha256'])
    atomic(out/'sync-verification.json',checks)
    W.process(['ffmpeg','-nostdin','-v','error','-y','-ss','4','-i',str(target),'-frames:v','1',str(out/'poster.jpg')],out/'poster.log',timeout=120)
    (out/'tour.json').write_text(json.dumps(tour,indent=2)+'\n');(out/'trace.csv').write_text((root/f'Movies/Tour_{n:02}/CameraAudit/trace.csv').read_text())
    files=[report]+[dict(file=name,bytes=(out/name).stat().st_size,sha256=digest(out/name)) for name in ['poster.jpg','tour.json','trace.csv','sync-verification.json']]
    return dict(number=n,referenceSha256=W.HASH,complete=True,files=files,seconds=tour['frames']/30,physicalOverlays=2,inspectionNeverPaused=True,overlayRevision=2,independentNativePlanner=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--gpu',type=int,default=0);a=p.parse_args();root=a.root;sync=root/'OverlaySync';sync.mkdir(exist_ok=True)
    for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,lambda *_:W.STOP.set())
    def linker():
        while not W.STOP.is_set():
            try:preserve(root,sync)
            except Exception:traceback.print_exc()
            W.STOP.wait(10)
    threading.Thread(target=linker,daemon=True).start()
    facts=json.loads((root/'Assets/facts.json').read_text());state=dict(state='running',expectedTours=10,ready=[],failed=[],active={})
    def status():state['updatedAt']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());atomic(sync/'status.json',state)
    status()
    for n in [5,2,1,3,4,6,7,8,9,10]:
        if W.STOP.is_set():break
        original=json.loads((root/f'Tours/tour-{n:02}.json').read_text());tour=synced_plan(original,facts);out=sync/f'Movies/Tour_{n:02}';out.mkdir(parents=True,exist_ok=True)
        final=out/'delivery.json'
        if final.exists():
            report=json.loads(final.read_text())
            if report.get('overlayRevision')==2 and all((out/f['file']).exists() and digest(out/f['file'])==f['sha256'] for f in report['files']):
                state['ready'].append(dict(number=n,path=f'Movies/Tour_{n:02}/delivery.json'));status();continue
        state['active']={'0':dict(tour=n,stage='waiting_for_base')};status()
        while not (root/f'Movies/Tour_{n:02}/delivery.json').exists() and not W.STOP.wait(10):pass
        if W.STOP.is_set():break
        try:
            preserve(root,sync);patches=[]
            for first,last in repair_windows(original,tour):
                candidates=[]
                for pth in sorted((sync/f'Base/Tour_{n:02}/Chunks').glob('*/raw.mp4')):
                    x,y=map(int,pth.parent.name.split('-'))
                    if x<last and y>first:candidates.append((pth,x,y))
                covered=first
                for pth,x,y in candidates:
                    if x>covered:break
                    covered=max(covered,y)
                if covered>=last:patches.extend(candidates);continue
                patch=sync/f'Patches/Tour_{n:02}/{first:06}-{last:06}'
                state['active']={'0':dict(tour=n,stage='native_clean_patch',firstFrame=first,lastFrame=last)};status()
                W.render_chunk(root,a.gpu,original,root/f'Tours/tour-{n:02}.json',patch,first,last,port_base=7971)
                patches.append((patch/'raw.mp4',first,last))
            patches=list(dict.fromkeys(patches));state['active']={'0':dict(tour=n,stage='compose_synced_1080p')};status()
            report=compose(root,sync,n,tour,patches,a.gpu);atomic(final,report)
            state['ready'].append(dict(number=n,path=f'Movies/Tour_{n:02}/delivery.json'));status()
        except Exception as e:
            traceback.print_exc();state['failed'].append(dict(number=n,error=str(e)));status()
            if W.STOP.is_set():break
    state['active']={};state['state']='interrupted' if W.STOP.is_set() else 'needs_attention' if state['failed'] else 'complete';status()
    if state['failed']:raise SystemExit(1)
if __name__=='__main__':main()

"""Mirror completed cloud tours to the owner's Windows review folder, restarting safely."""
import argparse,html,json,os,shutil,subprocess,time,traceback
from pathlib import Path
from export_video_reviews import digest,copy_with_windows,windows_path

def atomic(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2)+'\n');tmp.replace(path)
def remote(host,path):
    # Paths are fixed generated paths; no user-supplied shell fragments.
    return subprocess.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=20',host,'cat',path],timeout=60)
def gallery(output,status,delivered,error=''):
    cards=[]
    ready={x['number'] for x in status.get('ready',[])}
    for number in range(1,11):
        name=f'Tour_{number:02}';entry=delivered.get(str(number));state='Delivered' if entry else 'Downloading' if number in ready else 'Queued / rendering'
        master=f'<a href="{name}/tour-4k.mp4">4K master</a> · ' if entry and any(f['file']=='tour-4k.mp4' for f in entry['files']) else ''
        content=f'<video controls preload="none" poster="{name}/poster.jpg" src="{name}/tour-1080p.mp4"></video><p>{master}<a href="{name}/tour-1080p.mp4">1080p review</a> · <a href="{name}/tour.json">Camera plan</a></p>' if entry else '<div class="placeholder">The complete movie will appear here after verification.</div>'
        cards.append(f'<article><h2>Tour {number:02} <small>{state}</small></h2>{content}</article>')
    active=' · '.join(f'GPU {k}: Tour {v["tour"]:02} / {v["stage"]}'+(f' / frame {v["latestFrame"]:,} of {v["totalFrames"]:,}' if 'latestFrame' in v else '') for k,v in status.get('active',{}).items())
    text='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Brickflow · Final 37 tours</title><style>body{background:#0b0e13;color:#e9edf3;font:16px system-ui;margin:40px auto;max-width:1400px;padding:0 24px}h1{font-size:40px}p,small{color:#aebcca}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:24px}article{background:#141b25;border:1px solid #283344;border-radius:18px;padding:22px}small{font-size:14px;margin-left:12px}video{width:100%;border-radius:8px}a{color:#9ddd67}.placeholder{aspect-ratio:16/9;display:grid;place-items:center;background:#0b1018;border-radius:8px;padding:20px}aside{padding:18px;background:#182318;border-radius:12px;margin:24px 0}</style>'
    text+=f'<h1>Brickflow · Final 37 tours</h1><p>Second kiln cart → dehacking → row transfer → inspection → pallet → inventory → truck departure</p><aside>{len(delivered)} / 10 delivered · Cloud: {html.escape(status.get("state","connecting"))}<br>{html.escape(active)}<br>Updated: {html.escape(status.get("updatedAt","waiting for cloud"))}</aside>'
    if error:text+='<p>Delivery reconnecting: '+html.escape(error)+'</p>'
    text+='<p>Every tour includes the physical Franka and one real classifier feed. TIMELAPSE labels show the source clock speed. Recorded hardware and simulated brick IDs are not paired.</p><main>'+''.join(cards)+'</main><p>Continuous native C++ playback of the final source timeline in Unreal. Editorial comparison; no independent physical validation is implied.</p></html>'
    if len(delivered)<10:
        text=text.replace('</html>','<script>setInterval(()=>{if(![...document.querySelectorAll("video")].some(v=>!v.paused))location.reload()},60000)</script></html>')
    temp=output/'index.html.tmp';temp.write_text(text);temp.replace(output/'index.html')

def transfer(host,remote_path,local,expected):
    local.parent.mkdir(parents=True,exist_ok=True)
    if local.exists() and digest(local)==expected:return
    partial=local.with_suffix(local.suffix+'.partial')
    subprocess.run(['rsync','--partial','--append-verify','--timeout=120','-e','ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=20',host+':'+remote_path,str(partial)],check=True,timeout=7200)
    assert digest(partial)==expected,'Downloaded file hash mismatch';partial.replace(local)

def ready_order(items,cache,delivered):
    """Resume the furthest-downloaded tour first after a service or WSL restart."""
    def priority(item):
        folder=cache/f'Tour_{item["number"]:02}'
        cached=sum(f.stat().st_size for f in folder.glob('*') if f.is_file() and
                   (f.name.endswith('.mp4') or f.name.endswith('.mp4.partial')))
        return (-cached,item['number'])
    return sorted((item for item in items if str(item['number']) not in delivered),key=priority)

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='brickflow-cinematic-4gpu');p.add_argument('--remote-root',default='/home/shadeform/workspace/brickflow-final37-night');p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--once',action='store_true');p.add_argument('--1080-only',action='store_true',dest='only_1080');a=p.parse_args()
    a.cache.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    manifest=a.output/'delivery-status.json';delivered=json.loads(manifest.read_text()).get('delivered',{}) if manifest.exists() else {};status={};errors=0
    while True:
        try:
            status=json.loads(remote(a.host,a.remote_root+'/status.json'));atomic(a.output/'cloud-status.json',status);gallery(a.output,status,delivered)
            for item in ready_order(status.get('ready',[]),a.cache,delivered):
                number=item['number'];name=f'Tour_{number:02}'
                if str(number) in delivered:continue
                report=json.loads(remote(a.host,a.remote_root+'/'+item['path']));assert report['complete'] and report['physicalOverlays']==2 and report['inspectionNeverPaused']
                if a.only_1080:
                    report['files']=[f for f in report['files'] if f['file']!='tour-4k.mp4']
                    assert any(f['file']=='tour-1080p.mp4' for f in report['files'])
                    report['deliveryResolution']='1080p'
                pending=[]
                for file in report['files']:
                    assert '/' not in file['file'] and '..' not in file['file']
                    source=a.cache/name/file['file'];target=a.output/name/file['file']
                    transfer(a.host,a.remote_root+'/Movies/'+name+'/'+file['file'],source,file['sha256'])
                    pending.append(dict(windowsSource=windows_path(source),windowsDestination=windows_path(target),file=name+'/'+file['file'],sha256=file['sha256'],bytes=file['bytes']))
                # Native Windows file copy is faster than large writes through drvfs.
                sockets=sorted(Path('/run/WSL').glob('*_interop'),key=lambda x:x.stat().st_mtime,reverse=True)
                if sockets and not Path(os.environ.get('WSL_INTEROP','/nonexistent')).exists():os.environ['WSL_INTEROP']=str(sockets[0])
                try:copy_with_windows(pending,a.output/name,True)
                except (OSError,RuntimeError):
                    # A headless WSL service may have no Windows interop session.
                    for file in report['files']:
                        source=a.cache/name/file['file'];target=a.output/name/file['file'];target.parent.mkdir(parents=True,exist_ok=True)
                        if target.exists():assert digest(target)==file['sha256'];continue
                        temp=target.with_suffix(target.suffix+'.partial');shutil.copyfile(source,temp);assert digest(temp)==file['sha256'];temp.replace(target)
                atomic(a.output/name/'verification.json',report);delivered[str(number)]=dict(number=number,referenceSha256=report['referenceSha256'],files=report['files'])
                atomic(manifest,dict(delivered=delivered,complete=len(delivered)==10,updatedAt=time.time()));gallery(a.output,status,delivered)
            errors=0
            if len(delivered)==10:return
        except Exception as e:
            errors+=1;traceback.print_exc();gallery(a.output,status,delivered,str(e));atomic(a.cache/'last-error.json',dict(error=str(e),at=time.time(),consecutive=errors))
        if a.once:return
        time.sleep(min(180,30+errors*15))
if __name__=='__main__':main()

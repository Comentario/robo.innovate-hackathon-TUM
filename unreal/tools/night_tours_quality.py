"""Run encoded-pixel and full captured-clock audits as each final tour appears."""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from export_video_reviews import digest

HASH='3aa2ec3d3828a691e7020f4deca4dc86d093b69da1569b57c73865352a03f7c5'
STOP=False

def atomic(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.replace(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--once',action='store_true');a=p.parse_args();root=a.root.resolve();out=root/'Quality';out.mkdir(exist_ok=True)
    physical=Path.home()/'workspace/brickflow-native/Saved/LightingReview';verified={};failed={}
    def stopping(*_):
        global STOP
        STOP=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stopping)
    while not STOP:
        for number in range(1,11):
            if STOP:break
            movie=root/'Movies'/f'Tour_{number:02}';manifest=movie/'delivery.json';audit=out/f'tour-{number:02}.json'
            if not manifest.exists():continue
            try:
                delivery=json.loads(manifest.read_text());assert delivery['complete'] and delivery['referenceSha256']==HASH
                master=next(f for f in delivery['files'] if f['file']=='tour-4k.mp4');fingerprint=master['sha256']
                if str(number) in verified and verified[str(number)]['movieSha256']==fingerprint:continue
                if audit.exists():
                    cached=json.loads(audit.read_text())
                    if cached.get('verified') and cached.get('movieSha256')==fingerprint:
                        verified[str(number)]=cached;failed.pop(str(number),None);continue
                assert digest(movie/'tour-4k.mp4')==fingerprint,'Final master differs from its delivery manifest'
                command=[sys.executable,str(Path(__file__).with_name('verify_night_composite.py')),'--tour',str(movie/'tour.json'),'--movie',str(movie/'tour-4k.mp4'),'--franka',str(physical/'franka-cycle-source-1080x1920.mp4'),'--detection',str(physical/'Demo_Video1.mp4'),'--chunks',str(movie/'Chunks'),'--output',str(audit)]
                with (out/f'tour-{number:02}.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
                report=json.loads(audit.read_text());assert report['verified'] and report['renderedClock']['allFramesContiguous'] and report['renderedClock']['inspectionAlwaysOneX']
                report.update(movieSha256=fingerprint,number=number,checkedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()));atomic(audit,report);verified[str(number)]=report;failed.pop(str(number),None)
            except Exception as e:
                failed[str(number)]={'error':str(e),'at':time.time()};atomic(out/f'tour-{number:02}-error.json',failed[str(number)])
        state=dict(referenceSha256=HASH,complete=len(verified)==10,verified=verified,failed=failed,pid=os.getpid(),updatedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
        atomic(root/'quality-status.json',state)
        if state['complete'] or a.once:return
        for _ in range(30):
            if STOP:return
            time.sleep(1)
if __name__=='__main__':main()

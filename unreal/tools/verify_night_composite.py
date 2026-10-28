"""Inspect actual encoded tours for both real feeds and the rendered source clock.

This verifies editorial inclusion and continuity. It does not establish a physical
correspondence between synthetic identities and the recorded specimens.
"""
import argparse,csv,io,json,math,subprocess
from pathlib import Path
from PIL import Image,ImageChops,ImageStat

def frame(path,time,scale=None):
    command=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-ss',f'{time:.9f}','-i',str(path),'-frames:v','1']
    if scale:command+=['-vf',f'scale={scale[0]}:{scale[1]}:flags=lanczos']
    return Image.open(io.BytesIO(subprocess.check_output(command+['-f','image2pipe','-vcodec','png','-']))).convert('RGB')
def inspect_feed(movie,source,definition,box):
    # A point after the fade but before source exhaustion; compare exact interior
    # pixels against nearby source frames to accommodate ffmpeg frame sync rounding.
    video_frame=math.ceil((definition['fadeIn']+2)*30);time=video_frame/30
    source_frame=math.floor((time-definition['start'])*30)
    assert 0<=source_frame<definition['clipSeconds']*30
    x,y,w,h=box;actual=frame(movie,time).crop((x,y,x+w,y+h));inner=(w//10,h//10,w-w//10,h-h//10)
    candidates=[]
    for index in range(max(0,source_frame-2),source_frame+3):
        expected=frame(source,index/30,(w,h));delta=ImageChops.difference(actual.crop(inner),expected.crop(inner));mae=sum(ImageStat.Stat(delta).mean)/3
        candidates.append((mae,index))
    error,index=min(candidates);assert error<10,(source.name,'Real-feed pixels do not match the source',error)
    return dict(verified=True,videoFrame=video_frame,videoSeconds=time,sourceFrame=index,meanAbsoluteRgbError=error,interiorBoundsPixels=list(inner))
def check_rendered_clock(chunks,tour):
    rows=[]
    for path in sorted(chunks.glob('*/trace.csv')):
        part=list(csv.DictReader(path.open()));rows.extend(part)
    assert len(rows)==tour['frames'],('Rendered trace coverage',len(rows),tour['frames'])
    previous=None;maximum_rate_error=0
    for i,row in enumerate(rows):
        assert int(row['frame'])==i and row['subject']==tour['subject']
        t=i/30;s=next((s for s in tour['clock'] if t<s['videoStart']+s['duration']),tour['clock'][-1]);u=max(0,min(1,(t-s['videoStart'])/s['duration']));rate=s['rateStart']+(s['rateEnd']-s['rateStart'])*u*u*(3-2*u)
        maximum_rate_error=max(maximum_rate_error,abs(float(row['speed'])-rate))
        native=float(row['nativeSeconds']);expected=s['nativeStart']+s['duration']*(s['rateStart']*u+(s['rateEnd']-s['rateStart'])*(u**3-.5*u**4));assert abs(native-expected)<1e-6
        if previous is not None:assert native>=previous-1e-9
        previous=native
        d=tour['overlays']['detection']
        if d['start']<=t<=d['end']:assert abs(float(row['speed'])-1)<1e-9
    assert maximum_rate_error<1e-8
    return dict(renderedFrames=len(rows),allFramesContiguous=True,nativeClockContinuous=True,maximumSpeedError=maximum_rate_error,inspectionAlwaysOneX=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--tour',type=Path,required=True);p.add_argument('--movie',type=Path,required=True);p.add_argument('--franka',type=Path,required=True);p.add_argument('--detection',type=Path,required=True);p.add_argument('--chunks',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();t=json.loads(a.tour.read_text())
    result=dict(verified=True,referenceSha256=t['referenceSha256'],name=t['name'],independentPhysicalValidation=False)
    result['franka']=inspect_feed(a.movie,a.franka,t['overlays']['franka'],(2765,259,924,1642))
    result['detection']=inspect_feed(a.movie,a.detection,t['overlays']['detection'],(134,97,1536,1192))
    if a.chunks:result['renderedClock']=check_rendered_clock(a.chunks,t)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()

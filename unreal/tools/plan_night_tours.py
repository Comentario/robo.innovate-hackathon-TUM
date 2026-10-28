"""Author ten continuous final37 camera tours from pinned source event times."""
import argparse, bisect, json, math
from pathlib import Path

class Clock:
    def __init__(self, start): self.native=start;self.video=0.;self.segments=[]
    def add(self,d,a,b,name):
        assert d>0 and min(a,b)>=0
        self.segments.append(dict(videoStart=self.video,duration=d,nativeStart=self.native,rateStart=a,rateEnd=b,name=name))
        self.video+=d;self.native+=d*(a+b)/2
    def normal(self,t,name):
        if t>self.native+1e-7:self.add(t-self.native,1,1,name)
        assert abs(self.native-t)<1e-5,(self.native,t,name)
    def fast(self,t,peak,name,ramp=3.):
        delta=t-self.native
        if delta<ramp*(1+peak)+2: self.normal(t,name);return
        self.add(ramp,1,peak,name+' / accelerate')
        self.add((delta-ramp*(1+peak))/peak,peak,peak,name)
        self.add(ramp,peak,1,name+' / decelerate')
        assert abs(self.native-t)<1e-5
    @staticmethod
    def state(s,v):
        u=max(0,min(1,(v-s['videoStart'])/s['duration']))
        return s['nativeStart']+s['duration']*(s['rateStart']*u+(s['rateEnd']-s['rateStart'])*(u**3-.5*u**4))
    def at(self,t):
        for s in self.segments:
            if self.state(s,s['videoStart']+s['duration'])>=t-1e-8:
                lo=s['videoStart'];hi=lo+s['duration']
                for _ in range(60):
                    m=(lo+hi)/2
                    if self.state(s,m)<t:lo=m
                    else:hi=m
                return (lo+hi)/2
        raise ValueError(t)

def make(facts,index):
    candidate=facts['candidates'][0];p=candidate['pallet'];tracks=candidate['tracks']
    def event(kind,end=False):
        s=next(t for t in tracks if t['kind']==kind);return s['end' if end else 'start']
    start=facts['cart2Delivery']['start'];clock=Clock(start)
    wait=[32,40,24,32,40,28,36,24,40,32][index-1]
    stock=[96,128,80,120,160,96,144,80,128,112][index-1]
    clock.normal(start+8,'Second kiln cart arrival')
    clock.fast(facts['cart2Delivery']['end']-6,4,'Kiln cart transit',2)
    clock.normal(facts['cart2Delivery']['end'],'Kiln cart docking')
    clock.fast(event('lift-36-top-layers')-5,wait,'Wait for dehacking')
    clock.normal(event('place-on-loading-belts',True)+3,'Dehacking and loading')
    clock.fast(event('common-main-belt')-3,wait,'Loading belt queue')
    clock.normal(event('common-main-belt',True)+2,'Main belt transport')
    row=event('raise-six-rows-each-side');place=event('place-six-rows-on-v1',True)
    clock.fast(row-12,wait,'Main belt accumulation')
    clock.normal(place+2,'Profile row transfer with physical Franka')
    # Only physical manipulation has an editorial hold. Inspection never freezes.
    clock.add(2,1,0,'Franka comparison / ease to hold');clock.add(3+(index%3),0,0,'Franka comparison');clock.add(2,0,1,'Franka comparison / resume')
    scan=event('inspection-entry')
    clock.normal(event('roller-row-accumulation',True)+1,'Inspection and routing / real detection overlay')
    clock.fast(event('layer-buffer-zone-one')-2,4,'Row accumulation',2)
    clock.normal(event('place-guided-layer',True)+2,'Complete layer placement')
    clock.fast(event('finished-pallet-outfeed')-3,wait,'Continuous pallet assembly',4)
    clock.normal(event('finished-pallet-outfeed',True)+2,'Finished pallet outfeed')
    clock.fast(event('lift-supported-output-pallet')-3,12,'Bridge pickup queue',2)
    clock.normal(p['storedAt']+3,'Supported bridge transfer and stock placement')
    clock.fast(event('amr-lift-pallet')-4,stock,'Inventory dwell',3)
    clock.normal(event('amr-loaded-to-side-loading-bay')+2,'AMR pallet pickup')
    clock.fast(event('amr-raise-forks-to-trailer')-3,6 if index%2 else 4,'Loaded AMR travel',2)
    clock.normal(p['loadedAt']+12,'Reach forks and trailer loading')
    clock.fast(event('truck-order-departure')-4,wait,'Truck order completion')
    clock.normal(p['shippedAt']+3,'Loaded truck departure')
    outro=clock.video
    clock.add(5,1,40,'Plant reveal / accelerate')
    clock.add(43,40,40,'Plant operation timelapse')
    assert clock.native<facts['total']
    lane=facts['lanes'][p['lane']]['z'];yaw=math.radians([-12,-6,0,6,12,-9,-3,3,9,15][index-1]);height=[1,1.08,.96,1.12,1.03,.92,1.06,1,1.10,.98][index-1]
    def offset(v):
        x,y,z=v;return [x*math.cos(yaw)+z*math.sin(yaw),y*height,-x*math.sin(yaw)+z*math.cos(yaw)]
    def follow(off,fov=65,focus='subject',look=(0,.3,0)):return dict(focus=focus,offset=offset(off),fov=fov,lookOffset=list(look))
    views={
      'input':follow([9,4,6],62,'input-cart-1',(0,1.1,0)),
      'dehacking':follow([6,3.5,5],62),
      'transport':follow([2.7,2.7,-4.8],65),
      'profile':dict(look=[21.5,1.65,(next(t for t in tracks if t['kind']=='raise-six-rows-each-side')['from'][2]+lane)/2-1.7],offset=[6.2,1.2,-.5+(index-5)*.06],fov=54),
      'brick':follow([1.8,2.0,-3.6],65),
      'inspection':dict(look=[26.52,1.7,lane],offset=offset([.8,2,-3.4]),fov=65),
      'layer':follow([3.5,3,-4.3],64),
      'stacking':follow([7,4,-6],64,p['wood'],(0,.7,0)),
      'bridge':follow([5.5,3,3.5],67),
      'inventory':follow([6,3.5,-5],67),
      'amr':follow([-4.5,3.0,3.5],70),
      'loading':follow([5,3,4.5],70),
      'truck':follow([10,5,-10],72,p['order'],(0,.8,0)),
      'reveal':dict(look=[44,.5,8],offset=offset([90,75,78]),fov=67,orbitStart=outro+12,orbitDuration=36,orbitTurns=1 if index%2 else -1),
    }
    # Keep the first four elevated views as comparison baselines. Lower pending
    # variants reveal the real layer beneath the opaque gripping plate.
    dehacking_variants={
      5:([4.7,1.0,4.0],58,.02),6:([5.0,.9,3.5],60,.02),
      7:([5.4,1.6,5.4],62,.10),8:([3.8,1.2,5.0],60,.05),
      9:([7.0,2.3,6.7],65,.15),10:([6.2,1.7,5.5],63,.10),
    }
    if index in dehacking_variants:
        off,fov,look_y=dehacking_variants[index]
        views['dehacking']=follow(off,fov,look=(0,look_y,0))
    def at(t):return clock.at(t)
    cues=[(0,'input',0),(at(event('lift-36-top-layers')-9),'dehacking',5),
      (at(event('place-on-loading-belts',True)+1),'transport',5),
      (at(row-10),'profile',5),(at(place+8),'brick',4),
      (at(scan-6),'inspection',4),(at(scan+4),'brick',4),
      (at(event('layer-buffer-zone-one')-2),'layer',4),
      (at(event('place-guided-layer',True)+1),'stacking',5),
      (at(event('lift-supported-output-pallet')-2),'bridge',5),
      (at(p['storedAt']+1),'inventory',5),
      (at(event('amr-lift-pallet')-3),'amr',5),
      (at(event('amr-raise-forks-to-trailer')-4),'loading',5),
      (at(event('truck-order-departure')-2),'truck',6),(outro-2,'reveal',12)]
    cues.sort()
    for i in range(1,len(cues)):
        prev=cues[i-1];assert cues[i][0]>=prev[0]+prev[2]-1e-5,(index,prev,cues[i])
    history=lambda t:next((h for h in reversed(facts['history']) if h['t']<=t),facts['history'][0])
    stock_start=sum(history(start)['stock']);assert stock_start>0
    franka=dict(start=at(row)-5.7,fadeIn=at(row)-2,fadeOut=at(place+4)+1.5,end=at(place+4)+3.5,clipSeconds=12.8,layout='right-compact')
    detection=dict(start=at(scan)-.5,fadeIn=at(scan)-.5,fadeOut=at(scan)-.5+10.633333,end=at(scan)-.5+12.233333,clipSeconds=10.633333,layout='top-left')
    # Every classifier frame occurs during a strictly advancing 1x source interval.
    for s in clock.segments:
        if s['videoStart']<detection['end'] and s['videoStart']+s['duration']>detection['start']:assert s['rateStart']==s['rateEnd']==1
    return dict(schema='brickflow.final37-night-tour.v1',referenceSha256=facts['referenceSha256'],ownerDeclaredFinal=True,backend='native-cpp-source-event-replay',independentNativePlanner=False,
      name=f'Tour {index:02}',number=index,subject=str(candidate['id']),pallet=p['wood'],truck=p['order'],cart=1,laneZ=[l['z'] for l in facts['lanes']],
      sourceStart=start,sourceEnd=clock.native,seconds=clock.video,frames=math.ceil(clock.video*30),fps=30,width=3840,height=2160,
      stockPalletsAtStart=stock_start,outroAdditionalInspected=history(clock.native)['inspected']-history(p['shippedAt'])['inspected'],clock=clock.segments,views=views,
      cues=[dict(at=t,view=n,blend=b) for t,n,b in cues],overlays=dict(franka=franka,detection=detection),
      evidence='Authoritative source trajectory playback. Real overlays are editorial comparisons, not synchronized physical validation.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--facts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    f=json.loads(a.facts.read_text());manifest=[]
    for i in range(1,11):
        t=make(f,i);path=a.output/f'tour-{i:02}.json';path.write_text(json.dumps(t,indent=2)+'\n');manifest.append({k:t[k] for k in ['number','name','seconds','frames','subject','stockPalletsAtStart','outroAdditionalInspected']})
    (a.output/'manifest.json').write_text(json.dumps(dict(referenceSha256=f['referenceSha256'],tours=manifest),indent=2)+'\n');print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()

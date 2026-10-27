"""Offline verification only: film subjects must retain their frozen native/JS poses."""
import argparse,bisect,csv,json,math
from pathlib import Path

def pose(record,time):
    tracks=record['tracks']; i=bisect.bisect_right([s['t0'] for s in tracks],time)-1
    if i<0:return record['initial']
    s=tracks[i];u=max(0,min(1,(time-s['t0'])/(s['t1']-s['t0'])))
    if not s.get('linear'):u=u*u*(3-2*u)
    if 'path' in s:
        points=s['path'];lengths=[math.dist(a,b) for a,b in zip(points,points[1:])];q=sum(lengths)*u
        for a,b,d in zip(points,points[1:],lengths):
            if q<=d:return [a[j]+(b[j]-a[j])*q/d for j in range(3)]
            q-=d
        return points[-1]
    if 'rigid' in s:
        r=s['rigid'];a,b,v=r['from'],r['to'],r['local'];yaw=a[3]+(b[3]-a[3])*u;c=math.cos(yaw);sn=math.sin(yaw)
        return [a[0]+(b[0]-a[0])*u+c*v[0]+sn*v[2],a[1]+(b[1]-a[1])*u+v[1],a[2]+(b[2]-a[2])*u-sn*v[0]+c*v[2]]
    return [a+(b-a)*u for a,b in zip(s['a'],s['b'])]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('--reference',type=Path,default=Path('artifacts/unreal_film/selected-reference.json'));ap.add_argument('--complete',action='store_true');args=ap.parse_args()
    plan=json.loads((args.directory/'edit-plan.json').read_text());reference=json.loads(args.reference.read_text());records={str(reference[k]['id']):reference[k] for k in ['accepted','rejected']}
    rows=list(csv.DictReader((args.directory/'trace.csv').open(encoding='utf-8-sig')));worst=0;previous=-1
    for r in rows:
        frame=int(r['frame']);assert frame>previous;previous=frame;s=plan['shots'][int(r['shot'])]
        assert s['firstFrame']<=frame<s['firstFrame']+s['frames'];t=float(r['nativeSeconds']);expected=s['nativeStart']+(0 if s['freeze'] else (frame-s['firstFrame'])/plan['fps'])
        assert abs(t-expected)<1e-8,'Film retimed native motion'
        p=pose(records[r['subject']],t);error=max(abs(float(r['brick'+axis])-p[i]) for i,axis in enumerate('XYZ'));worst=max(worst,error)
        assert error<1e-7,(frame,r['subject'],error)
    assert any(s['camera']=='sensor' and s['freeze'] for s in plan['shots']);assert any(s['camera']=='row-hold' and s['freeze'] for s in plan['shots'])
    if args.complete:
        assert len(rows)==plan['frames'] and previous==plan['frames']-1
        orbit=[r for r in rows if plan['shots'][int(r['shot'])]['camera']=='orbit']
        angles=[math.atan2(float(r['cameraY']),float(r['cameraX'])-2600) for r in orbit]
        turn=sum((b-a+math.pi)%(2*math.pi)-math.pi for a,b in zip(angles,angles[1:]))
        assert abs(turn-2*math.pi)<1e-6,'Incomplete camera orbit'
        for view in ('row-hold','sensor'):
            hold=[r for r in rows if plan['shots'][int(r['shot'])]['camera']==view]
            assert max(float(r['nativeSeconds']) for r in hold)-min(float(r['nativeSeconds']) for r in hold)<1e-9
            assert math.dist([float(hold[0]['camera'+a]) for a in 'XYZ'],[float(hold[-1]['camera'+a]) for a in 'XYZ'])>1

    result={'verified':True,'framesChecked':len(rows),'maximumPoseErrorMetres':worst,'nativeMotionSpeed':1,'complete':args.complete,'limitation':'Numerical agreement with synthetic reference; not physical validation.'}
    (args.directory/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()

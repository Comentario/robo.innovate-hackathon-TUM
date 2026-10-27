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

def phase_time(s,local,fps):
    if 'rateStart' not in s:return s['nativeStart']+(0 if s['freeze'] else local)
    d=s['frames']/fps;u=max(0,min(1,local/d));a,b=s['rateStart'],s['rateEnd']
    return s['nativeStart']+d*(a*u+(b-a)*(u**3-.5*u**4))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('--reference',type=Path,default=Path('artifacts/unreal_film/selected-reference.json'));ap.add_argument('--complete',action='store_true');args=ap.parse_args()
    plan=json.loads((args.directory/'edit-plan.json').read_text());reference=json.loads(args.reference.read_text());records={str(reference[k]['id']):reference[k] for k in ['accepted','rejected']}
    rows=list(csv.DictReader((args.directory/'trace.csv').open(encoding='utf-8-sig')));worst=0;previous=-1
    for r in rows:
        frame=int(r['frame']);assert frame>previous;previous=frame;s=plan['shots'][int(r['shot'])]
        assert s['firstFrame']<=frame<s['firstFrame']+s['frames'];t=float(r['nativeSeconds']);expected=phase_time(s,(frame-s['firstFrame'])/plan['fps'],plan['fps'])
        assert abs(t-expected)<1e-8,'Film retimed native motion'
        p=pose(records[r['subject']],t);error=max(abs(float(r['brick'+axis])-p[i]) for i,axis in enumerate('XYZ'));worst=max(worst,error)
        assert error<1e-7,(frame,r['subject'],error)
    assert any(s['camera']=='sensor' and s['freeze'] for s in plan['shots']);assert any(s['camera']=='row-hold' and s['freeze'] for s in plan['shots'])
    continuous=plan.get('schema')=='brickflow.continuous-film.v2'
    if args.complete:
        assert len(rows)==plan['frames'] and previous==plan['frames']-1
        if continuous:
            assert abs(float(rows[0]['nativeSeconds']))<1e-12
            for a,b in zip(plan['shots'],plan['shots'][1:]):
                assert abs(phase_time(a,a['frames']/plan['fps'],plan['fps'])-b['nativeStart'])<1e-8,'Clock skip between phases'
                assert abs(a['rateEnd']-b['rateStart'])<1e-9,'Instantaneous playback speed change'
            for a,b in zip(rows,rows[1:]):
                dt=float(b['nativeSeconds'])-float(a['nativeSeconds']);assert -.0000001<=dt<=40/plan['fps']+1e-7,'Native clock jump'
                assert math.dist([float(a['camera'+q]) for q in 'XYZ'],[float(b['camera'+q]) for q in 'XYZ'])<150,'Camera position jump'
                va=[float(a['look'+q])-float(a['camera'+q]) for q in 'XYZ'];vb=[float(b['look'+q])-float(b['camera'+q]) for q in 'XYZ']
                dot=sum(x*y for x,y in zip(va,vb))/(math.hypot(*va)*math.hypot(*vb))
                assert math.degrees(math.acos(max(-1,min(1,dot))))<2,'Camera direction jump'
                assert abs(float(a['fov'])-float(b['fov']))<.3,'Lens jump'
            accepted=reference['accepted'];event=lambda name:next(t for t in accepted['tracks'] if t['kind']==name)
            row0,row1=event('raise-six-rows-each-side')['t0'],event('place-six-rows-on-v1')['t1']
            profile=[r for r in rows if row0<=float(r['nativeSeconds'])<=row1]
            assert len(profile)>180
            origin=[float(profile[0]['camera'+q]) for q in 'XYZ']
            for r in profile:
                assert math.dist(origin,[float(r['camera'+q]) for q in 'XYZ'])<1e-5,'Profile camera moved during physical comparison'
                assert abs(float(r['fov'])-55)<1e-6
            bridge0,bridge1=event('finished-pallet-outfeed')['t0'],event('lower-pallet-on-transport-cart')['t1']
            assert all(abs(float(r['speed'])-1)<1e-7 for r in rows if bridge0<=float(r['nativeSeconds'])<=bridge1),'Bridge is not at real speed'
            hold=lambda view:[r for r in rows if plan['shots'][int(r['shot'])]['camera']==view]
            for view in ('row-hold','sensor'):
                h=hold(view);assert max(float(r['nativeSeconds']) for r in h)-min(float(r['nativeSeconds']) for r in h)<1e-9
            reveal=next(c['atSeconds'] for c in plan['cameraCues'] if c['view']=='reveal')
            orbit=[r for r in rows if int(r['frame'])/plan['fps']>=reveal+16]
            angles=[math.atan2(float(r['cameraY']),float(r['cameraX'])-2600) for r in orbit]
            turn=sum((b-a+math.pi)%(2*math.pi)-math.pi for a,b in zip(angles,angles[1:]));assert abs(turn-2*math.pi)<1e-5
            assert int(rows[-1]['inspected'])-int(rows[round(reveal*plan['fps'])]['inspected'])>=2000
        else:
            orbit=[r for r in rows if plan['shots'][int(r['shot'])]['camera']=='orbit']
            angles=[math.atan2(float(r['cameraY']),float(r['cameraX'])-2600) for r in orbit]
            turn=sum((b-a+math.pi)%(2*math.pi)-math.pi for a,b in zip(angles,angles[1:]));assert abs(turn-2*math.pi)<1e-6
            for view in ('row-hold','sensor'):
                h=[r for r in rows if plan['shots'][int(r['shot'])]['camera']==view]
                assert max(float(r['nativeSeconds']) for r in h)-min(float(r['nativeSeconds']) for r in h)<1e-9
                assert math.dist([float(h[0]['camera'+a]) for a in 'XYZ'],[float(h[-1]['camera'+a]) for a in 'XYZ'])>1

    result={'verified':True,'framesChecked':len(rows),'maximumPoseErrorMetres':worst,'playback':('continuous smooth ramps up to 40x' if continuous else '1x shots with documented idle cuts'),'cameraAuditOnly':plan.get('cameraAuditOnly',False),'complete':args.complete,'limitation':'Numerical agreement with synthetic reference; not physical validation.'}
    (args.directory/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()

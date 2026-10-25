"""Sampled material-envelope audit; excludes tools and contact dynamics."""
from bisect import bisect_right
from itertools import product
import math
from .motion import fraction


def pose(m,identity,t,index=None):
    seq=m['tracks'].get(identity,[])
    starts=index[identity] if index is not None else [x['t0'] for x in seq]
    k=bisect_right(starts,t)-1
    if k<0:return m['initial'][identity]
    s=seq[k];u=max(0,min(1,(t-s['t0'])/(s['t1']-s['t0'])))
    if s.get('motion'):u=fraction(t-s['t0'],s['motion'])
    return [a+(b-a)*u for a,b in zip(s['from'],s['to'])]


def sampled_material_clearance(report,samples=24):
    m=report['mechanics'];L,H,D=m['brick_m'];half=[L/2,H/2,D/2];size=[.30,.08,.08]
    ids=[b['id'] for b in report['material']];index={i:[s['t0'] for s in m['tracks'].get(i,[])] for i in ids}
    times=[report['simulated_seconds']*k/samples for k in range(samples+1)]
    times.extend(e['t']+.01 for e in report['events'] if e['kind'] in ('recovery_start','alignment_check'))
    hits=[]
    for t in times:
        occupied={};positions={};tested=set()
        for identity in ids:
            p=pose(m,identity,t,index);positions[identity]=p
            seq=m['tracks'].get(identity,[]);k=bisect_right(index[identity],t)-1
            if k>=0 and seq[k]['label'] in ('Contained collection; settling abstracted','Contained discard cart collection; settling abstracted','Contained disposal area unloading; settling abstracted'):continue
            cells=[range(math.floor((p[a]-half[a]) /size[a]),math.floor((p[a]+half[a])/size[a])+1) for a in range(3)]
            for key in product(*cells):
                for other in occupied.get(key,[]):
                    pair=(identity,other)
                    if pair in tested:continue
                    tested.add(pair);q=positions[other]
                    if all(abs(p[a]-q[a])<2*half[a]-1e-5 for a in range(3)):
                        hits.append({'t':t,'a':identity,'b':other,'p':p,'q':q})
                        if len(hits)>=12:return {'passed':False,'sampled_frames':len(times),'collisions':hits,'scope':'Sampled axis-aligned brick envelopes; no tools, cables or contact dynamics'}
                occupied.setdefault(key,[]).append(identity)
    return {'passed':not hits,'sampled_frames':len(times),'collisions':hits,'scope':'Sampled axis-aligned brick envelopes; not a continuous collision proof; excludes tools/cables/dynamics and internal enclosed-bin settling'}

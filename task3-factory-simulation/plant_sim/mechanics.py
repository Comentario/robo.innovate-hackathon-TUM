"""Export the exact automation recipe executed by SimPy, without rescheduling."""
from collections import defaultdict
from copy import deepcopy
import math
from .automation import BED, INPUT_DECK, OUTPUT_DECK, LAYOUT, HOMES


def lerp(a,b,t):return [x+(y-x)*t for x,y in zip(a,b)]


def position_at(track,initial,t):
    value=initial
    for segment in track:
        if t<segment['t0']:break
        points=segment['points']
        if t>=segment['t1']:value=points[-1][1:];continue
        f=(t-segment['t0'])/(segment['t1']-segment['t0'])
        for a,b in zip(points,points[1:]):
            if f<=b[0]+1e-10:
                u=max(0,min(1,(f-a[0])/(b[0]-a[0])))
                if segment.get('interpolation')!='linear':u=u*u*(3-2*u)
                return lerp(a[1:],b[1:],u)
    return value


def compile_mechanics(report):
    g=report['config']['geometry'];w,d,h=[v/1000 for v in g['brick_mm']]
    aux_ids=set(report['automation']['auxiliary_ids'])
    initial=report['automation']['initial_positions'];tracks=defaultdict(list);tools=defaultdict(list);observations=[]
    for e in report['events']:
        if e['kind']=='inspection':observations.append({k:e[k] for k in ('t','pair','lane','ids','rejected')})
        if e['kind']!='operation_start':continue
        for identity,seq in e['motion_plan']['brick_tracks'].items():
            for m in seq:
                tracks[identity].append({'t0':round(e['t']+m['start_s'],6),
                    't1':round(e['t']+m['start_s']+m['duration_s'],6),
                    'points':m['points'],'kind':m['kind'],'owner':m['owner'],
                    'interpolation':m['interpolation'],'station':e['station']})
        for tool,seq in e['motion_plan']['tool_tracks'].items():
            for m in seq:
                tools[tool].append({'t0':round(e['t']+m['start_s'],6),
                    't1':round(e['t']+m['start_s']+m['duration_s'],6),
                    'points':m['points'],'kind':m['kind'],'brick_ids':m['brick_ids'],
                    'attach':[e['t']+v for v in m['attach_s']],'interpolation':'linear'})
    stations={k:LAYOUT[k] for k in ('dock','dehacker','separator','pairer','stacker')}
    stations.update({'infeed':LAYOUT['infeed_end'],'outfeed':LAYOUT['outfeed_end'],
                     'lane_1':[13,BED,-2],'lane_2':[13,BED,2]})
    return {'schema_version':'1.1','units':'meters','up_axis':'Y','bed_height':BED,
        'pallet_deck':OUTPUT_DECK,'input_pallet_deck':INPUT_DECK,'brick_dimensions_m':[w,h,d],
        'layout':LAYOUT,'tool_homes':{**HOMES,**{f'robot_{i}':[15.5,2.7,0] for i in range(1,report['config']['correction_robots']+1)}},
        'stations':stations,'initial_positions':{i:p for i,p in initial.items() if i not in aux_ids},
        'tracks':{i:s for i,s in tracks.items() if i not in aux_ids},'tools':dict(tools),
        'auxiliaries':{'initial_positions':{i:initial[i] for i in aux_ids},'tracks':{i:tracks[i] for i in aux_ids}},
        'observations':observations,'stop_time':report['simulated_seconds'],
        'scope':'Automation sequence + geometry-derived virtual positions and constant-speed kinematics. No dynamics/contact solver.'}


def validate_mechanics(m):
    count=0
    for initial,tracks in [(m['initial_positions'],m['tracks']),(m['auxiliaries']['initial_positions'],m['auxiliaries']['tracks'])]:
        for identity,seq in tracks.items():
            p=initial[identity];end=0
            for s in seq:
                assert s['t0']>=end-2e-6,(identity,'double booking')
                assert s['t1']>s['t0']
                points=s['points'];assert points[0][0]==0 and points[-1][0]==1
                assert all(a[0]<b[0] for a,b in zip(points,points[1:]))
                assert all(math.isfinite(v) for p in points for v in p)
                assert max(abs(a-b) for a,b in zip(p,points[0][1:]))<1e-6,(identity,'jump')
                p=points[-1][1:];end=s['t1'];count+=1
    for tool,seq in m['tools'].items():
        for a,b in zip(seq,seq[1:]):
            assert a['t1']<=b['t0']+2e-6,(tool,'double booking')
            assert max(abs(x-y) for x,y in zip(a['points'][-1][1:],b['points'][0][1:]))<1e-6
    return {'continuous_brick_tracks':True,'exclusive_tool_ownership':True,
            'brick_identities':len(m['initial_positions']),'auxiliary_identities':len(m['auxiliaries']['initial_positions']),
            'motion_segments':count}

"""Continuous kinematic tracks derived from SimPy operations (not contact physics).

Positions are meters, Y up. Each physical brick has one render identity. No
inspection decisions are inferred by this module, nor is the process rescheduled.
"""
from collections import defaultdict
import math


BED = 0.90
DECK = 0.15
OUTPUT_DECK = 0.21
STATIONS = {
    'dock': [-3, 0, 0], 'dehacker': [0, 0, 0], 'infeed': [2, BED, 0],
    'separator': [5, BED, 0], 'lane_1': [9, BED, -2], 'lane_2': [9, BED, 2],
    'pairer': [14, BED, 0], 'outfeed': [16, BED, 0], 'stacker': [19.5, 0, 0],
}


def lerp(a, b, t):
    return [x+(y-x)*t for x,y in zip(a,b)]


def position_at(track, initial, t):
    value = initial
    for segment in track:
        if t < segment['t0']:
            break
        points = segment['points']
        if t >= segment['t1']:
            value = points[-1][1:]
            continue
        f = (t-segment['t0'])/(segment['t1']-segment['t0'])
        for a,b in zip(points,points[1:]):
            if f <= b[0]:
                u = (f-a[0])/(b[0]-a[0])
                u = u*u*(3-2*u)  # rest-to-rest interpolation; continuous positions
                return lerp(a[1:],b[1:],u)
    return value


def compile_mechanics(report):
    c = report['config']
    g = c['geometry']
    w,d,h = [x/1000 for x in g['brick_mm']]
    rows,cols = g['rows'],g['columns']
    n=rows*cols
    per_stack=g['input_layers']//2
    materials=report['material']
    layer_ids=defaultdict(lambda: [[],[]])
    initial={}
    tracks=defaultdict(list)
    tools=defaultdict(list)
    observations=[]
    stock_count=defaultdict(int)
    removed_count=defaultdict(int)
    output_pairs=0
    completed_pallets=0

    def slots(x,y,z):
        return [[x+(r-(rows-1)/2)*d,y,z+(col-(cols-1)/2)*w]
                for r in range(rows) for col in range(cols)]

    for b in materials:
        if b['origin']=='input':
            _,pid,lane,slot=b['id'].split('-')
            pid,lane,slot=int(pid),int(lane),int(slot)
            stack=(pid-1)//per_stack
            pair_in_stack=(pid-1)%per_stack
            yy=DECK+(g['input_layers']-2*pair_in_stack-lane-.5)*h
            initial[b['id']]=slots(-3,yy,stack*(cols*w+.8))[slot]
            layer_ids[pid][lane].append(b['id'])
        else:
            shade_index=c['shades'].index(b['shade'])
            j=stock_count[b['shade']];stock_count[b['shade']]+=1
            level=j//n;slot=j%n
            initial[b['id']]=slots(8.5+shade_index*.65,BED+(level+.5)*h,5)[slot]

    def append(identity,t0,t1,points,kind,owner=None):
        if t1<=t0:
            raise ValueError('Mechanical motion must have positive duration')
        seq=tracks[identity]
        start=position_at(seq,initial[identity],t0)
        if seq and seq[-1]['t1']>t0+1e-6:
            raise ValueError(f'Overlapping motion for {identity}')
        if max(abs(a-b) for a,b in zip(start,points[0][1:]))>1e-6:
            raise ValueError(f'Discontinuous motion for {identity}')
        seq.append({'t0':t0,'t1':t1,'points':points,'kind':kind,'owner':owner})

    def transfer(ids,targets,t0,duration,kind,tool=None):
        if not ids:return
        starts=[position_at(tracks[i],initial[i],t0) for i in ids]
        source=[sum(p[k] for p in starts)/len(starts) for k in (0,1,2)]
        dest=[sum(p[k] for p in targets)/len(targets) for k in (0,1,2)]
        if tool:
            top0=max(p[1] for p in starts)+h/2
            top1=max(p[1] for p in targets)+h/2
            clearance=max(2.25,top0+.25,top1+.25)
            # Brick and tool coincide during the 0.15..0.85 carry interval.
            for i,a,b in zip(ids,starts,targets):
                pa=[a[0],clearance+(a[1]-top0),a[2]]
                pb=[b[0],clearance+(b[1]-top1),b[2]]
                append(i,t0,t0+duration,[[0,*a],[.15,*a],[.35,*pa],[.65,*pb],[.85,*b],[1,*b]],kind,tool)
            home={'dehacker':[0,2.7,0],'separator':[5,2.7,0],
                  'pairer':[14,2.7,0],'stacker':[17,2.7,0]}.get(tool,[9.5,2.7,0])
            a=[source[0],top0,source[2]];b=[dest[0],top1,dest[2]]
            seq=tools[tool]
            # Every cycle begins/ends at the same clear home pose.
            seq.append({'t0':t0,'t1':t0+duration,'kind':kind,'brick_ids':list(ids),
                        'attach':[t0+.15*duration,t0+.85*duration],
                        'points':[[0,*home],[.15,*a],[.35,a[0],clearance,a[2]],
                                  [.65,b[0],clearance,b[2]],[.85,*b],[.95,b[0],clearance,b[2]],[1,*home]]})
        else:
            for i,a,b in zip(ids,starts,targets):
                append(i,t0,t0+duration,[[0,*a],[1,*b]],kind)

    def layer_target(pid,lane,x,y,z):
        return slots(x,y,z)

    for e in report['events']:
        t=e['t'];pid=e.get('pair')
        if e['kind']=='inspection':
            observations.append({'t':t,'pair':pid,'lane':e['lane'],'ids':e['ids'],'rejected':e['rejected']})
        if e['kind']=='brick_replaced':
            layer_ids[pid][e['lane']][e['slot']]=e['brick']
        if e['kind']=='pair_completed':
            output_pairs+=1
        if e['kind']=='pallet_completed':
            completed_pallets+=1
        if e['kind']!='operation_start':continue
        s=e['station'];duration=e['duration'];phase=e['phase']
        if s=='dock':
            first=(pid-1)//per_stack*per_stack+1
            ids=[i for p in range(first,first+per_stack) for l in layer_ids[p] for i in l]
            target=[]
            for i in ids:
                p=initial[i];target.append([p[0]+3,p[1],p[2]-((pid-1)//per_stack)*(cols*w+.8)])
            transfer(ids,target,t,duration,'Input stack transfer')
        elif s=='dehacker':
            ids=layer_ids[pid][0]+layer_ids[pid][1]
            target=slots(1.8,BED+1.5*h,0)+slots(1.8,BED+.5*h,0)
            transfer(ids,target,t,duration,'Two-layer dehacking','dehacker')
        elif s=='infeed':
            # Three parking nests: finite buffer plus the upstream held unit.
            nest=(pid-1)%(c['buffer_pairs']+1)
            z=(nest-(c['buffer_pairs']/2))*(cols*w+.3)
            ids=layer_ids[pid][0]+layer_ids[pid][1]
            transfer(ids,slots(3.3,BED+1.5*h,z)+slots(3.3,BED+.5*h,z),t,duration,'Infeed shuttle')
        elif s=='separator':
            # Explicit approach from parking nest; then one supported layer per lift.
            ids=layer_ids[pid][0]+layer_ids[pid][1]
            transfer(ids,slots(5,BED+1.5*h,0)+slots(5,BED+.5*h,0),t,duration*.25,'Separator loading')
            for lane in (0,1):
                start=t+duration*(.25+.375*lane)
                transfer(layer_ids[pid][lane],slots(9,BED+.5*h,-2 if lane==0 else 2),start,duration*.375,'Separate single layer','separator')
        elif s in ('lane_1','lane_2') and phase=='Transfer corrected layer':
            lane=0 if s=='lane_1' else 1
            nest=(pid-1)%c['inflight_pairs']
            transfer(layer_ids[pid][lane],slots(11.3+nest*.5,BED+.5*h,-2 if lane==0 else 2),t,duration,'Corrected-layer conveyor')
        elif s.startswith('robot_'):
            lane=e['lane'];slot=e['slot'];identity=e['brick']
            if e['destination']=='layer':
                target=[slots(9,BED+.5*h,-2 if lane==0 else 2)[slot]]
            else:
                destination=e['destination'];index=removed_count[destination];removed_count[destination]+=1
                binx=12 if destination=='reject' else 13.4
                target=[slots(binx,BED+(index//n+.5)*h,5)[index%n]]
            transfer([identity],target,t,duration,phase,s)
        elif s=='pairer':
            # Lower layer is placed first; upper is deposited onto it.
            for order,lane in enumerate((1,0)):
                transfer(layer_ids[pid][lane],slots(14,BED+(.5 if lane==1 else 1.5)*h,0),
                         t+duration*order/2,duration/2,'Pair corrected layers','pairer')
        elif s=='outfeed':
            transfer(layer_ids[pid][0]+layer_ids[pid][1],slots(17,BED+1.5*h,0)+slots(17,BED+.5*h,0),t,duration,'Output conveyor')
        elif s=='stacker' and phase=='Restack two-layer unit':
            layer_base=(output_pairs%(g['output_layers']//2))*2
            target=slots(19.5,OUTPUT_DECK+(layer_base+1.5)*h,0)+slots(19.5,OUTPUT_DECK+(layer_base+.5)*h,0)
            transfer(layer_ids[pid][0]+layer_ids[pid][1],target,t,duration,'Restack two-layer unit','stacker')
        elif s=='stacker' and phase=='Exchange output pallet':
            ids=report['pallets'][completed_pallets-1]
            endx=22+(completed_pallets-1)*.65
            target=[]
            for i in ids:
                p=position_at(tracks[i],initial[i],t);target.append([p[0]+endx-19.5,p[1],p[2]])
            transfer(ids,target,t,duration/2,'Full pallet discharge')

    # Open operations freeze when the process stops; never finish a failed movement visually.
    stop=report['simulated_seconds']
    return {'schema_version':'1.0','units':'meters','up_axis':'Y','bed_height':BED,'pallet_deck':OUTPUT_DECK,'input_pallet_deck':DECK,
            'brick_dimensions_m':[w,h,d],'stations':STATIONS,'initial_positions':initial,
            'tracks':dict(tracks),'tools':dict(tools),'observations':observations,'stop_time':stop,
            'scope':'Continuous kinematics and process interlocks. No rigid-body contact, friction, load or collision validation.'}


def validate_mechanics(mechanics):
    """Return independently checkable continuity/ownership audit statistics."""
    segments=0
    for identity,seq in mechanics['tracks'].items():
        last_position=mechanics['initial_positions'][identity];last_end=0
        for segment in seq:
            assert segment['t0']>=last_end-1e-6
            assert segment['t1']>segment['t0']
            points=segment['points']
            assert points[0][0]==0 and points[-1][0]==1
            assert all(a[0]<b[0] for a,b in zip(points,points[1:]))
            assert all(math.isfinite(v) for p in points for v in p)
            assert max(abs(a-b) for a,b in zip(last_position,points[0][1:]))<1e-6
            last_position=points[-1][1:];last_end=segment['t1'];segments+=1
    for tool,seq in mechanics['tools'].items():
        for a,b in zip(seq,seq[1:]):
            assert a['t1']<=b['t0']+1e-6, f'Tool {tool} double booked'
            assert max(abs(x-y) for x,y in zip(a['points'][-1][1:],b['points'][0][1:]))<1e-6
    return {'continuous_brick_tracks':True,'exclusive_tool_ownership':True,
            'brick_identities':len(mechanics['initial_positions']),'motion_segments':segments}

"""Deterministic automation recipes: distance/speed + explicit dwell, no dynamics.

The same planned substeps determine SimPy time, virtual limit confirmations and
3D tracks. A stroke is ideal constant-speed motion with rest intervals; no mass,
friction or acceleration is inferred. Speeds are unmeasured engineering inputs.
"""
from collections import defaultdict
import math

BED=.90
INPUT_DECK=.15
OUTPUT_DECK=.21
LAYOUT={
 'dock':[-3,0,0], 'dehacker':[0,0,0], 'infeed_start':[1.8,BED,0],
 'infeed_end':[7.3,BED,0], 'separator':[9,BED,0],
 'lane_entry_x':12.0, 'inspection_x':13.0, 'correction_x':14.4,
 'join_start_x':16.3, 'pairer':[19.5,BED,0], 'outfeed_end':[22.5,BED,0],
 'stacker':[25,0,0], 'discharge_x':27.5, 'lane_z':[-2,2],
 'supply_x':14.0, 'supply_z':5.0, 'reject_x':13.2, 'reuse_x':14.0, 'reuse_z':-5.0,
}
HOMES={'dehacker':[0,2.7,0], 'separator':[9,2.7,0],
       'pairer':[19.5,2.7,0], 'stacker':[22.5,2.7,0]}


def validate_automation(c):
    a=c['automation']
    expected={'infeed_m_s','transfer_m_s','gantry_xy_m_s','gantry_z_m_s',
              'robot_xy_m_s','robot_z_m_s','dock_m_s','pallet_m_s',
              'clamp_s','release_s','settle_s','exposure_s','inference_s','clearance_m'}
    if set(a)!=expected:raise ValueError('automation must specify all documented engineering inputs')
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in a.values()):
        raise ValueError('All automation speeds, distances and dwell times must be positive and finite')
    if a['clearance_m']>=2.65:raise ValueError('Carry clearance must stay below the 2.7 m home plane')


class AutomationPlanner:
    def __init__(self,c,bricks):
        validate_automation(c)
        self.c=c;self.a=c['automation'];g=c['geometry']
        self.w,self.d,self.h=[v/1000 for v in g['brick_mm']]
        self.rows,self.cols=g['rows'],g['columns'];self.n=self.rows*self.cols
        self.positions={};self.initial={};self.removed=defaultdict(int)
        self.stack_ids=defaultdict(list);counts=defaultdict(int)
        self.output_ids=[];self.finished_pallets=[]
        self.auxiliary_ids=[]
        for b in bricks.values():
            if b.origin=='input':
                _,pid,lane,slot=b.id.split('-');pid,lane,slot=int(pid),int(lane),int(slot)
                per=g['input_layers']//2;stack=(pid-1)//per;k=(pid-1)%per
                y=INPUT_DECK+(g['input_layers']-2*k-lane-.5)*self.h
                p=self.slots(-3,y,stack*(self.cols*self.w+.8))[slot]
                self.stack_ids[stack].append(b.id)
            else:
                j=counts[b.shade];counts[b.shade]+=1
                p=self.slots(LAYOUT['supply_x']+c['shades'].index(b.shade)*.65,
                             BED+(j//self.n+.5)*self.h,5)[j%self.n]
            self.positions[b.id]=p;self.initial[b.id]=p[:]

        for stack in range(c['input_stacks']):
            identity=f'P-IN-{stack}';p=[-3,.08,stack*(self.cols*self.w+.8)]
            self.auxiliary_ids.append(identity);self.initial[identity]=p[:];self.positions[identity]=p[:]
        pallet_count=math.ceil(c['input_stacks']*g['input_layers']/g['output_layers'])+1
        for index in range(pallet_count):
            identity=f'P-OUT-{index}';p=[25,.14,0 if index==0 else -3.5-(index-1)*3]
            self.auxiliary_ids.append(identity);self.initial[identity]=p[:];self.positions[identity]=p[:]

    def slots(self,x,y,z):
        return [[x+(r-(self.rows-1)/2)*self.d,y,z+(col-(self.cols-1)/2)*self.w]
                for r in range(self.rows) for col in range(self.cols)]

    def plan(self,station,phase,pair,context):
        a=self.a;pid=pair['id'];layers=[[b.id for b in l] for l in pair['layers']]
        all_ids=layers[0]+layers[1]
        steps=[];tracks=defaultdict(list);tools=defaultdict(list);offset=0.0

        def step(label,dt,kind='dwell',distance=0.,speed=None,axis=None,sensor=None):
            nonlocal offset
            item={'label':label,'start_s':offset,'duration_s':dt,'kind':kind,
                  'distance_m':distance,'speed_m_s':speed,'axis':axis,'sensor':sensor}
            steps.append(item);offset+=dt
            return dt

        def travel(label,p,q,vxy,vz,sensor):
            # X/Z axes interpolate together; the slowest axis fixes time.
            dx,dz=abs(q[0]-p[0]),abs(q[2]-p[2]);dy=abs(q[1]-p[1])
            dt=max(dx/vxy,dz/vxy,dy/vz)
            if dt<1e-9:return 0.
            axis='Y' if dy>1e-8 and dx+dz<1e-8 else 'X/Z'
            distance=max(dx,dz,dy)
            speed=vz if axis=='Y' else vxy
            step(label,dt,'travel',distance,speed,axis,sensor)
            return dt

        def belt(ids,targets,label,speed):
            starts=[self.positions[i][:] for i in ids]
            dist=max(math.dist(p,q) for p,q in zip(starts,targets)) if ids else 0
            dt=dist/speed
            if dt>1e-9:
                begin=offset;step(label,dt,'travel',dist,speed,'conveyor','position_sensor')
                for i,p,q in zip(ids,starts,targets):
                    tracks[i].append({'start_s':begin,'duration_s':dt,'points':[[0,*p],[1,*q]],'kind':label,'owner':None,'interpolation':'linear'})
                    self.positions[i]=q[:]
            step('Settling / position debounce',a['settle_s'],sensor='position_stable')

        def carry(ids,targets,label,tool):
            nonlocal offset
            begin=offset
            starts=[self.positions[i][:] for i in ids]
            source=[sum(p[k] for p in starts)/len(starts) for k in (0,1,2)]
            dest=[sum(p[k] for p in targets)/len(targets) for k in (0,1,2)]
            top0=max(p[1] for p in starts)+self.h/2;top1=max(p[1] for p in targets)+self.h/2
            clearance=max(a['clearance_m'],top0+.15,top1+.15)
            home=HOMES.get(tool,[15.5,2.7,0])
            xy=a['robot_xy_m_s'] if tool.startswith('robot_') else a['gantry_xy_m_s']
            vz=a['robot_z_m_s'] if tool.startswith('robot_') else a['gantry_z_m_s']
            high0=[source[0],home[1],source[2]];pick=[source[0],top0,source[2]]
            lift0=[source[0],clearance,source[2]];lift1=[dest[0],clearance,dest[2]]
            put=[dest[0],top1,dest[2]];high1=[dest[0],home[1],dest[2]]
            headpoints=[[0,*home]];brickpoints={i:[[0,*p]] for i,p in zip(ids,starts)}
            attached=False
            def add_head(q,label,sensor=None):
                nonlocal attached
                previous=headpoints[-1][1:]
                travel(label,previous,q,xy,vz,sensor)
                rel=offset-begin;headpoints.append([rel,*q])
                for i,p,qend in zip(ids,starts,targets):
                    if attached:
                        b=[q[0]+p[0]-source[0],q[1]+p[1]-top0,q[2]+p[2]-source[2]]
                    else:b=qend if released else p
                    brickpoints[i].append([rel,*b])
            released=False
            add_head(high0,'Traverse above source','above_source')
            add_head(pick,'Lower to source','pick_limit')
            step('Close gripper / confirm clamp',a['clamp_s'],sensor='clamp_closed')
            attach=offset-begin;headpoints.append([attach,*pick])
            for i,p in zip(ids,starts):brickpoints[i].append([attach,*p])
            attached=True
            add_head(lift0,'Lift clear of surrounding material','clearance_limit')
            add_head(lift1,'Traverse with held material','above_destination')
            # Targets preserve within-grip offsets, including paired-layer height.
            add_head(put,'Lower to destination','place_limit')
            step('Open gripper / confirm release',a['release_s'],sensor='grip_open')
            detach=offset-begin;headpoints.append([detach,*put])
            for i,q in zip(ids,targets):brickpoints[i].append([detach,*q])
            attached=False;released=True
            add_head(high1,'Retract vertically','retracted_limit')
            add_head(home,'Return to clear home position','home_limit')
            end=offset-begin
            def normalized(points):
                # Zero-distance substeps may produce duplicate timestamps.
                unique={round(p[0],10):p for p in points}
                points=[unique[k] for k in sorted(unique)]
                return [[p[0]/end,*p[1:]] for p in points]
            for i,q in zip(ids,targets):
                tracks[i].append({'start_s':begin,'duration_s':end,'points':normalized(brickpoints[i]),'kind':label,'owner':tool,'interpolation':'linear'})
                self.positions[i]=q[:]
            tools[tool].append({'start_s':begin,'duration_s':end,'points':normalized(headpoints),
                                'kind':label,'brick_ids':ids,'attach_s':[begin+attach,begin+detach],'interpolation':'linear'})

        if station=='dock':
            stack=(pid-1)//(self.c['geometry']['input_layers']//2)
            if stack:
                old=f'P-IN-{stack-1}'
                belt([old],[[-3,.08,0]],'Retract empty input pallet',a['pallet_m_s'])
                belt([old],[[-3,.08,-4.2]],'Empty input pallet discharge',a['pallet_m_s'])
            ids=self.stack_ids[stack]+[f'P-IN-{stack}'];z=stack*(self.cols*self.w+.8)
            aligned=[[p[0],p[1],p[2]-z] for p in [self.positions[i] for i in ids]]
            belt(ids,aligned,'Dock lateral alignment',a['dock_m_s'])
            targets=[[p[0]+3,p[1],p[2]] for p in [self.positions[i] for i in ids]]
            belt(ids,targets,'Dock forward transfer',a['dock_m_s'])
        elif station=='dehacker':
            carry(all_ids,self.slots(1.8,BED+1.5*self.h,0)+self.slots(1.8,BED+.5*self.h,0),phase,'dehacker')
        elif station=='infeed':
            belt(all_ids,self.slots(7.3,BED+1.5*self.h,0)+self.slots(7.3,BED+.5*self.h,0),'Infeed belt to PE_IN',a['infeed_m_s'])
        elif station=='separator':
            belt(all_ids,self.slots(9,BED+1.5*self.h,0)+self.slots(9,BED+.5*self.h,0),'Load separator to PE_SEP',a['transfer_m_s'])
            for lane in (0,1):carry(layers[lane],self.slots(12,BED+.5*self.h,LAYOUT['lane_z'][lane]),'Separate single layer','separator')
        elif station in ('lane_1','lane_2'):
            lane=0 if station=='lane_1' else 1;z=LAYOUT['lane_z'][lane]
            if phase=='Position layer at inspection sensor':
                belt(layers[lane],self.slots(13,BED+.5*self.h,z),'Conveyor to PE_CAM',a['transfer_m_s'])
            elif phase=='Inspect exposed layer':
                step('Image exposure',a['exposure_s'],sensor='image_ready')
                step('Inspection processing',a['inference_s'],sensor='inspection_ready')
            elif phase=='Position layer at correction sensor':
                belt(layers[lane],self.slots(14.4,BED+.5*self.h,z),'Conveyor to PE_CORR',a['transfer_m_s'])
            else:
                belt(layers[lane],self.slots(16.3+pair['nest']*.5,BED+.5*self.h,z),'Conveyor to reserved join nest',a['transfer_m_s'])
        elif station.startswith('robot_'):
            identity=context['brick'];lane=context['lane'];slot=context['slot']
            if context['destination']=='layer':target=self.slots(14.4,BED+.5*self.h,LAYOUT['lane_z'][lane])[slot]
            else:
                destination=context['destination'];index=self.removed[destination];self.removed[destination]+=1
                target=self.slots(LAYOUT['reject_x'] if destination=='reject' else LAYOUT['reuse_x'],BED+(index//self.n+.5)*self.h,5 if destination=='reject' else LAYOUT['reuse_z'])[index%self.n]
            carry([identity],[target],phase,station)
        elif station=='pairer':
            for lane in (1,0):carry(layers[lane],self.slots(19.5,BED+(.5 if lane==1 else 1.5)*self.h,0),'Pair corrected layers','pairer')
        elif station=='outfeed':
            belt(all_ids,self.slots(22.5,BED+1.5*self.h,0)+self.slots(22.5,BED+.5*self.h,0),'Output belt to PE_OUT',a['transfer_m_s'])
        elif station=='stacker' and phase=='Restack two-layer unit':
            base=(len(self.output_ids)//self.n)%self.c['geometry']['output_layers']
            carry(all_ids,self.slots(25,OUTPUT_DECK+(base+1.5)*self.h,0)+self.slots(25,OUTPUT_DECK+(base+.5)*self.h,0),phase,'stacker')
            self.output_ids.extend(all_ids)
        elif station=='stacker':
            size=self.n*self.c['geometry']['output_layers'];ids=self.output_ids[-size:]
            k=len(self.finished_pallets);self.finished_pallets.append(ids)
            ids=ids+[f'P-OUT-{k}']
            dx=LAYOUT['discharge_x']+k*.65-25
            belt(ids,[[p[0]+dx,p[1],p[2]] for p in [self.positions[i] for i in ids]],'Full pallet discharge',a['pallet_m_s'])
            belt([f'P-OUT-{k+1}'],[[25,.14,0]],'Empty pallet feed',a['pallet_m_s'])
            step('Empty pallet locate / debounce',a['settle_s'],sensor='pallet_located')
        else:raise ValueError(f'No automation recipe for {station} / {phase}')
        return {'duration_s':offset,'steps':steps,'brick_tracks':dict(tracks),'tool_tracks':dict(tools)}


def timing_report(events,elapsed,input_bricks,output_bricks,robots):
    stations=defaultdict(lambda:{'operations':0,'travel_s':0.,'dwell_s':0.,'active_s':0.})
    operations=[];waits=[]
    for e in events:
        if e['kind'] in ('interlock_granted','robot_acquired') and e.get('waited_s',0)>1e-8:
            waits.append({'station':e['station'],'pair':e['pair'],'gate':e.get('gate','robot_available'),'start_s':e['t']-e['waited_s'],'duration_s':e['waited_s']})
        if e['kind']!='operation_start' or 'motion_plan' not in e:continue
        p=e['motion_plan'];s=stations[e['station']];s['operations']+=1
        travel=sum(step['duration_s'] for step in p['steps'] if step['kind']=='travel')
        dwell=p['duration_s']-travel
        executed=max(0,min(p['duration_s'],elapsed-e['t']))
        s['travel_s']+=travel;s['dwell_s']+=dwell;s['active_s']+=executed
        operations.append({'station':e['station'],'pair':e['pair'],'phase':e['phase'],
                           'start_s':e['t'],'duration_s':p['duration_s'],'travel_s':travel,'dwell_s':dwell,'steps':p['steps']})
    robot_busy=sum(v['active_s'] for k,v in stations.items() if k.startswith('robot_'))
    loads={k:v['active_s'] for k,v in stations.items() if not k.startswith('robot_')}
    loads['correction_robots']=robot_busy/robots
    return {'basis':'distance / configured constant speed + declared dwell; no acceleration model',
            'stations':dict(stations),'operations':operations,'waits':waits,
            'dominant_active_load':max(loads,key=loads.get) if loads else None,
            'elapsed_s':elapsed,'output_rate_formula':f'{output_bricks} * 3600 / {elapsed:.6f}',
            'first_admission_s':next((e['t'] for e in events if e['kind']=='pair_admitted'),None),
            'warning':'Concurrent station durations must not be added to obtain elapsed time. Speeds/dwell are assumptions, not factory measurements.'}

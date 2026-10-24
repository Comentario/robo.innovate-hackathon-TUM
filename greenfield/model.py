"""Autonomous cells: dehack -> meter -> inspect -> tone queues -> form -> lower.

SimPy owns resource reservations and all movement time. A bounded unknown route
never asks a human to classify. Failure to confirm material state stops safely.
"""
from collections import Counter,defaultdict
from copy import deepcopy
import math,random
import simpy

BED=1.25
L=.245;D=.067;H=.069

class Hold(Exception):pass

def pattern(rows,cols,quotas,offset):
    """Deterministic quantity-constrained pattern, with non-monochrome rows/cols."""
    remaining=list(quotas);out=[];n=rows*cols
    def search(k):
        if k==n:return True
        r,c=divmod(k,cols)
        options=sorted((i for i,v in enumerate(remaining) if v),key=lambda i:(
            (c>0 and out[-1]==i)+(r>0 and out[k-cols]==i),-remaining[i],(i-offset)%len(remaining)))
        for i in options:
            if c==cols-1 and len(set(out[r*cols:k]+[i]))==1:continue
            if r==rows-1 and len({*(out[j*cols+c] for j in range(r)),i})==1:continue
            remaining[i]-=1;out.append(i)
            if search(k+1):return True
            out.pop();remaining[i]+=1
        return False
    if not search(0):raise Hold('No valid spatial mix for configured quantities')
    return out

class Plant:
    def __init__(self,config):
        self.c=deepcopy(config);self.validate();c=self.c;g=c['geometry']
        self.L,self.D,self.H=[v/1000 for v in g['brick_mm']];self.n=g['rows']*g['columns'];self.env=simpy.Environment()
        self.rng=random.Random(c['seed']);self.done=self.env.event();self.changed=self.env.event()
        self.events=[];self.tracks=defaultdict(list);self.positions={};self.initial={};self.material={};self.aux={}
        self.held_tools={};self.pending_steps=0;self.active=set();self.stats=Counter();self.status='running';self.reason=None
        self.placed=[];self.shipped=[];self.pallets=[];self.layer_results=[];self.faults_used=set()
        self.source_finished=False;self.inspected=0;self.inventory=defaultdict(int);self.candidates=defaultdict(list)
        self.pallet_mix=[];self.pack_layers=[]
        self.builders_finished=0;self.produced_layers=0;self.reserved_layers=0;self.timing=defaultdict(lambda:Counter())
        self.tail_shift=(c['buffer_cells_per_shade']-20)*.3
        self.bays=(c['cells']+1)//2;self.cell_z=[(i-(c['cells']-1)/2)*4.0 for i in range(c['cells'])]
        self.bay_z=[sum(self.cell_z[2*b:2*b+2])/len(self.cell_z[2*b:2*b+2]) for b in range(self.bays)]
        self.tray_slots=simpy.Store(self.env);self.tray_slots.items.extend((b,k) for b in range(self.bays) for k in (0,1))
        self.layers=[simpy.Store(self.env) for _ in range(self.bays)]
        self.free_cells=[simpy.Store(self.env) for _ in range(self.bays)]
        disabled=c['faults']['disabled_cells']
        for i in range(c['cells']):
            if i not in disabled:self.free_cells[i//2].items.append(i)
        self.intakes=[simpy.Store(self.env,capacity=1) for _ in range(c['cells'])]
        self.scan=[simpy.Resource(self.env,capacity=1) for _ in range(c['cells'])]
        self.router=[simpy.Resource(self.env,capacity=1) for _ in range(c['cells'])]
        self.inspect_zones=[[simpy.Resource(self.env,capacity=1) for _ in range(8)] for _ in range(c['cells'])]
        self.reserve_transfer=self.router  # One physical handling shuttle per cell
        self.reserve_slots=[simpy.Store(self.env) for _ in range(c['cells'])]
        for store in self.reserve_slots:store.items.extend(range(c['accepted_overflow_capacity']//c['cells']))
        self.inlet=[simpy.Resource(self.env,capacity=1) for _ in range(c['cells'])]
        self.queue_cells={(i,s):[simpy.Resource(self.env,capacity=1) for _ in range(c['buffer_cells_per_shade'])]
                          for i in range(c['cells']) for s in c['shades']}
        self.ready={(i,s):simpy.Store(self.env) for i in range(c['cells']) for s in c['shades']}
        self.full_layers=simpy.Store(self.env,capacity=c['cells'])
        self.formation=[simpy.Resource(self.env,capacity=1) for _ in range(c['cells'])]
        self.layer_pickup=[self.env.event() for _ in range(c['cells'])]
        self._material()

    def validate(self):
        c=self.c;g=c['geometry']
        if c['input_stacks'] not in (1,2,3,4):raise ValueError('Input buffer supports one to four 800-brick stacks')
        if g['brick_mm'] != [245,67,69]:raise ValueError('Current physical layout is qualified only for the organizer brick dimensions')
        if c['cells'] not in (2,4,6,8):raise ValueError('Supported physical layouts: 2, 4, 6 or 8 cells')
        if g['rows']!=4 or g['columns']!=10 or g['output_layers']!=14 or g['input_layers']!=20:
            raise ValueError('This concept preserves the organizer 10x4x20 -> 10x4x14 layout')
        for k in ('input_stacks','buffer_cells_per_shade','reject_capacity','quarantine_capacity','accepted_overflow_capacity'):
            if type(c[k]) is not int or c[k]<=0:raise ValueError(k+' must be a positive integer')
        for k in ('defect_rate','uncertain_rate','reinspection_resolution','false_accept_rate','false_reject_rate'):
            if not 0<=c[k]<=1:raise ValueError(k+' must be a probability')
        if len(c['shades'])!=3 or len(set(c['shades']))!=3:raise ValueError('Three accepted shade reservoirs are required')
        if any(not math.isclose(v,1/3) for v in c['recipe']):raise ValueError('Current spatial pattern is verified for an equal-third recipe')
        if len(c['recipe'])!=3 or not math.isclose(sum(c['recipe']),1) or min(c['recipe'])<=0:raise ValueError('Invalid recipe')
        for v in [c['brick_mass_kg'],c['input_bricks_per_hour'],c['max_simulation_seconds'],*c['speeds'].values(),*c['dwell'].values()]:
            if not math.isfinite(v) or v<=0:raise ValueError('Engineering inputs must be positive and finite')
        if c['accepted_overflow_capacity']//c['cells']>50 or c['accepted_overflow_capacity']%c['cells']:
            raise ValueError('Approved reserve layout supports at most 50 pockets per cell, equally divided')
        if c['buffer_cells_per_shade']<14:raise ValueError('Each tone queue must support the largest 40-brick layer quota')
        if c['buffer_cells_per_shade'] not in (20,30):raise ValueError('Supported physical tone layouts have 20 or 30 zones per shade')
        if c['brick_mass_kg']*9.80665>350:raise ValueError('Selected driven roller load envelope exceeded')
        if c['speeds']['belt_m_s']>.6 or c['speeds']['buffer_m_s']>.6:raise ValueError('Selected 35 W 30:1 roller profile exceeded')
        if not .1<=c['speeds']['pallet_m_s']<=.5:raise ValueError('Reference pallet conveyor speed exceeded')
        if c['geometry']['rows']*c['geometry']['columns']*c['brick_mass_kg']+c['layer_tool_mass_kg']>2000/9.80665:
            raise ValueError('Reference high-load gantry force envelope exceeded')
        if c['speeds']['gantry_xy_m_s']>1.25:raise ValueError('High-load reference axis speed exceeded')
        if any(i not in range(c['cells']) for i in c['faults']['disabled_cells']):raise ValueError('Unknown disabled cell')
        if len(c['faults']['disabled_cells'])==c['cells']:raise ValueError('No healthy cell')
        for b in range((c['cells']+1)//2):
            if all(i in c['faults']['disabled_cells'] for i in range(2*b,min(c['cells'],2*b+2))):
                raise ValueError('Each source bay needs at least one available cell')

    def pose(self,x,y,z,slot):
        r,k=divmod(slot,self.c['geometry']['columns'])
        return [x+(r-1.5)*self.L,y,z+(k-4.5)*self.D]

    def _material(self):
        g=self.c['geometry'];total=self.c['input_stacks']*g['input_layers']*self.n
        for j in range(total):
            stack=j//(20*self.n);layer=(j//self.n)%20;slot=j%self.n
            identity=f'B{j:05}'
            p=self.pose(-3,.15+(19-layer+.5)*self.H,stack*1.2,slot)
            shade=self.rng.choices(self.c['shades'],weights=self.c['recipe'])[0]
            self.material[identity]={'id':identity,'product_id':self.c['product_id'],'shade':shade,
                'good':self.rng.random()>=self.c['defect_rate'],'location':'input','observed':None}
            self.initial[identity]=p[:];self.positions[identity]=p[:]
        self.add_aux('GUIDE-GATE',[(21+self.tail_shift),.91,0],'guide_gate')
        for tool,p in [('dehack',[0,2.6,0]),('stacker',[(21+self.tail_shift),2.6,0])]:self.add_aux('TOOL-'+tool,p,'tool')
        for b,z in enumerate(self.bay_z):self.add_aux(f'ROW-SHUTTLE-{b}',[4.7,BED,z],'roller_shuttle')
        for i,z in enumerate(self.cell_z):
            self.add_aux(f'REJECT-PUSHER-{i}',[9,BED+.045,z-self.D/2-.012],'side_pusher')
            self.add_aux(f'INFEED-{i}',[5.6-self.L/2-.012,BED+.045,z],'pusher')
            self.add_aux(f'ROW-PUSHER-{i}',[(16.65+self.tail_shift)-self.L/2-.012,BED+.045,z],'pusher')
            self.add_aux(f'SORTER-{i}',[9.45,BED,z],'roller_shuttle')
            self.add_aux(f'PICKER-{i}',[9,2.5,z],'clamp_gripper')
        for i,z in enumerate(self.cell_z):self.add_aux(f'SELECTOR-{i}',[(16.25+self.tail_shift),BED,z-.3015],'selector')
        for i in range(self.c['input_stacks']):self.add_aux(f'P-IN-{i}',[-3,.08,i*1.2],'pallet')
        for i in range(math.ceil(total/560)+1):self.add_aux(f'P-OUT-{i}',[(21+self.tail_shift),.214,0 if i==0 else -3-i*1.2],'pallet')

    def add_aux(self,identity,p,kind):
        self.aux[identity]={'kind':kind};self.positions[identity]=p[:];self.initial[identity]=p[:]

    def notify(self):
        old=self.changed;self.changed=self.env.event()
        if not old.triggered:old.succeed()

    def emit(self,kind,station='',**kwargs):self.events.append({'t':round(self.env.now,7),'kind':kind,'station':station,**kwargs})
    def locate(self,ids,location):
        for identity in ids:self.material[identity]['location']=location

    def pause(self,station,label,seconds):
        self.emit('step',station,label=label,duration=seconds,distance_m=0,speed_m_s=None)
        self.timing[station]['dwell_s']+=seconds
        self.pending_steps+=1
        yield self.env.timeout(seconds)
        self.pending_steps-=1

    def zone_key(self,p):
        if abs(p[1]-(BED+self.H/2))>.001:return None
        cell=round(p[2]/4+(self.c['cells']-1)/2)
        if cell not in range(self.c['cells']):return None
        z=self.cell_z[cell]
        if abs(p[2]-z)<.01 and 6.39<=p[0]<=8.51:
            zone=round((p[0]-6.4)/.3)
            if abs(p[0]-(6.4+.3*zone))<.001:return f'scan:{cell}:0:{zone}'
        if 10.14<=p[0]<=10.16+(self.c['buffer_cells_per_shade']-1)*.3:
            lane=round(p[2]-z)+1;zone=round((p[0]-10.15)/.3)
            if lane in range(3) and abs(p[2]-(z+lane-1))<.001 and abs(p[0]-(10.15+zone*.3))<.001:
                return f'tone:{cell}:{lane}:{zone}'
        return None

    def move(self,ids,targets,station,label,speed):
        if not ids:return
        if any(i in self.active for i in ids):raise AssertionError('Material double booking')
        gate=None
        if len(ids)==1 and ids[0] in self.material and targets[0][0]>self.positions[ids[0]][0]+.05:
            gate=self.zone_key(self.positions[ids[0]])
        if gate:
            self.emit('stop_command',station,zone=gate,opened=True,duration=.08)
            yield from self.pause(station,'Retract accumulation stop',.08)
        starts=[self.positions[i][:] for i in ids]
        distance=max(max(abs(a-b) for a,b in zip(p,q)) for p,q in zip(starts,targets))
        if distance<1e-10:return
        duration=distance/speed;t=self.env.now
        self.emit('step',station,label=label,duration=duration,distance_m=distance,speed_m_s=speed)
        self.timing[station]['travel_s']+=duration;self.timing[station]['moves']+=1
        for identity,p,q in zip(ids,starts,targets):
            self.tracks[identity].append({'t0':t,'t1':t+duration,'from':p,'to':q[:],'station':station,'label':label})
            self.positions[identity]=q[:];self.active.add(identity)
        yield self.env.timeout(duration)
        for identity in ids:self.active.remove(identity)
        if gate:
            self.emit('stop_command',station,zone=gate,opened=False,duration=.08)
            yield from self.pause(station,'Raise cleared-zone stop',.08)

    def carry(self,ids,targets,tool,label):
        aux='TOOL-'+tool;speed=self.c['speeds'];dwell=self.c['dwell']
        starts=[self.positions[i][:] for i in ids];x=sum(p[0] for p in starts)/len(ids);z=sum(p[2] for p in starts)/len(ids)
        xt=sum(p[0] for p in targets)/len(ids);zt=sum(p[2] for p in targets)/len(ids)
        top=max(p[1] for p in starts)+self.H/2;top_t=max(p[1] for p in targets)+self.H/2
        clear=max(2.35,top+.15,top_t+.15);home=getattr(self,'tool_homes',{}).get(tool,[0,2.6,0] if tool=='dehack' else [(21+self.tail_shift),2.6,0])
        yield from self.move([aux],[[x,2.6,z]],tool,'Approach above source',speed['gantry_xy_m_s'])
        yield from self.move([aux],[[x,top,z]],tool,'Lower to grip',speed['gantry_z_m_s'])
        yield from self.pause(tool,'Grip confirmation',dwell['grip_s'])
        self.emit('attach',tool,ids=ids)
        high=[[p[0],p[1]+clear-top,p[2]] for p in starts]
        yield from self.move(ids+[aux],high+[[x,clear,z]],tool,'Lift retained layer',speed['gantry_z_m_s'])
        lifted=[[q[0],q[1]+clear-top_t,q[2]] for q in targets]
        yield from self.move(ids+[aux],lifted+[[xt,clear,zt]],tool,label,speed['gantry_xy_m_s'])
        yield from self.move(ids+[aux],targets+[[xt,top_t,zt]],tool,'Deposit supported layer',speed['gantry_z_m_s'])
        yield from self.pause(tool,'Release confirmation',dwell['release_s']);self.emit('detach',tool,ids=ids)
        yield from self.move([aux],[[xt,2.6,zt]],tool,'Vertical retract',speed['gantry_z_m_s'])
        yield from self.move([aux],[home],tool,'Return to clear home',speed['gantry_xy_m_s'])

    def picked_move(self,identity,target,cell,station,label,speed):
        tool=f'PICKER-{cell}';p=self.positions[identity][:]
        grip=[p[0],p[1]+self.H/2+.025,p[2]]
        if self.held_tools.get(tool)!=identity:
            old=self.positions[tool][:];clear=max(2.5,old[1],grip[1]+.15)
            yield from self.move([tool],[[old[0],clear,old[2]]],station,'Empty clamp retract',.7)
            yield from self.move([tool],[[grip[0],clear,grip[2]]],station,'Empty clamp approach above source',self.c['speeds']['transfer_m_s'])
            yield from self.move([tool],[grip],station,'Lower mechanical clamp',.7)
            yield from self.pause(station,'Clamp confirmation',.1)
            self.held_tools[tool]=identity;self.emit('grip_closed',station,brick=identity,tool=tool)
        q=target[0]
        yield from self.move([identity,tool],[q,[q[0],q[1]+self.H/2+.025,q[2]]],station,label,speed)

    def release_picker(self,cell,station):
        tool=f'PICKER-{cell}';identity=self.held_tools.pop(tool)
        self.emit('grip_open',station,brick=identity,tool=tool)
        p=self.positions[tool][:]
        yield from self.pause(station,'Release clamp confirmation',.1)
        yield from self.move([tool],[[p[0],max(2.5,p[1]+.15),p[2]]],station,'Empty clamp vertical retract',.7)

    def guarded(self,generator):
        try:yield from generator
        except Hold as e:
            if not self.done.triggered:
                self.status='safe_hold';self.reason=str(e);self.emit('safe_hold',reason=self.reason);self.done.succeed()

    def work_in_progress(self,cell=None,bay=None):
        terminal={'shipped','partial_pallet','reject','quarantine'}
        return sum(b['location'] not in terminal and (cell is None or b.get('cell')==cell) and (bay is None or b.get('bay')==bay) for b in self.material.values())

    def source(self):
        total=self.c['input_stacks']*20;speed=self.c['speeds'];last_stack=-1
        for layer in range(total):
            due=layer*self.n*3600/self.c['input_bricks_per_hour']
            if self.env.now<due:yield self.env.timeout(due-self.env.now)
            bay,nest=yield self.tray_slots.get()
            stack=layer//20
            if stack!=last_stack:
                if stack:
                    old=f'P-IN-{stack-1}'
                    previous=[f'P-IN-{k}' for k in range(stack-1)]
                    if previous:
                        yield from self.move(previous,[[self.positions[i][0],.08,self.positions[i][2]-1.2] for i in previous],'dock','Advance empty pallet return',speed['pallet_m_s'])
                    yield from self.move([old],[[-3,.08,0]],'dock','Transfer empty pallet onto return lane',speed['pallet_m_s'])
                    yield from self.move([old],[[-3,.08,-2]],'dock','Empty input pallet discharge',speed['pallet_m_s'])
                ids=[f'B{j:05}' for j in range(stack*800,(stack+1)*800)]+[f'P-IN-{stack}']
                aligned=[[self.positions[i][0],self.positions[i][1],self.positions[i][2]-stack*1.2] for i in ids]
                yield from self.move(ids,aligned,'dock','Align input stack',speed['pallet_m_s'])
                yield from self.move(ids,[[p[0]+3,p[1],p[2]] for p in aligned],'dock','Dock full input pallet',speed['pallet_m_s'])
                last_stack=stack
            ids=[f'B{j:05}' for j in range(layer*self.n,(layer+1)*self.n)]
            for identity in ids:self.material[identity]['bay']=bay
            z=self.bay_z[bay]+(nest-.5)*1.1
            target=[self.pose(3,BED+self.H/2,z,k) for k in range(self.n)]
            yield from self.carry(ids,target,'dehack','Unload single layer')
            self.stats['unloaded_bricks']+=len(ids);self.locate(ids,'tray');self.emit('layer_unloaded','dehack',layer=layer,bay=bay,nest=nest,ids=ids)
            yield self.layers[bay].put((layer,nest,ids))
        self.source_finished=True;self.emit('source_finished');self.notify()

    def feeder(self,bay):
        shuttle=f'ROW-SHUTTLE-{bay}';v=self.c['speeds']['transfer_m_s']
        while True:
            layer,nest,ids=yield self.layers[bay].get()
            for r in (3,2,1,0):
                cell=yield self.free_cells[bay].get();z=self.cell_z[cell]
                row=ids[r*10:(r+1)*10];rz=sum(self.positions[i][2] for i in row)/10
                yield from self.move([shuttle],[[4.7,BED,rz]],f'feeder_{bay}','Dock empty roller shuttle',v)
                target=[[4.7,self.positions[i][1],self.positions[i][2]] for i in row]
                yield from self.move(row,target,f'feeder_{bay}','Powered front-row extraction',v)
                target=[[4.7,BED+self.H/2,z+(k-4.5)*self.D] for k in range(10)]
                yield from self.move(row+[shuttle],target+[[4.7,BED,z]],f'feeder_{bay}','Supported row shuttle cross-travel',v)
                target=[[5.6,p[1],p[2]] for p in target]
                yield from self.move(row,target,f'feeder_{bay}','Powered row discharge to infeed',v)
                self.locate(row,f'cell_{cell}_intake')
                for identity in row:self.material[identity]['cell']=cell
                yield self.intakes[cell].put(row)
                yield from self.pause(f'feeder_{bay}','Row-clear sensor confirmation',self.c['dwell']['sensor_s'])
            yield self.tray_slots.put((bay,nest));self.notify()

    def intake(self,cell):
        z=self.cell_z[cell];pitch=.30
        while True:
            row=yield self.intakes[cell].get()
            for number,identity in enumerate(row):
                with self.inlet[cell].request() as req:
                    yield req
                    entrance=self.inspect_zones[cell][0].request();yield entrance
                    p=self.positions[identity][:]
                    tool=f'INFEED-{cell}';home=5.6-self.L/2-.012
                    yield from self.move([tool],[[home,BED+.045,p[2]]],f'cell_{cell}_infeed','Position singulation pusher',self.c['speeds']['transfer_m_s'])
                    yield from self.move([identity,tool],[[5.95,p[1],p[2]],[5.95-self.L/2-.012,BED+.045,p[2]]],f'cell_{cell}_infeed','Pusher singulates one brick',self.c['speeds']['transfer_m_s'])
                    yield from self.move([tool],[[home,BED+.045,p[2]]],f'cell_{cell}_infeed','Retract singulation pusher',self.c['speeds']['transfer_m_s'])
                    yield from self.move([identity],[[5.95,p[1],z]],f'cell_{cell}_infeed','Align separated brick with lane',self.c['speeds']['transfer_m_s'])
                    target=[[6.4,BED+self.H/2,z]]
                    yield from self.move([identity],target,f'cell_{cell}_infeed','Meter separated brick',self.c['speeds']['transfer_m_s'])
                    self.env.process(self.guarded(self.inspect(identity,cell,entrance)))
                    yield from self.pause(f'cell_{cell}_infeed','Maintain inspection pitch',pitch/self.c['speeds']['belt_m_s'])
            yield self.free_cells[cell//2].put(cell)

    def inspect(self,identity,cell,entrance):
        b=self.material[identity];d=self.c['dwell'];z=self.cell_z[cell]
        # Independent deterministic per-brick observations, unchanged by lane count.
        rng=random.Random(f'{self.c["seed"]}:{identity}:inspection')
        uncertain=rng.random()<self.c['uncertain_rate']
        reject=(rng.random()>=self.c['false_accept_rate']) if not b['good'] else (rng.random()<self.c['false_reject_rate'])
        reservation=entrance
        for zone in range(1,8):
            nxt=self.inspect_zones[cell][zone].request();yield nxt
            yield from self.move([identity],[[6.4+zone*.3,BED+self.H/2,z]],f'cell_{cell}_vision','Advance to free inspection zone',self.c['speeds']['belt_m_s'])
            self.inspect_zones[cell][zone-1].release(reservation);reservation=nxt
        with self.scan[cell].request() as req:
            yield req
            yield from self.pause(f'cell_{cell}_vision','Trigger + exposure + inference',d['sensor_s']+d['exposure_s']+d['inference_s'])
            if uncertain:
                self.stats['reinspected']+=1;self.emit('reinspection',f'cell_{cell}_vision',brick=identity)
                yield from self.pause(f'cell_{cell}_vision','Automatic second exposure',d['exposure_s']+d['inference_s'])
                uncertain=rng.random()>=self.c['reinspection_resolution']
            decision='quarantine' if uncertain else 'reject' if reject else 'accepted'
            b['observed']=decision
            self.emit('inspection',f'cell_{cell}_vision',brick=identity,decision=decision,shade=b['shade'])
            self.inspected+=1;self.notify()
            with self.router[cell].request() as route:
                yield route
                yield from self.move([identity],[[9.0,BED+self.H/2,z]],f'cell_{cell}_router','Clear inspection arch before diverting',self.c['speeds']['transfer_m_s'])
                self.stats[f'cell_{cell}_seen']+=1
                fault=self.c['faults']
                if cell==fault['jam_cell'] and self.stats[f'cell_{cell}_seen']==fault['jam_at_piece'] and 'jam' not in self.faults_used:
                    self.faults_used.add('jam');self.emit('recovery_start',f'cell_{cell}_router',reason='Known-position gate jam',brick=identity)
                    p=self.positions[identity][:]
                    yield from self.move([identity],[[p[0]-.02,p[1],p[2]]],f'cell_{cell}_router','Bounded reverse within reserved zone',.1)
                    yield from self.pause(f'cell_{cell}_router','Automatic home check',.4)
                    yield from self.move([identity],[p],f'cell_{cell}_router','Retry confirmed transfer',.1)
                    self.stats['recoveries']+=1;self.emit('recovery_complete',f'cell_{cell}_router',brick=identity)
                if decision!='accepted' and hasattr(self,'discard'):
                    yield from self.discard(identity,cell,decision,reservation)
                    return
                if decision!='accepted':
                    capacity=self.c[decision+'_capacity']
                    if self.stats[decision]>=capacity:raise Hold(decision+' container full')
                    index=self.stats[f'{decision}_{cell}'];self.stats[f'{decision}_{cell}']+=1;self.stats[decision]+=1
                    if index>=400:raise Hold('Collection compartment full; upstream inhibited')
                    xx=8.5 if decision=='reject' else 7.7
                    inlet=9.0 if decision=='reject' else 8.7
                    target=[[xx+((index%2)-.5)*.28,.22+self.H/2+(index//40)*self.H,z+1.6+((index//2)%20)*.075]]
                    tool=f'REJECT-PUSHER-{cell}';v=self.c['speeds']['transfer_m_s']
                    yield from self.move([tool],[[inlet,BED+.045,z-self.D/2-.012]],f'cell_{cell}_router','Select side-ejection channel',v)
                    yield from self.move([identity],[[inlet,BED+self.H/2,z]],f'cell_{cell}_router','Position over ejector rollers',v)
                    yield from self.move([identity,tool],[[inlet,BED+self.H/2,z+1.25],[inlet,BED+.045,z+1.25-self.D/2-.012]],f'cell_{cell}_router','Side pusher ejects observed extreme or uncertainty',v)
                    yield from self.move([tool],[[inlet,BED+.045,z-self.D/2-.012]],f'cell_{cell}_router','Retract side pusher',v)
                    # The enclosed collection compartment is not a contact/settling model.
                    yield from self.move([identity],[[xx,.65,z+1.6]],f'cell_{cell}_router','Travel down supported collection chute',.6)
                    yield from self.move([identity],target,f'cell_{cell}_router','Contained collection; settling abstracted',1.0)
                    b['location']=decision;self.emit('routed',f'cell_{cell}_router',brick=identity,destination=decision);self.inspect_zones[cell][-1].release(reservation);self.notify();return
                shade=b['shade'];s=self.c['shades'].index(shade);zz=z+(s-1)*1.0
                # Admission to a finite physical buffer is reserved before transfer.
                resources=self.queue_cells[cell,shade]
                if all(zone.count for zone in resources):
                    self.env.process(self.guarded(self.overflow(identity,cell,shade,reservation)))
                    return
                buffer_reservation=resources[0].request()
                yield buffer_reservation
                shuttle=f'SORTER-{cell}';v=self.c['speeds']['transfer_m_s']
                yield from self.move([shuttle],[[9.45,BED,z]],f'cell_{cell}_router','Return cross-belt shuttle to receive',v)
                yield from self.move([identity],[[9.45,BED+self.H/2,z]],f'cell_{cell}_router','Load cross-belt shuttle',v)
                yield from self.move([identity,shuttle],[[9.45,BED+self.H/2,zz],[9.45,BED,zz]],f'cell_{cell}_router','Shuttle to accepted shade lane',v)
                yield from self.move([identity],[[10.15,BED+self.H/2,zz]],f'cell_{cell}_router','Powered discharge into shade lane',v)
                self.inventory[cell,shade]+=1;b['location']='accepted_buffer';self.emit('buffer_admitted',f'cell_{cell}_buffer',brick=identity,shade=shade);self.notify()
                self.inspect_zones[cell][-1].release(reservation)
                self.env.process(self.guarded(self.buffer(identity,cell,shade,buffer_reservation)))

    def overflow(self,identity,cell,shade,inspection_reservation):
        if not self.reserve_slots[cell].items:self.emit('interlock_wait',f'cell_{cell}_reserve',gate='approved_reserve_space',reason='Upstream inhibited; no material discarded')
        slot=yield self.reserve_slots[cell].get();z=self.cell_z[cell]
        target=[[9.3+(slot%4)*.30,BED+self.H/2,z+1.6+(slot//4)*.08]]
        with self.reserve_transfer[cell].request() as transfer:
            yield transfer
            p=self.positions[identity][:]
            yield from self.picked_move(identity,[[p[0],2.05,p[2]]],cell,f'cell_{cell}_reserve','Lift above approved stock',.3)
            yield from self.picked_move(identity,[[target[0][0],2.05,target[0][2]]],cell,f'cell_{cell}_reserve','Transfer over reserved pocket',self.c['speeds']['transfer_m_s'])
            yield from self.picked_move(identity,target,cell,f'cell_{cell}_reserve','Lower into approved pocket',.3)
            yield from self.release_picker(cell,f'cell_{cell}_reserve')
        self.locate([identity],'accepted_reserve');self.emit('reserve_admitted',f'cell_{cell}_reserve',brick=identity);self.stats['overflow_routes']+=1
        self.inspect_zones[cell][-1].release(inspection_reservation);self.notify()
        resource=self.queue_cells[cell,shade][0]
        zz=z+(self.c['shades'].index(shade)-1)
        while True:
            with self.reserve_transfer[cell].request() as transfer:
                yield transfer
                if resource.count:
                    pass
                else:
                    request=resource.request();yield request
                    p=self.positions[identity][:]
                    yield from self.picked_move(identity,[[p[0],2.05,p[2]]],cell,f'cell_{cell}_reserve','Raise retrieval pocket',.3)
                    yield from self.picked_move(identity,[[10.15,2.05,zz]],cell,f'cell_{cell}_reserve','Automatic reserve return',self.c['speeds']['transfer_m_s'])
                    yield from self.picked_move(identity,[[10.15,BED+self.H/2,zz]],cell,f'cell_{cell}_reserve','Lower retrieved brick',.3)
                    yield from self.release_picker(cell,f'cell_{cell}_reserve')
                    break
            yield self.changed | self.env.timeout(.25)
        yield self.reserve_slots[cell].put(slot)
        self.inventory[cell,shade]+=1;self.locate([identity],'accepted_buffer');self.notify()
        self.env.process(self.guarded(self.buffer(identity,cell,shade,request)))

    def buffer(self,identity,cell,shade,reservation):
        resources=self.queue_cells[cell,shade];z=self.cell_z[cell]+(self.c['shades'].index(shade)-1)
        for index in range(1,len(resources)):
            nxt=resources[index].request();yield nxt
            yield from self.move([identity],[[10.15+index*.3,BED+self.H/2,z]],f'cell_{cell}_buffer','Advance to next free accumulation zone',self.c['speeds']['buffer_m_s'])
            resources[index-1].release(reservation);reservation=nxt
        selected=self.env.event();yield self.ready[cell,shade].put((identity,selected));self.notify()
        yield selected
        # Selector owns the piece; the tail may advance after it has left this zone.
        resources[-1].release(reservation)

    def quota(self,index):
        raw=[self.n*x for x in self.c['recipe']];q=[int(x) for x in raw]
        for k in range(self.n-sum(q)):q[(index+k)%len(q)]+=1
        return q

    def builder(self,cell):
        z=self.cell_z[cell];selector=f'SELECTOR-{cell}';speed=self.c['speeds'];dwell=self.c['dwell']
        while True:
            index=self.reserved_layers;self.reserved_layers+=1;q=self.quota(index)
            desired=pattern(4,10,q,index%3);ids_by_slot={};row_ids=[]
            request=self.formation[cell].request();yield request
            for r in range(4):
                need=Counter(self.c['shades'][v] for v in desired[r*10:r*10+10])
                while any(self.inventory[cell,shade]<n for shade,n in need.items()):
                    if self.inspected==len(self.material) and self.source_finished:
                        remaining=Counter(b['shade'] for b in self.material.values() if b.get('cell')==cell and b['observed']=='accepted' and b['location'] in ('accepted_buffer','accepted_reserve',f'cell_{cell}_intake'))
                        if any(remaining[shade]<n for shade,n in need.items()):
                            self.locate(list(ids_by_slot.values()),'unfinished_layer')
                            self.emit('partial_layer_retained',f'cell_{cell}_former',bricks=len(ids_by_slot),reason='End-of-batch stock cannot complete the next compliant row')
                            self.formation[cell].release(request);self.builders_finished+=1;self.notify();return
                    yield self.changed | self.env.timeout(.25)
                for shade,n in need.items():self.inventory[cell,shade]-=n
                self.emit('row_started',f'cell_{cell}_former',layer=index,row=r)
                for col in range(9,-1,-1):
                    # Move the already formed row by one short-edge pitch before admitting the next brick.
                    if row_ids:
                        target=[[self.positions[i][0],self.positions[i][1],self.positions[i][2]+self.D] for i in row_ids]
                        yield from self.move(row_ids,target,f'cell_{cell}_former','Index row by one brick',speed['transfer_m_s'])
                    shade=self.c['shades'][desired[r*10+col]]
                    identity,selected=yield self.ready[cell,shade].get()
                    self.locate([identity],'forming');ids_by_slot[r*10+col]=identity
                    zz=self.positions[identity][2]
                    yield from self.move([selector],[[(16.25+self.tail_shift),BED,zz]],f'cell_{cell}_selector','Select required tone queue',speed['selector_m_s'])
                    yield from self.move([identity],[[(16.25+self.tail_shift),BED+self.H/2,zz]],f'cell_{cell}_selector','Feed confirmed brick onto shuttle',speed['transfer_m_s'])
                    selected.succeed();self.notify()
                    yield from self.move([identity,selector],[[(16.25+self.tail_shift),BED+self.H/2,z-.3015],[(16.25+self.tail_shift),BED,z-.3015]],f'cell_{cell}_selector','Align with row inlet',speed['selector_m_s'])
                    yield from self.move([identity],[[(16.65+self.tail_shift),BED+self.H/2,z-.3015]],f'cell_{cell}_selector','Feed row inlet',speed['transfer_m_s'])
                    yield from self.pause(f'cell_{cell}_selector','Confirm inlet clear',dwell['sensor_s'])
                    row_ids.append(identity)
                row_x=(18.2+self.tail_shift)+(1.5-r)*self.L
                target=[[row_x,BED+self.H/2,self.positions[i][2]] for i in row_ids]
                pusher=f'ROW-PUSHER-{cell}'
                yield from self.move(row_ids+[pusher],target+[[row_x-self.L/2-.012,BED+.045,z]],f'cell_{cell}_former','Push complete row across roller deck',speed['transfer_m_s'])
                yield from self.move([pusher],[[(16.65+self.tail_shift)-self.L/2-.012,BED+.045,z]],f'cell_{cell}_former','Retract row pusher to home limit',speed['transfer_m_s'])
                yield from self.pause(f'cell_{cell}_former','Pusher home confirmation',dwell['sensor_s'])
                row_ids=[]
            ids=[ids_by_slot[k] for k in range(self.n)]
            # Slots are reversed in X relative to input, but the spatial pattern remains explicit.
            shade_grid=[self.material[i]['shade'] for i in ids]
            mono_rows=sum(len(set(shade_grid[r*10:r*10+10]))==1 for r in range(4))
            mono_cols=sum(len({shade_grid[r*10+c] for r in range(4)})==1 for c in range(10))
            if mono_rows or mono_cols:raise AssertionError('Invalid spatial mix')
            self.layer_results.append({'index':index,'cell':cell,'ids':ids,'counts':dict(Counter(shade_grid)),
                'monochrome_rows':mono_rows,'monochrome_columns':mono_cols})
            self.emit('layer_formed',f'cell_{cell}_former',index=index,ids=ids,counts=dict(Counter(shade_grid)))
            self.locate(ids,'formed_layer');pickup=self.env.event()
            yield self.full_layers.put((cell,index,ids,pickup))
            yield pickup
            self.formation[cell].release(request);self.notify()

    def stacker(self):
        speed=self.c['speeds'];dwell=self.c['dwell'];g=self.c['geometry'];pack=[];pallet_index=0
        while True:
            cell,index,ids,pickup=yield self.full_layers.get()
            target=[[(21+self.tail_shift)+(1.5-k//10)*self.L,BED+self.H/2,(k%10-4.5)*self.D] for k in range(self.n)]
            # Critical uncertain confirmation is inhibited BEFORE moving material.
            if self.c['faults']['critical_sensor_layer']==index:
                yield from self.pause('stacker','Bounded source confirmation timeout',2.0)
                raise Hold('Layer source confirmation missing; motion inhibited, material retained')
            error=self.c['faults']['alignment_error_m'] if index==self.c['faults']['alignment_layer'] else 0
            if error:target=[[p[0]+error,p[1],p[2]] for p in target]
            yield from self.carry(ids,target,'stacker','Transfer mixed layer to guided well')
            pickup.succeed();self.notify();self.locate(ids,'alignment_hold')
            self.emit('alignment_check','stacker',layer=index,error_m=error)
            if abs(error)>.012:raise Hold('Alignment outside bounded correction travel')
            if error:
                self.emit('recovery_start','stacker',reason='Layer offset detected',layer=index)
                yield from self.move(ids,[[p[0]-error,p[1],p[2]] for p in target],'stacker','Guided layer re-centering',.02)
                self.stats['recoveries']+=1;self.emit('recovery_complete','stacker',layer=index)
            yield from self.pause('stacker','Centering paddles / position confirmation',dwell['centering_s'])
            self.pack_layers.append(ids[:]);pack.extend(ids);self.placed.extend(ids);self.locate(ids,'partial_pallet');self.produced_layers+=1
            # Descend after EACH layer so the top transfer plane remains constant.
            moving=pack+[f'P-OUT-{pallet_index}']
            lowered=[[self.positions[i][0],self.positions[i][1]-self.H,self.positions[i][2]] for i in moving]
            yield from self.move(moving,lowered,'elevator','Lower one layer pitch',speed['elevator_m_s'])
            self.emit('layer_stacked','stacker',layer=index,placed=len(self.placed),pack_fill=len(pack),deck_y=BED-(len(pack)//self.n)*self.H)
            if len(pack)==560:
                # Verify counts, product and every layer's mix before autonomous release.
                if len(set(pack))!=560 or any(self.material[i]['product_id']!=self.c['product_id'] for i in pack):raise AssertionError('Invalid output pallet')
                matrix=self.pack_layers[-14:]
                vertical=sum(len({self.material[layer[k]]['shade'] for layer in matrix})==1 for k in range(40))
                counts=Counter(self.material[i]['shade'] for i in pack)
                self.pallet_mix.append({'pallet':pallet_index,'counts':dict(counts),'monochrome_vertical_columns':vertical})
                if vertical:raise Hold('Pallet spatial mix verification failed; material retained')
                # Advance completed pallets before admitting the next one; never drive through parked stock.
                previous=[i for p in self.pallets for i in p]+[f'P-OUT-{k}' for k in range(pallet_index)]
                if previous:
                    yield from self.move(previous,[[self.positions[i][0]+1.25,self.positions[i][1],self.positions[i][2]] for i in previous],'pallet_out','Index downstream pallet accumulation',speed['pallet_m_s'])
                yield from self.move(['GUIDE-GATE'],[[(21+self.tail_shift),2.31,0]],'guide_gate','Raise guide panels clear of output path',.3)
                yield from self.pause('guide_gate','Open end-limit confirmation',dwell['sensor_s'])
                self.emit('gate_open_confirmed','guide_gate')
                dx=3
                yield from self.move(moving,[[self.positions[i][0]+dx,self.positions[i][1],self.positions[i][2]] for i in moving],'pallet_out','Release verified pallet',speed['pallet_m_s'])
                self.pallets.append(pack[:]);self.shipped.extend(pack);self.locate(pack,'shipped')
                self.emit('pallet_released','pallet_out',pallet=pallet_index,shipped=len(self.shipped))
                pallet_index+=1;pack=[]
                empty=f'P-OUT-{pallet_index}'
                yield from self.move([empty],[[(21+self.tail_shift),self.positions[empty][1],0]],'pallet_in','Automatic empty pallet feed',speed['pallet_m_s'])
                yield from self.move([empty],[[(21+self.tail_shift),BED-.07,0]],'elevator','Raise empty pallet to transfer plane',speed['elevator_m_s'])
                yield from self.move(['GUIDE-GATE'],[[(21+self.tail_shift),.91,0]],'guide_gate','Close guide panels around clear transfer plane',.3)
                yield from self.pause('guide_gate','Closed end-limit confirmation',dwell['sensor_s'])
                self.emit('gate_closed_confirmed','guide_gate')
            self.notify()

    def monitor(self):
        while True:
            if (self.source_finished and self.inspected==len(self.material) and
                    self.builders_finished==self.c['cells'] and self.produced_layers==len(self.layer_results)
                    and not self.active and not self.pending_steps):
                self.status='completed_with_residual_stock';self.done.succeed();return
            yield self.changed | self.env.timeout(.25)

    def run(self):
        for process in [self.source(),self.stacker(),self.monitor(),*(self.feeder(b) for b in range(self.bays)),
                        *(self.intake(i) for i in range(self.c['cells'])),*(self.builder(i) for i in range(self.c['cells']))]:
            self.env.process(self.guarded(process))
        self.env.run(until=self.done|self.env.timeout(self.c['max_simulation_seconds']))
        if self.status=='running':self.status='safe_hold';self.reason='Process horizon: incompatible stock or blocked station; no invalid pallet released'
        self.emit('run_finished',status=self.status,reason=self.reason)
        return self.report()

    def report(self):
        t=self.env.now;locations=Counter(b['location'] for b in self.material.values());total=len(self.material)
        placed_bad=sum(not self.material[i]['good'] for i in self.placed)
        good_input=sum(b['good'] for b in self.material.values())
        assert len(set(self.placed))==len(self.placed) and len(set(self.shipped))==len(self.shipped)
        # Handling coverage counts completed material movements; no staff-reduction claim.
        residual=total-len(self.shipped)-locations['partial_pallet']-locations['reject']-locations['quarantine']
        rates={'formed_good_bph':(len(self.placed)-placed_bad)*3600/t if t else 0,
               'released_good_bph':sum(self.material[i]['good'] for i in self.shipped)*3600/t if t else 0}
        k={'input_bricks':total,'inspected':self.inspected,'placed_bricks':len(self.placed),'shipped_bricks':len(self.shipped),
           'full_pallets':len(self.pallets),'partial_pallet_bricks':locations['partial_pallet'],'reject_bricks':locations['reject'],
           'quarantine_bricks':locations['quarantine'],'residual_wip':residual,'material_balance_ok':sum(locations.values())==total,
           'shipped_good':sum(self.material[i]['good'] for i in self.shipped),'formed_good':len(self.placed)-placed_bad,
           'bad_placed':placed_bad,'false_rejects':sum(b['good'] and b['location']=='reject' for b in self.material.values()),
           'reinspected':self.stats['reinspected'],'automatic_recoveries':self.stats['recoveries'],
           'monochrome_rows':sum(x['monochrome_rows'] for x in self.layer_results),
           'monochrome_columns':sum(x['monochrome_columns'] for x in self.layer_results),
           'autonomous_handling_events':self.stats['unloaded_bricks']+len(self.placed),'unloaded_bricks':self.stats['unloaded_bricks'],'overflow_routes':self.stats['overflow_routes'],'input_good_truth':good_input,
           **{key:round(value,3) for key,value in rates.items()}}
        activity=[]
        for cell in range(self.c['cells']):
            stations={f'cell_{cell}_router',f'cell_{cell}_reserve'}
            busy=sum(min(e['duration'],max(0,t-e['t'])) for e in self.events if e['kind']=='step' and e['station'] in stations)
            activity.append({'cell':cell,'busy_s':round(busy,6),'active_fraction':round(busy/t,6) if t else 0})
        return {'handling_activity':activity,'schema_version':'2.0','concept':'Greenfield autonomous blending','config':self.c,'status':self.status,'reason':self.reason,
                'simulated_seconds':round(t,7),'kpis':k,'material':list(self.material.values()),'locations':dict(locations),
                'pallets':self.pallets,'pallet_mix':self.pallet_mix,'layers':self.layer_results,'events':self.events,'timing':dict(self.timing),
                'mechanics':{'initial':self.initial,'tracks':dict(self.tracks),'auxiliaries':self.aux,'cell_z':self.cell_z,'bay_z':self.bay_z,
                             'tail_shift_m':self.tail_shift,'bed_y':BED,'brick_m':[self.L,self.H,self.D],'orientation':self.c['orientation_assumption']},
                'scope':['Reject/quarantine slide along supported chutes. Internal settling inside closed collection bins is abstracted, not contact-simulated.',
                         'Individual powered accumulation zones have independent stops; incremental row formation preserves unfinished layers as WIP.',
                         'No routine human station; autonomous reinspection/quarantine; asset maintenance is outside the production model.',
                         'Dataset classification is synthetic; no Person 1 labels or scores are changed.',
                         'Kinematics, finite accumulation zones and virtual automation; no contact/friction/load dynamics.',
                         'Reference data bound component envelopes only; EOAT, temperature, dust, strokes and product footprint need validation.',
                         'Rates include finite-batch fill/drain. Formed partial pallets are not counted as released product.',
                         'Residual accepted stock is carried inventory, not scrap or a silently relaxed recipe.']}

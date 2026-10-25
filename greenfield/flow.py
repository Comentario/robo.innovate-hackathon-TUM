"""Shared-drive continuous mixing loops with synchronized inlet and fixed outlet.

All supported material moves with one encoder; no independent per-slot motors.
Finite occupancy, protected merge gaps and a single extraction lane per cell.
"""
import math
import simpy
from .twin import TwinPlant
from .model import BED
from .motion import profile
from .junctions import curve,length

X0=10.8;X1=15.2;R=2/math.pi;PITCH=.4;SLOTS=32;PERIMETER=12.8

def loop_pose(distance,z,x1=X1):
    a=x1-X0;s=distance%(2*a+2*math.pi*R);arc=math.pi*R
    if s<a:return [X0+s,BED+.0345,z-R],0.
    if s<a+arc:
        angle=(s-a)/R;return [x1+R*math.sin(angle),BED+.0345,z-R*math.cos(angle)],-angle
    if s<2*a+arc:return [x1-(s-a-arc),BED+.0345,z+R],-math.pi
    angle=(s-2*a-arc)/R
    return [X0-R*math.sin(angle),BED+.0345,z+R*math.cos(angle)],-math.pi-angle


class FlowPlant(TwinPlant):
    def __init__(self,c):
        if not 1.<=c['loop_m_s']<=1.5 or not 3<=c['loop_capacity']<=int(32+2*c.get('transport_extension_m',0)/PITCH)-4:raise ValueError('Unsupported loop speed or finite capacity')
        super().__init__(c)
        self.dispatch_shift=max(0.,self.tail_shift-2.8);self.merge_x=28+self.dispatch_shift
        for key in ('OUTPUT-SHUTTLE','OUTPUT-CART'):
            self.positions[key][0]+=self.dispatch_shift;self.initial[key]=self.positions[key][:]
        self.merge_ticks=math.ceil(profile(length(curve([9.,BED+self.H/2,0],[X0,BED+self.H/2,-R],.72)),c['loop_m_s'],1.,0.,c['loop_m_s'])['duration']/(PITCH/c['loop_m_s']));self.loop_end=X1+self.tail_shift;self.loop_slots=32+round(2*self.tail_shift/PITCH);self.loop_exit=11+round(self.tail_shift/PITCH)
        self.loop_stock=[{} for _ in range(8)];self.loop_pending=[None]*8;self.loop_merging=[None]*8
        self.loop_prefetch=[None]*8;self.loop_demands=[None]*8;self.loop_exit_busy=[False]*8
        self.route_approach=[simpy.Resource(self.env,capacity=1) for _ in range(8)];self.approach_tokens=[None]*8
        self.entry_dock=[simpy.Resource(self.env,capacity=1) for _ in range(8)]
        for cell,z in enumerate(self.cell_z):
            key=f'REJECT-PUSHER-{cell}';self.positions[key][1]=BED+.30;self.initial[key]=self.positions[key][:]
        self.loop_peaks=[0]*8;self.loop_backpressure=0
        for cell in range(8):
            for prefix in ('PICKER-','SORTER-','SELECTOR-'):
                key=prefix+str(cell)
                self.aux.pop(key,None);self.positions.pop(key,None);self.initial.pop(key,None)
            key=f'ROW-PUSHER-{cell}'
            self.positions[key][2]+=-.6485;self.initial[key]=self.positions[key][:]

    def loop_release_approach(self,cell):
        token=self.approach_tokens[cell]
        if token is not None:self.route_approach[cell].release(token);self.approach_tokens[cell]=None;self.notify()

    def loop_pre_route(self,identity,cell,reservation):
        token=self.route_approach[cell].request();yield token
        self.approach_tokens[cell]=token
        yield from self.move([identity],[[9.,BED+self.H/2,self.cell_z[cell]]],f'cell_{cell}_approach','Independent powered approach to protected merge inlet',1.)
        self.inspect_zones[cell][-1].release(reservation);self.notify()

    def loop_admit(self,identity,cell,reservation):
        dock=self.entry_dock[cell].request()
        if not dock.triggered:self.loop_backpressure+=1
        yield dock
        clear=self.env.event()
        self.loop_pending[cell]=(identity,dock,clear,reservation)
        yield clear

    def loop_load(self,identity,cell,clear,reservation):
        z=self.cell_z[cell];speed=self.c['loop_m_s'];tick=PITCH/speed
        inlet=curve([9.,BED+self.H/2,z],[X0,BED+self.H/2,z-R],.72)
        first=profile(length(inlet),speed,1.,0.,speed)['duration']
        ticks=self.merge_ticks
        yield self.env.timeout(ticks*tick-first)
        self.loop_release_approach(cell)
        yield from self.move([identity],[[X0,BED+self.H/2,z-R]],f'cell_{cell}_router','Guided servo merge into reserved loop gap',speed,end_speed=speed,path=inlet)
        clear.succeed();self.notify()

    def loop_take(self,cell,shade,next_shade=None):
        prefetched=self.loop_prefetch[cell]
        if prefetched:
            expected,event=prefetched
            if expected!=shade:raise AssertionError('Prefetched tone does not match row')
            self.loop_prefetch[cell]=None
        else:
            event=self.env.event()
            if self.loop_demands[cell] is not None:raise AssertionError('Two outlet demands for one cell')
            self.loop_demands[cell]=(shade,event);self.notify()
        identity=yield event
        # A single next brick can approach while the independent row belt indexes.
        if next_shade is not None and self.inventory[cell,next_shade]>0:
            ready=self.env.event();self.loop_prefetch[cell]=(next_shade,ready)
            self.loop_demands[cell]=(next_shade,ready);self.notify()
        return identity

    def loop_extract(self,identity,cell,event):
        z=self.cell_z[cell];self.locate([identity],'forming')
        # Diagonal fixed belt leaves the loop on the outside of its bend.
        yield from self.move([identity],[[16.25+self.tail_shift,BED+self.H/2,z-.95]],f'cell_{cell}_outlet','Fixed selected-tone outlet aligns outside the loop bend',self.c['loop_m_s'],start_speed=self.c['loop_m_s'],end_speed=.8,path=curve(self.positions[identity][:],[16.25+self.tail_shift,BED+self.H/2,z-.95],.38))
        yield from self.move([identity],[[16.65+self.tail_shift,BED+self.H/2,z-.95]],f'cell_{cell}_outlet','Straight nose transfer into separated row pocket',.8,start_speed=.8)
        self.loop_exit_busy[cell]=False;event.succeed(identity);self.notify()

    def loop_advance(self,cell,distance,start_speed,end_speed):
        stock=self.loop_stock[cell];ids=[v for v in stock.values() if isinstance(v,str) and v.startswith('B')]
        speed=self.c['loop_m_s'];motion=profile(distance,speed,1.,start_speed,end_speed);duration=motion['duration'];t=self.env.now
        if not ids:
            yield self.env.timeout(duration);return
        self.emit('step',f'cell_{cell}_mix_loop',label='Continuous common-drive mixing conveyor',duration=duration,distance_m=distance,speed_m_s=speed,motion=motion)
        self.timing[f'cell_{cell}_mix_loop']['travel_s']+=duration
        self.timing[f'cell_{cell}_mix_loop']['moves']+=1
        for slot,identity in stock.items():
            if not identity.startswith('B'):continue
            if identity in self.active:raise AssertionError('Loop double booking')
            s=slot*PITCH;target,_=loop_pose(s+distance,self.cell_z[cell],self.loop_end)
            seq=self.tracks[identity]
            if start_speed==end_speed and seq and seq[-1].get('loop_s0') is not None and abs(seq[-1]['t1']-t)<1e-7 and seq[-1]['motion']['start_speed']==seq[-1]['motion']['end_speed']:
                last=seq[-1];last['t1']=t+duration;last['to']=target[:];last['loop_s1']+=distance
                last['motion']['distance']+=distance;last['motion']['duration']+=duration
            else:
                seq.append({'t0':t,'t1':t+duration,'from':self.positions[identity][:],'to':target[:],'station':f'cell_{cell}_mix_loop','label':'Continuous common-drive mixing conveyor','motion':dict(motion),'loop_s0':s,'loop_s1':s+distance,'loop_cell':cell})
            self.positions[identity]=target;self.active.add(identity)
        yield self.env.timeout(duration)
        for identity in ids:self.active.remove(identity)

    def loop_worker(self,cell):
        speed=self.c['loop_m_s'];stock=self.loop_stock[cell]
        while True:
            if self.builders_finished==8 and not self.loop_pending[cell] and not self.loop_merging[cell] and not self.loop_exit_busy[cell]:
                yield from self.loop_advance(cell,speed*speed/2,speed,0.)
                return
            demand=self.loop_demands[cell];identity=stock.get(self.loop_exit)
            if demand and identity and identity.startswith('B') and not self.loop_exit_busy[cell] and self.material[identity]['shade']==demand[0]:
                stock.pop(self.loop_exit);self.loop_demands[cell]=None;self.loop_exit_busy[cell]=True
                self.env.process(self.guarded(self.loop_extract(identity,cell,demand[1])))
            if self.loop_pending[cell] and not self.loop_merging[cell] and ((self.loop_slots-self.merge_ticks)%self.loop_slots not in stock) and sum(v.startswith('B') for v in stock.values())<self.c['loop_capacity']:
                identity,dock,clear,reservation=self.loop_pending[cell];self.loop_pending[cell]=None
                ticks=self.merge_ticks
                stock[(self.loop_slots-ticks)%self.loop_slots]='GAP-'+identity
                process=self.env.process(self.loop_load(identity,cell,clear,reservation))
                self.loop_merging[cell]=[identity,dock,ticks,process]
            yield from self.loop_advance(cell,PITCH,speed,speed)
            moved={(k+1)%self.loop_slots:v for k,v in stock.items()};stock.clear();stock.update(moved)
            joining=self.loop_merging[cell]
            if joining:
                joining[2]-=1
                if not joining[2]:
                    identity,dock,_,process=joining;yield process
                    for k in [k for k,v in stock.items() if v=='GAP-'+identity]:stock.pop(k)
                    if 0 in stock:raise AssertionError('Merge slot occupied')
                    stock[0]=identity;self.loop_merging[cell]=None
                    self.entry_dock[cell].release(dock)
                    shade=self.material[identity]['shade'];self.inventory[cell,shade]+=1
                    self.locate([identity],'accepted_buffer');self.notify()
                    self.emit('loop_admitted',f'cell_{cell}_mix_loop',brick=identity,cell=cell,shade=shade)
            self.loop_peaks[cell]=max(self.loop_peaks[cell],sum(v.startswith('B') for v in stock.values()))

    def intake(self,cell):
        if not self.c.get('batch_row_intake'):
            yield from super().intake(cell);return
        z=self.cell_z[cell];v=self.c['speeds']['transfer_m_s'];tool=f'INFEED-{cell}'
        while True:
            row=yield self.intakes[cell].get()
            with self.inlet[cell].request() as request:
                yield request
                for target,label,speed in [([5.30,BED+.30,z+.3015],'Position wide row paddle',v),([5.6-self.L/2-.012,BED+.30,z+.3015],'Position row slide behind all ten bricks',v),([5.6-self.L/2-.012,BED+.045,z+.3015],'Lower guided row paddle',self.c['speeds']['gantry_z_m_s'])]:
                    yield from self.move([tool],[target],f'cell_{cell}_infeed',label,speed)
                self.emit('row_intake_push',f'cell_{cell}_infeed',cell=cell,ids=row[:])
                yield from self.move(row+[tool],[[5.95,BED+self.H/2,self.positions[i][2]] for i in row]+[[5.95-self.L/2-.012,BED+.045,z+.3015]],f'cell_{cell}_infeed','Transfer all ten bricks in one paddle stroke',v)
                yield from self.move([tool],[[5.95-self.L/2-.012,BED+.30,z+.3015]],f'cell_{cell}_infeed','Raise wide paddle before transverse dosing',self.c['speeds']['gantry_z_m_s'])
                retract=self.env.process(self.move([tool],[[5.30,BED+.30,z+.3015]],f'cell_{cell}_infeed','Return raised rigid X slide',v))
                for number,identity in enumerate(row):
                    entrance=self.inspect_zones[cell][0].request();yield entrance
                    remaining=row[number:]
                    if number:
                        self.emit('transverse_belt_index',f'cell_{cell}_infeed',cell=cell,ids=remaining[:],delta_m=-self.D)
                        yield from self.move(remaining,[[self.positions[i][0],self.positions[i][1],self.positions[i][2]-self.D] for i in remaining],f'cell_{cell}_infeed','Index all occupants of transverse dosing belt',.6)
                    yield from self.move([identity],[[6.4,BED+self.H/2,z]],f'cell_{cell}_infeed','Extract leading brick onto reserved inspection inlet',.6)
                    yield from self.check_piece_alignment(identity,cell)
                    self.env.process(self.guarded(self.inspect(identity,cell,entrance)))
                    yield from self.pause(f'cell_{cell}_infeed','Confirm leading brick clear',self.c['dwell']['sensor_s'])
                yield retract
            yield self.free_cells[cell//2].put(cell)

    def merge_pallet(self,ids,wood,line,pallet,branch_slot):
        moving=ids+[wood];z=self.line_z[line];v=self.c['speeds']['pallet_m_s'];tool='OUTPUT-SHUTTLE'
        with self.merge.request() as request:
            yield request;self.emit('merge_enter','output_merge',line=line,pallet=pallet)
            yield from self.move([tool],[[self.merge_x,.154,z]],'output_merge','Dock empty merge shuttle to waiting branch',v)
            dx=self.merge_x-self.positions[wood][0]
            yield from self.move(moving,[[p[0]+dx,p[1],p[2]] for p in (self.positions[i] for i in moving)],'output_merge','Load supported pallet onto common merge shuttle',v)
            self.branch_slots[line].release(branch_slot)
            slot_z=(len(self.output_cart_load)-1.5)*1.35
            yield from self.move(moving+[tool],[[p[0],p[1],p[2]-z+slot_z] for p in (self.positions[i] for i in moving)]+[[self.merge_x,.154,slot_z]],'output_merge','Translate supported pallet to selected dispatch-cart bay',v)
            yield from self.move(moving,[[p[0]+3.5,p[1],p[2]] for p in (self.positions[i] for i in moving)],'output_merge','Load verified pallet onto common dispatch cart',v)
            self.output_cart_load.append(moving[:]);self.pallets.append(ids[:]);self.shipped.extend(ids);self.locate(ids,'shipped')
            self.delivered_pallets.append({'pallet':pallet,'line':line,'wood':wood,'ids':ids[:],'t':self.env.now})
            self.emit('pallet_released','output_cart',line=line,pallet=pallet,shipped=len(self.shipped))
            self.emit('merge_exit','output_merge',line=line,pallet=pallet);self.outputs_pending-=1;self.notify()
            if len(self.output_cart_load)==4:
                all_ids=[i for pack in self.output_cart_load for i in pack]+['OUTPUT-CART']
                yield from self.move(all_ids,[[p[0]+4.5,p[1],p[2]] for p in (self.positions[i] for i in all_ids)],'output_cart','Dispatch completed output cart to finished-goods bay',self.c['logistics']['cart_m_s'])
                self.output_cart_departed=True;self.emit('output_cart_dispatched','output_cart',pallets=4);self.notify()

    def run(self):
        for cell in range(8):self.env.process(self.guarded(self.loop_worker(cell)))
        return super().run()

    def report(self):
        r=super().report()
        r['mechanics'].update(transfer_revision=17,dispatch_shift_m=self.dispatch_shift,loop_geometry={'x0':X0,'x1':self.loop_end,'radius':R,'pitch':PITCH,'perimeter':2*(self.loop_end-X0)+2*math.pi*R},loop_drives=8,zone_drives=64,zone_controllers=16,surge_belt_drives=0,loop_peaks=self.loop_peaks,inlet_backpressure=self.loop_backpressure)
        r['scope'][1]='One encoder-driven loop per cell; all loop occupants share speed. Synchronized single-slot inlet, fixed selected-tone outlet, finite occupancy. No tone storage conveyors, reserve conveyors or moving grade selectors.'
        return r

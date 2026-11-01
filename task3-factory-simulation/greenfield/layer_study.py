"""Capacity screening for selective layer repair; independent of the kinematic demo.

Synthetic observations, bounded-search mixing and selected repair-cycle assumptions.
This model does NOT certify robot paths, gripping, collisions or plant throughput.
"""
from collections import Counter
import random
import math
import simpy
from .motion import profile


def plan_layer(original, good, previous=(), node_limit=200000):
    """Bounded backtracking: preserve valid accepted positions, prefer balanced tones.

    Feasible heuristic, not a minimum-edit or equal-recipe optimality proof.
    """
    grid=[];counts=[0,0,0];nodes=0
    def search(k):
        nonlocal nodes
        nodes+=1
        if nodes>node_limit:raise ValueError('Mix search budget exceeded; material must remain held')
        if k==40:return True
        row,col=divmod(k,10)
        choices=sorted(range(3),key=lambda shade:(not(good[k] and original[k]==shade),counts[shade],shade))
        for shade in choices:
            if col>=2 and grid[-1]==grid[-2]==shade:continue
            if row>=2 and grid[k-10]==grid[k-20]==shade:continue
            if len(previous)>=2 and previous[-1][k]==previous[-2][k]==shade:continue
            grid.append(shade);counts[shade]+=1
            if search(k+1):return True
            counts[shade]-=1;grid.pop()
        return False
    if not search(0):raise ValueError('No feasible layer mix; material must remain held')
    return grid


def valid_mix(grid,previous=()):
    return not (any(grid[r*10+c]==grid[r*10+c+1]==grid[r*10+c+2] for r in range(4) for c in range(8)) or
        any(grid[r*10+c]==grid[(r+1)*10+c]==grid[(r+2)*10+c] for r in range(2) for c in range(10)) or
        len(previous)>=2 and any(previous[-1][k]==previous[-2][k]==grid[k] for k in range(40)))


def stroke(distance,speed,acceleration=3.):
    return 0. if distance<1e-9 else profile(distance,speed,acceleration)['duration']


def layer_transfer(source_top,xy_distance,target_top=1.319):
    # Same conservative axis speeds as the existing demo: XY 1.0, Z 0.7 m/s.
    # Home->source, down, grip, lift, loaded XY, down, release, retract, home.
    clear=max(2.35,source_top+.15,target_top+.15)
    return (stroke(xy_distance/2,1.)+stroke(2.6-source_top,.7)+.25+
        stroke(clear-source_top,.7)+stroke(xy_distance,1.)+
        stroke(clear-target_top,.7)+.20+stroke(2.6-target_top,.7)+stroke(xy_distance/2,1.))


def synthetic_layers(seed=8,defect_rate=.12,stacks=36):
    rng=random.Random(seed);lines=[[],[]];history=[[],[]]
    for stack in range(stacks):
        line=stack%2
        for h in range(20):
            original=[rng.randrange(3) for _ in range(40)]
            good=[rng.random()>=defect_rate for _ in range(40)]
            if len(lines[line])%14==0:history[line]=[]
            grid=plan_layer(original,good,history[line]);assert valid_mix(grid,history[line])
            history[line].append(grid)
            ids=[f'B{stack*800+h*40+k:05}' for k in range(40)]
            edits=[k for k in range(40) if not good[k] or original[k]!=grid[k]]
            lines[line].append(dict(stack=stack,height=h,ids=ids,original=original,good=good,grid=grid,edits=edits))
    return lines


class LayerRepairStudy:
    def __init__(self,layers,heads=1,repair_cycle_s=5.,availability=1.):
        if heads not in (1,2) or repair_cycle_s<=0 or not 0<availability<=1:raise ValueError('Invalid capacity assumptions')
        self.layers=layers;self.heads=heads;self.cycle=repair_cycle_s;self.availability=availability
        self.env=simpy.Environment();self.bridge=simpy.Resource(self.env,capacity=1)
        self.supply=simpy.Resource(self.env,capacity=1)
        self.input=[simpy.Store(self.env,capacity=2) for _ in range(2)]
        self.output=[simpy.Store(self.env,capacity=2) for _ in range(2)]
        self.bank=[[250]*3 for _ in range(2)];self.initial_spares=1500;self.injected=0
        self.busy=Counter();self.events=[];self.repairs=0;self.defects=0;self.reused_good=0
        self.processed=0;self.shipped=0;self.partial=0;self.pallets=0;self.layer_rows=[]

    def wait(self,stage,duration):
        self.busy[stage]+=duration
        # Explicit effective-time sensitivity; base run has availability=1.
        yield self.env.timeout(duration/self.availability)

    def source(self,line):
        last=None
        for layer in self.layers[line]:
            if layer['stack']!=last:
                with self.bridge.request() as req:
                    yield req;yield from self.wait('shared_stack_delivery',40.)
                last=layer['stack']
            yield from self.wait('dehacker_'+str(line),layer_transfer(.33+(20-layer['height'])*.069,3.))
            yield self.input[line].put(layer)
        yield self.input[line].put(None)

    def correct(self,line):
        while True:
            layer=yield self.input[line].get()
            if layer is None:yield self.output[line].put(None);return
            # Common inspection and spreading time, including confirmations.
            yield from self.wait('inspection_spread_'+str(line),1.+2.)
            workloads=[sum(k%10<5 for k in layer['edits']),sum(k%10>=5 for k in layer['edits'])] if self.heads==2 else [len(layer['edits'])]
            # Heads have disjoint column territories; whole remove phase precedes replacement.
            for head,n in enumerate(workloads):self.busy[f'repair_head_{line}_{head}']+=n*self.cycle
            yield self.env.timeout(max(workloads,default=0)*self.cycle/(2*self.availability))
            for k in layer['edits']:
                self.repairs+=1
                if layer['good'][k]:self.bank[line][layer['original'][k]]+=1;self.reused_good+=1
                else:self.defects+=1
            for k in layer['edits']:
                shade=layer['grid'][k]
                if not self.bank[line][shade]:
                    with self.supply.request() as req:
                        yield req;yield from self.wait('verified_spare_replenishment',30.)
                        self.bank[line][shade]+=100;self.injected+=100
                self.bank[line][shade]-=1
            if max(self.bank[line])>500:raise RuntimeError('Finite good-stock lane full; redesign replenishment/mix')
            yield self.env.timeout(max(workloads,default=0)*self.cycle/(2*self.availability))
            yield from self.wait('inspection_spread_'+str(line),2.+.5)
            self.processed+=40;self.layer_rows.append({'line':line,'stack':layer['stack'],'height':layer['height'],'edits':len(layer['edits']),'changed_slots':layer['edits'],'original_shades':layer['original'],'original_good':layer['good'],'grid':layer['grid'],'completed_s':self.env.now})
            yield self.output[line].put(layer)

    def stack(self,line):
        fill=0
        yield from self.wait('pallet_change_'+str(line),18.)
        while True:
            layer=yield self.output[line].get()
            if layer is None:self.partial+=fill*40;return
            yield from self.wait('stacker_'+str(line),layer_transfer(1.319,3.)+stroke(.069,.12,.3)+.4)
            fill+=1
            if fill==14:
                self.shipped+=560;self.pallets+=1;fill=0
                self.events.append({'kind':'pallet_released','line':line,'t':self.env.now,'shipped':self.shipped})
                yield from self.wait('pallet_change_'+str(line),18.)

    def run(self):
        workers=[self.env.process(f(i)) for i in range(2) for f in (self.source,self.correct,self.stack)]
        self.env.run(until=self.env.all_of(workers))
        total=sum(len(l)*40 for l in self.layers);bank=sum(map(sum,self.bank))
        assert total+self.initial_spares+self.injected==self.shipped+self.partial+self.defects+bank
        return {'status':'completed','input_bricks':total,'processed_bricks':self.processed,'shipped_bricks':self.shipped,'partial_bricks':self.partial,'full_pallets':self.pallets,'seconds':self.env.now,'shipped_bph':self.shipped*3600/self.env.now,'equipment_counts':{'dehackers':2,'repair_stations':2,'repair_heads':2*self.heads,'guided_palletizers':2},'timing_assumptions':{'full_repair_s':self.cycle,'inspection_s':1.,'spread_s':2.,'close_s':2.,'final_check_s':.5,'stack_delivery_s':40.,'pallet_change_s':18.,'spare_batch':100,'spare_replenishment_s':30.,'xy_m_s':1.,'z_m_s':.7,'axis_acceleration_m_s2':3.,'layer_xy_transfer_m':3.},'heads_per_station':self.heads,'repair_cycle_s':self.cycle,'availability_factor':self.availability,'repaired_positions':self.repairs,'rejected_bricks':self.defects,'good_bricks_returned_to_stock':self.reused_good,'initial_spares':self.initial_spares,'replenished_spares':self.injected,'final_spare_stock':bank,'material_balance_ok':True,'stage_busy_seconds':dict(self.busy),'layers':self.layer_rows,'events':self.events,'scope':'Capacity screening only: no robot-path, gripper, dynamic collision or detection-accuracy validation. Spreading, repair cycle, supply and pallet-change times are selected assumptions. Two heads use disjoint column territories; no shared-workspace scheduling. Output partials remain in separate lines.'}

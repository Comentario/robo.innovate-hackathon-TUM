"""Two independent four-cell lines sharing inventory delivery and final dispatch.

The class reuses the cell/perception contracts; only plant logistics differ.
"""
from collections import Counter
import math
import simpy
from .model import Plant, Hold, BED


class RoutedStore:
    def __init__(self, stores, route):self.stores=stores;self.route=route
    def put(self,item):return self.stores[self.route(item)].put(item)


class TwinPlant(Plant):
    def __init__(self,config):
        if config['input_stacks'] not in (2,4):raise ValueError('Dual inventory contains two or four input stacks')
        if config['cells']!=8:raise ValueError('Dual layout has two lines of four cells')
        log=config['logistics']
        if type(log['discard_cart_capacity']) is not int or not 1<=log['discard_cart_capacity']<=240:raise ValueError('Discard cart geometry supports 1..240 pieces')
        if type(log['discard_carts_per_line']) is not int or not 1<=log['discard_carts_per_line']<=4:raise ValueError('Service lanes support one to four discard carts per line')
        for key in ('cart_m_s','bridge_xy_m_s','bridge_z_m_s','fork_tool_kg','bridge_capacity_kg','rail_cart_capacity_kg','unload_service_s'):
            if not math.isfinite(log[key]) or log[key]<=0:raise ValueError('Positive finite logistics inputs required')
        self.line_z=[-8.0,8.0];self.lines=2
        self.tool_homes={f'{kind}_{line}':[1.5 if kind=='dehack' else 21+(config['buffer_cells_per_shade']-20)*.3,2.6,z]
                         for line,z in enumerate(self.line_z) for kind in ('dehack','stacker')}
        super().__init__(config)
        self.bridge=simpy.Resource(self.env,capacity=1);self.inventory_arrived=self.env.event()
        self.input_empties=[[],[]];self.source_done=0;self.outputs_pending=0;self.discard_pending=0;self.services_pending=0
        self.merge=simpy.Resource(self.env,capacity=1)
        self.branch_slots=[simpy.Resource(self.env,capacity=1) for _ in range(2)]
        self.line_layers=[simpy.Store(self.env) for _ in range(2)]
        self.full_layers=RoutedStore(self.line_layers,lambda item:item[0]//4)
        self.line_trays=[simpy.Store(self.env) for _ in range(2)]
        for line,store in enumerate(self.line_trays):store.items.extend((bay,nest) for bay in range(line*2,line*2+2) for nest in (0,1))
        self.tray_slots=RoutedStore(self.line_trays,lambda item:item[0]//2)
        self.collectors={(line,side,k):simpy.Resource(self.env,capacity=1) for line in range(2) for side in (-1,1) for k in range(1,26)}
        self.cart_inlet=[simpy.Resource(self.env,capacity=1) for _ in range(2)]
        self.cart_index=[0,0];self.discard_carts=[]
        self.cart_payloads={f'DISCARD-CART-{line}-{n}':[] for line in range(2) for n in range(self.c['logistics']['discard_carts_per_line'])}
        self.cart_pack=[self.cart_payloads[f'DISCARD-CART-{line}-0'] for line in range(2)]
        self.empty_carts=[simpy.Store(self.env) for _ in range(2)];self.staging_lock=[simpy.Resource(self.env,capacity=1) for _ in range(2)]
        for store in self.empty_carts:store.items.extend(range(1,self.c['logistics']['discard_carts_per_line']))
        self.disposal_ids=[[],[]]
        self.delivered_pallets=[];self.output_cart_load=[];self.output_cart_departed=False
        self.line_pack_layers=[[],[]]
        self.input_stack_mass=800*self.c['brick_mass_kg']+25
        if self.input_stack_mass+self.c['logistics']['fork_tool_kg']>self.c['logistics']['bridge_capacity_kg']:
            raise ValueError('Full-stack bridge payload exceeded')
        if self.c['input_stacks']*self.input_stack_mass+1000>self.c['logistics']['rail_cart_capacity_kg']:
            raise ValueError('Inventory rail cart payload exceeded')

    def _material(self):
        super()._material()
        for identity,b in self.material.items():
            stack=int(identity[1:])//800;p=self.positions[identity]
            p=[p[0]-9,p[1]+.18,p[2]-stack*1.2+(stack-(self.c['input_stacks']-1)/2)*1.35]
            self.positions[identity]=p[:];self.initial[identity]=p[:]
        for key in ('GUIDE-GATE','TOOL-dehack','TOOL-stacker'):
            self.aux.pop(key);self.positions.pop(key);self.initial.pop(key)
        for stack in range(self.c['input_stacks']):
            key=f'P-IN-{stack}';p=[-12,.26,(stack-(self.c['input_stacks']-1)/2)*1.35]
            self.positions[key]=p[:];self.initial[key]=p[:]
        for key in [i for i in self.aux if i.startswith('P-OUT-')]:
            self.aux.pop(key);self.positions.pop(key);self.initial.pop(key)
        x=21+self.tail_shift
        for line,z in enumerate(self.line_z):
            side=-1 if line==0 else 1
            self.add_aux(f'GUIDE-GATE-{line}',[x,2.31,z],'guide_gate')
            for kind in ('dehack','stacker'):self.add_aux(f'TOOL-{kind}_{line}',self.tool_homes[f'{kind}_{line}'],'tool')
            for number in range(4):
                self.add_aux(f'P-OUT-{2*number+line}',[x,.214,z+side*(3+number*1.35)],'pallet')
            for number in range(self.c['logistics']['discard_carts_per_line']):
                p=[5.8,0,z] if number==0 else [1.6,0,z-side*number*1.4]
                self.add_aux(f'DISCARD-CART-{line}-{number}',p,'discard_cart')
        self.add_aux('KILN-CART',[-12,0,0],'kiln_cart')
        self.add_aux('INVENTORY-FORK',[-9.2,3.48,0],'pallet_fork')
        self.add_aux('OUTPUT-SHUTTLE',[28,.154,0],'pallet_shuttle')
        self.add_aux('OUTPUT-CART',[31.5,0,0],'output_cart')
        for cell,z in enumerate(self.cell_z):
            key=f'INFEED-{cell}';self.positions[key]=[5.30,BED+.30,z];self.initial[key]=self.positions[key][:]

    def inventory_delivery(self):
        ids=list(self.material)+[f'P-IN-{s}' for s in range(self.c['input_stacks'])]+['KILN-CART']
        yield from self.move(ids,[[p[0]+4,p[1],p[2]] for p in (self.positions[i] for i in ids)],'inventory_cart','Rail inventory cart arrives at pickup bay',self.c['logistics']['cart_m_s'])
        self.emit('inventory_arrived','inventory_cart',stacks=self.c['input_stacks']);self.inventory_arrived.succeed()

    def deliver_stack(self,stack,line):
        tool='INVENTORY-FORK';v=self.c['logistics']['bridge_xy_m_s'];vz=self.c['logistics']['bridge_z_m_s'];z=self.line_z[line]
        ids=[f'B{i:05}' for i in range(stack*800,(stack+1)*800)]+[f'P-IN-{stack}']
        source=self.positions[f'P-IN-{stack}'][:];p=self.positions[tool][:]
        yield from self.move([tool],[[p[0],3.48,p[2]]],'inventory_bridge','Raise empty fork to travel plane',vz)
        yield from self.move([tool],[[source[0]-1.45,3.48,source[2]]],'inventory_bridge','Approach inventory from fork-pocket side',v)
        yield from self.move([tool],[[source[0]-1.45,source[1]+.02,source[2]]],'inventory_bridge','Lower fork outside the stack',vz)
        yield from self.move([tool],[[source[0],source[1]+.02,source[2]]],'inventory_bridge','Insert fork into pallet pockets',v)
        self.emit('retention_command','inventory_bridge',closed=True,duration=.6)
        yield from self.pause('inventory_bridge','Close retention net and confirm load secured',.6)
        self.emit('bulk_attach','inventory_bridge',stack=stack,line=line)
        lift=3.46-source[1]
        yield from self.move(ids+[tool],[[self.positions[i][0],self.positions[i][1]+lift,self.positions[i][2]] for i in ids]+[[source[0],3.48,source[2]]],'inventory_bridge','Lift complete 800-brick stack above local gantries',vz)
        dx=-source[0];dz=z-source[2]
        yield from self.move(ids+[tool],[[self.positions[i][0]+dx,self.positions[i][1],self.positions[i][2]+dz] for i in ids]+[[0,3.48,z]],'inventory_bridge',f'Transfer retained stack to dehacking line {line+1}',v)
        yield from self.move(ids+[tool],[[self.positions[i][0],self.positions[i][1]-3.2,self.positions[i][2]] for i in ids]+[[0,.28,z]],'inventory_bridge','Lower stack onto receiving dock',vz)
        self.emit('retention_command','inventory_bridge',closed=False,duration=.6)
        yield from self.pause('inventory_bridge','Retract retention screens after dock load confirmation',.6)
        self.emit('stack_delivered','inventory_bridge',stack=stack,line=line)
        yield from self.move([tool],[[-1.45,.28,z]],'inventory_bridge','Withdraw empty fork from pallet pockets',v)
        yield from self.move([tool],[[-1.45,3.48,z]],'inventory_bridge','Retract fork clear of production',vz)

    def source_line(self,line):
        yield self.inventory_arrived
        count=0;z=self.line_z[line];speed=self.c['speeds']
        for local_stack,stack in enumerate(range(line,self.c['input_stacks'],2)):
            with self.bridge.request() as request:
                yield request;yield from self.deliver_stack(stack,line)
            for layer in range(20):
                due=count*self.n*3600*2/self.c['input_bricks_per_hour']
                if self.env.now<due:yield self.env.timeout(due-self.env.now)
                bay,nest=yield self.line_trays[line].get()
                ids=[f'B{i:05}' for i in range(stack*800+layer*40,stack*800+(layer+1)*40)]
                for identity in ids:self.material[identity]['bay']=bay;self.material[identity]['line']=line
                zz=self.bay_z[bay]+(nest-.5)*1.1
                yield from self.carry(ids,[self.pose(3,BED+self.H/2,zz,k) for k in range(40)],f'dehack_{line}','Unload single layer')
                self.stats['unloaded_bricks']+=40;self.locate(ids,'tray')
                self.emit('layer_unloaded',f'dehack_{line}',line=line,layer=stack*20+layer,bay=bay,nest=nest,ids=ids)
                yield self.layers[bay].put((stack*20+layer,nest,ids));count+=1
            wood=f'P-IN-{stack}';previous=self.input_empties[line]
            if previous:
                yield from self.move(previous,[[p[0]-1.35,p[1],p[2]] for p in (self.positions[i] for i in previous)],f'input_return_{line}','Advance returned empty pallets before admitting another',speed['pallet_m_s'])
            yield from self.move([wood],[[-3,.26,z]],f'input_return_{line}','Return empty input pallet on straight roller lane',speed['pallet_m_s'])
            self.input_empties[line].append(wood)
        self.source_done+=1;self.source_finished=self.source_done==2;self.emit('source_finished',f'dehack_{line}',line=line);self.notify()

    def intake(self,cell):
        z=self.cell_z[cell];v=self.c['speeds']['transfer_m_s'];tool=f'INFEED-{cell}'
        while True:
            row=yield self.intakes[cell].get()
            for identity in row:
                with self.inlet[cell].request() as request:
                    yield request;entrance=self.inspect_zones[cell][0].request();yield entrance
                    p=self.positions[identity][:]
                    yield from self.move([tool],[[5.30,BED+.30,p[2]]],f'cell_{cell}_infeed','Traverse raised pusher behind incoming row',v)
                    yield from self.move([tool],[[5.6-self.L/2-.012,BED+.045,p[2]]],f'cell_{cell}_infeed','Lower paddle behind rear face with clear approach',v)
                    yield from self.move([identity,tool],[[5.95,p[1],p[2]],[5.95-self.L/2-.012,BED+.045,p[2]]],f'cell_{cell}_infeed','Pusher singulates one brick',v)
                    yield from self.move([tool],[[5.30,BED+.30,p[2]]],f'cell_{cell}_infeed','Lift and retract paddle above row loading envelope',v)
                    yield from self.move([identity],[[5.95,p[1],z]],f'cell_{cell}_infeed','Align separated brick with lane',v)
                    yield from self.move([identity],[[6.4,BED+self.H/2,z]],f'cell_{cell}_infeed','Meter across connected roller bridge',v)
                    self.env.process(self.guarded(self.inspect(identity,cell,entrance)))
                    yield from self.pause(f'cell_{cell}_infeed','Maintain inspection pitch',.3/self.c['speeds']['belt_m_s'])
            yield self.free_cells[cell//2].put(cell)

    def discard(self,identity,cell,decision,inspection_reservation):
        self.discard_pending+=1;line=cell//4;z=self.cell_z[cell];center=self.line_z[line]
        side=1 if z+1.25>=center else -1;k=min(25,max(1,round(abs(z+1.25-center)/.3)))
        resource=self.collectors[line,side,k];reservation=resource.request();yield reservation
        v=self.c['speeds']['transfer_m_s'];tool=f'REJECT-PUSHER-{cell}'
        yield from self.move([identity,tool],[[9,BED+self.H/2,z+1.25],[9,BED+.045,z+1.25-self.D/2-.012]],f'cell_{cell}_router','Side pusher sends non-approved brick to common discard',v)
        yield from self.move([tool],[[9,BED+.045,z-self.D/2-.012]],f'cell_{cell}_router','Retract guided side ejector',v)
        yield from self.move([identity],[[7.06,.65,center+side*k*.3]],f'cell_{cell}_router','Travel down supported full-length discard chute',.6)
        yield from self.move([identity],[[6.8,.65,center+side*k*.3]],f'cell_{cell}_router','Enter flush collector receiving rollers',.6)
        self.material[identity]['location']='discard_transit';self.material[identity]['discard_reason']=decision
        self.inspect_zones[cell][-1].release(inspection_reservation);self.notify()
        self.env.process(self.guarded(self.collect_discard(identity,line,side,k,reservation)))

    def collect_discard(self,identity,line,side,k,reservation):
        center=self.line_z[line]
        while k>1:
            next_resource=self.collectors[line,side,k-1];nxt=next_resource.request();yield nxt
            yield from self.move([identity],[[6.8,.65,center+side*(k-1)*.3]],f'discard_conveyor_{line}','Advance reserved discard collection zone',.6)
            self.collectors[line,side,k].release(reservation);k-=1;reservation=nxt
        with self.cart_inlet[line].request() as request:
            yield request
            if len(self.cart_pack[line])>=self.c['logistics']['discard_cart_capacity']:yield from self.swap_discard_cart(line)
            yield from self.move([identity],[[6.8,.65,center]],f'discard_conveyor_{line}','Enter interlocked common cart inlet',.6)
            self.collectors[line,side,1].release(reservation)
            cart=f'DISCARD-CART-{line}-{self.cart_index[line]}';number=len(self.cart_pack[line])
            target=[5.8+(number%4-1.5)*.26,.25+self.H/2+(number//40)*self.H,center+((number//4)%10-4.5)*.075]
            yield from self.move([identity],[target],f'discard_cart_{line}','Contained discard cart collection; settling abstracted',1.0)
            reason=self.material[identity]['discard_reason'];self.material[identity]['location']=reason
            self.cart_pack[line].append(identity);self.emit('routed',f'discard_cart_{line}',brick=identity,destination=reason,line=line,cart=cart)
            self.discard_pending-=1;self.notify()

    def swap_discard_cart(self,line):
        if not self.c['logistics'].get('discard_collection_available',True):raise Hold('Discard cart collection unavailable; upstream interlocked')
        number=self.cart_index[line];z=self.line_z[line];side=-1 if line==0 else 1
        old=f'DISCARD-CART-{line}-{number}';ids=self.cart_pack[line][:];moving=ids+[old];v=self.c['logistics']['cart_m_s']
        self.emit('cart_gate_command',f'discard_cart_{line}',cart=old,opened=False,duration=.4)
        yield from self.pause(f'discard_cart_{line}','Close cart gate before collection',.4)
        self.emit('cart_route_state',f'discard_cart_{line}',cart=old,state='Loaded departure',line=line)
        self.emit('discard_swap_start',f'discard_cart_{line}',line=line,cart=old,bricks=len(ids))
        yield from self.move(moving,[[p[0]-4.2,p[1],p[2]] for p in (self.positions[i] for i in moving)],f'discard_cart_{line}','Collect loaded discard cart into service lane',v)
        yield from self.move(moving,[[p[0],p[1],p[2]+side*1.4] for p in (self.positions[i] for i in moving)],f'discard_cart_{line}','Clear cart exchange intersection',v)
        self.discard_carts.append({'id':old,'line':line,'ids':ids});self.services_pending+=1
        self.env.process(self.guarded(self.remove_cart(moving,line,number)))
        while True:
            with self.staging_lock[line].request() as request:
                yield request
                if self.empty_carts[line].items:
                    next_number=yield self.empty_carts[line].get();empty=f'DISCARD-CART-{line}-{next_number}'
                    yield from self.move([empty],[[1.6,0,z]],f'discard_cart_{line}','Bring replacement cart to service junction',v)
                    remaining=[f'DISCARD-CART-{line}-{n}' for n in self.empty_carts[line].items]
                    if remaining:yield from self.move(remaining,[[p[0],p[1],p[2]+side*1.4] for p in (self.positions[i] for i in remaining)],f'discard_cart_{line}','Advance empty-cart queue without overtaking',v)
                    break
            yield self.changed | self.env.timeout(.25)
        yield from self.move([empty],[[5.8,0,z]],f'discard_cart_{line}','Dock empty discard cart',v)
        self.cart_index[line]=next_number;self.cart_pack[line]=self.cart_payloads[empty]
        self.emit('cart_gate_command',f'discard_cart_{line}',cart=empty,opened=True,duration=.4)
        yield from self.pause(f'discard_cart_{line}','Open receiving gate after cart-present confirmation',.4)
        self.emit('cart_route_state',f'discard_cart_{line}',cart=empty,state='Receiving dock confirmed',line=line)
        self.emit('discard_swap_complete',f'discard_cart_{line}',line=line,cart=empty);self.notify()

    def remove_cart(self,moving,line,number):
        z=self.line_z[line];side=-1 if line==0 else 1;cart=moving[-1];ids=moving[:-1];v=self.c['logistics']['cart_m_s'];depot=z+side*11
        dz=depot-self.positions[cart][2]
        yield from self.move(moving,[[p[0],p[1],p[2]+dz] for p in (self.positions[i] for i in moving)],f'cart_collection_{line}','Transport loaded cart to designated unloading area',v)
        yield from self.pause(f'cart_collection_{line}','Automatic depot docking sensor confirmation',.25)
        self.emit('cart_route_state',f'cart_collection_{line}',cart=cart,state='Automatic unloading',line=line)
        self.emit('discard_cart_removed',f'cart_collection_{line}',line=line,cart=cart)
        self.emit('cart_gate_command',f'cart_collection_{line}',cart=cart,opened=True,duration=.4)
        yield from self.pause(f'cart_collection_{line}','Open cart gate inside unloading area',.4)
        yield from self.pause(f'cart_collection_{line}','Collection-area unloading service; internal handling abstracted',self.c['logistics']['unload_service_s'])
        start=len(self.disposal_ids[line])
        targets=[[4.1+((start+k)%4-1.5)*.26,.25+self.H/2+((start+k)//40)*self.H,depot+(((start+k)//4)%10-4.5)*.075] for k in range(len(ids))]
        yield from self.move(ids,targets,f'cart_collection_{line}','Contained disposal area unloading; settling abstracted',.5)
        self.emit('cart_gate_command',f'cart_collection_{line}',cart=cart,opened=False,duration=.4)
        yield from self.pause(f'cart_collection_{line}','Close empty cart gate before return',.4)
        self.disposal_ids[line].extend(ids);self.cart_payloads[cart].clear()
        self.emit('discard_cart_emptied',f'cart_collection_{line}',line=line,cart=cart,bricks=len(ids))
        self.emit('cart_route_state',f'cart_collection_{line}',cart=cart,state='Empty return',line=line)
        # Empty carts return on a separate lane; the FIFO queue never overtakes.
        yield from self.move([cart],[[3.0,0,depot]],f'cart_collection_{line}','Transfer empty cart onto return lane',v)
        with self.staging_lock[line].request() as request:
            yield request
            target_z=z-side*(len(self.empty_carts[line].items)+1)*1.4
            yield from self.move([cart],[[3.0,0,target_z]],f'cart_collection_{line}','Return empty cart behind queued spares',v)
            yield from self.move([cart],[[1.6,0,target_z]],f'cart_collection_{line}','Park empty cart at tail of spare queue',v)
            yield self.empty_carts[line].put(number)
        yield from self.pause(f'cart_collection_{line}','Automatic spare-bay presence confirmation',.25)
        self.emit('cart_route_state',f'cart_collection_{line}',cart=cart,state='Available spare',line=line)
        self.emit('discard_cart_returned',f'cart_collection_{line}',line=line,cart=cart);self.services_pending-=1;self.notify()

    def prepare_pallet(self,line,index):
        x=21+self.tail_shift;z=self.line_z[line];wood=f'P-OUT-{line+2*index}';gate=f'GUIDE-GATE-{line}'
        yield from self.move([wood],[[x,.214,z]],f'pallet_in_{line}','Feed empty wooden pallet into open guided well',self.c['speeds']['pallet_m_s'])
        yield from self.move([wood],[[x,BED-.07,z]],f'elevator_{line}','Raise wooden pallet to initial layer support plane',self.c['speeds']['elevator_m_s'])
        yield from self.move([gate],[[x,.91,z]],f'guide_gate_{line}','Close guide frame after pallet confirmation',.3)
        self.emit('gate_closed_confirmed',f'guide_gate_{line}',line=line)

    def stacker_line(self,line):
        speed=self.c['speeds'];dwell=self.c['dwell'];x=21+self.tail_shift;z=self.line_z[line];pack=[];pallet_index=0;matrix=[]
        yield from self.prepare_pallet(line,0)
        while True:
            cell,index,ids,pickup=yield self.line_layers[line].get()
            target=[[x+(1.5-k//10)*self.L,BED+self.H/2,z+(k%10-4.5)*self.D] for k in range(40)]
            if self.c['faults']['critical_sensor_layer']==index:
                yield from self.pause(f'stacker_{line}','Bounded source confirmation timeout',2)
                raise Hold('Layer source confirmation missing; motion inhibited, material retained')
            error=self.c['faults']['alignment_error_m'] if index==self.c['faults']['alignment_layer'] else 0
            if error:target=[[p[0]+error,p[1],p[2]] for p in target]
            yield from self.carry(ids,target,f'stacker_{line}','Transfer mixed layer to guided well')
            pickup.succeed();self.notify();self.locate(ids,'alignment_hold')
            self.emit('alignment_check',f'stacker_{line}',line=line,layer=index,error_m=error)
            if abs(error)>.012:raise Hold('Alignment outside bounded correction travel')
            if error:
                self.emit('recovery_start',f'stacker_{line}',line=line,reason='Layer offset detected',layer=index)
                yield from self.move(ids,[[p[0]-error,p[1],p[2]] for p in target],f'stacker_{line}','Guided layer re-centering',.02)
                self.stats['recoveries']+=1;self.emit('recovery_complete',f'stacker_{line}',line=line,layer=index)
            yield from self.pause(f'stacker_{line}','Centering and supported position confirmation',dwell['centering_s'])
            matrix.append(ids[:]);pack.extend(ids);self.placed.extend(ids);self.locate(ids,'partial_pallet');self.produced_layers+=1
            moving=pack+[f'P-OUT-{line+2*pallet_index}']
            yield from self.move(moving,[[p[0],p[1]-self.H,p[2]] for p in (self.positions[i] for i in moving)],f'elevator_{line}','Lower supported pallet one layer pitch',speed['elevator_m_s'])
            self.emit('layer_stacked',f'stacker_{line}',line=line,layer=index,placed=len(self.placed),pack_fill=len(pack),pallet=line+2*pallet_index,deck_y=BED-len(pack)/40*self.H)
            if len(pack)==560:
                vertical=sum(len({self.material[row[k]]['shade'] for row in matrix})==1 for k in range(40))
                if vertical:raise Hold('Pallet spatial mix verification failed; material retained')
                self.pallet_mix.append({'pallet':line+2*pallet_index,'line':line,'counts':dict(Counter(self.material[i]['shade'] for i in pack)),'monochrome_vertical_columns':vertical})
                slot=self.branch_slots[line].request();yield slot
                gate=f'GUIDE-GATE-{line}'
                yield from self.move([gate],[[x,2.31,z]],f'guide_gate_{line}','Raise guide frame clear of outgoing pallet',.3)
                self.emit('gate_open_confirmed',f'guide_gate_{line}',line=line)
                yield from self.move(moving,[[p[0]+2.5,p[1],p[2]] for p in (self.positions[i] for i in moving)],f'pallet_out_{line}','Discharge verified pallet to independent branch buffer',speed['pallet_m_s'])
                self.locate(pack,'output_transit');self.outputs_pending+=1
                self.emit('line_pack_released',f'pallet_out_{line}',line=line,pallet=line+2*pallet_index)
                self.env.process(self.guarded(self.merge_pallet(pack[:],moving[-1],line,line+2*pallet_index,slot)))
                pallet_index+=1;pack=[];matrix=[]
                yield from self.prepare_pallet(line,pallet_index)
            self.notify()

    def merge_pallet(self,ids,wood,line,pallet,branch_slot):
        moving=ids+[wood];z=self.line_z[line];v=self.c['speeds']['pallet_m_s'];tool='OUTPUT-SHUTTLE'
        with self.merge.request() as request:
            yield request;self.emit('merge_enter','output_merge',line=line,pallet=pallet)
            yield from self.move([tool],[[28,.154,z]],'output_merge','Dock empty merge shuttle to waiting branch',v)
            dx=28-self.positions[wood][0]
            yield from self.move(moving,[[p[0]+dx,p[1],p[2]] for p in (self.positions[i] for i in moving)],'output_merge','Load supported pallet onto common merge shuttle',v)
            self.branch_slots[line].release(branch_slot)
            slot_z=(len(self.output_cart_load)-1.5)*1.35
            yield from self.move(moving+[tool],[[p[0],p[1],p[2]-z+slot_z] for p in (self.positions[i] for i in moving)]+[[28,.154,slot_z]],'output_merge','Translate supported pallet to selected dispatch-cart bay',v)
            yield from self.move(moving,[[p[0]+3.5,p[1],p[2]] for p in (self.positions[i] for i in moving)],'output_merge','Load verified pallet onto common dispatch cart',v)
            self.output_cart_load.append(moving[:]);self.pallets.append(ids[:]);self.shipped.extend(ids);self.locate(ids,'shipped')
            self.delivered_pallets.append({'pallet':pallet,'line':line,'wood':wood,'ids':ids[:],'t':self.env.now})
            self.emit('pallet_released','output_cart',line=line,pallet=pallet,shipped=len(self.shipped))
            self.emit('merge_exit','output_merge',line=line,pallet=pallet);self.outputs_pending-=1;self.notify()
            if len(self.output_cart_load)==4:
                all_ids=[i for pack in self.output_cart_load for i in pack]+['OUTPUT-CART']
                yield from self.move(all_ids,[[p[0]+4.5,p[1],p[2]] for p in (self.positions[i] for i in all_ids)],'output_cart','Dispatch completed output cart to finished-goods bay',self.c['logistics']['cart_m_s'])
                self.output_cart_departed=True;self.emit('output_cart_dispatched','output_cart',pallets=4);self.notify()

    def monitor(self):
        while True:
            if (self.source_finished and self.inspected==len(self.material) and self.builders_finished==8 and
                self.produced_layers==len(self.layer_results) and not self.outputs_pending and not self.discard_pending and
                not self.services_pending and not self.active and not self.pending_steps):
                if self.output_cart_load and not self.output_cart_departed:
                    all_ids=[i for pack in self.output_cart_load for i in pack]+['OUTPUT-CART']
                    yield from self.move(all_ids,[[p[0]+4.5,p[1],p[2]] for p in (self.positions[i] for i in all_ids)],'output_cart','Dispatch partially occupied cart at completed-batch closeout',self.c['logistics']['cart_m_s'])
                    self.output_cart_departed=True;self.emit('output_cart_dispatched','output_cart',pallets=len(self.output_cart_load));self.notify()
                self.status='completed_with_residual_stock';self.done.succeed();return
            yield self.changed | self.env.timeout(.25)

    def run(self):
        processes=[self.inventory_delivery(),self.monitor(),*(self.source_line(i) for i in range(2)),*(self.stacker_line(i) for i in range(2)),
                   *(self.feeder(i) for i in range(4)),*(self.intake(i) for i in range(8)),*(self.builder(i) for i in range(8))]
        for process in processes:self.env.process(self.guarded(process))
        self.env.run(until=self.done|self.env.timeout(self.c['max_simulation_seconds']))
        if self.status=='running':self.status='safe_hold';self.reason='Process horizon reached with material retained'
        self.emit('run_finished',status=self.status,reason=self.reason);return self.report()

    def report(self):
        r=super().report();r['schema_version']='3.0';r['concept']='Dual-line autonomous dehacking'
        r['mechanics'].update(line_z=self.line_z,layout='dual',collector_x=6.8,collector_y=.65)
        r['discard_cart_state']=[{'id':f'DISCARD-CART-{line}-{n}','line':line,'capacity':self.c['logistics']['discard_cart_capacity'],
            'ids':self.cart_payloads[f'DISCARD-CART-{line}-{n}'][:]}
            for line in range(2) for n in range(self.c['logistics']['discard_carts_per_line'])]
        r['disposal_ids']=self.disposal_ids
        r['kpis']['discard_carts_emptied']=sum(e['kind']=='discard_cart_emptied' for e in self.events)
        r['delivered_pallets']=self.delivered_pallets;r['discard_carts']=self.discard_carts
        r['kpis']['discard_bricks']=r['kpis']['reject_bricks']+r['kpis']['quarantine_bricks']
        r['kpis']['discard_cart_exchanges']=sum(e['kind']=='discard_swap_complete' for e in self.events)
        r['kpis']['output_cart_dispatched']=self.output_cart_departed
        r['scope'][:1]=['The batch represents four stacks, not the full 36-stack industrial kiln cart; the 800/560-brick stack/pallet interfaces are preserved.','One common discard stream for off-spec and unresolved observations; the reason remains in the trace. No automatic reinsertion.',
            'Discard carts follow an autonomous concept route: interlocked exchange, automatic unloading, separate empty return, FIFO spare docking and presence confirmation. No operator is modeled; industrial AGV navigation and contact dynamics require qualification.',
            'Internal settling inside enclosed carts is abstracted, not contact-simulated. Bulk fork, rail carts and full-stack crane require separate load validation.']
        for layer in r['layers']:layer['line']=layer['cell']//4
        return r

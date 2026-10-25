"""Same-height reversible surge belts; reuse the existing horizontal sorter.

One short belt per observed shade. All stored pieces shift together. No aerial
picker, individual-pocket teleport or unbounded storage is used.
"""
class ReversibleSurge:
    def surge_z(self,cell,shade):
        return self.cell_z[cell]+1.55+.4*self.c['shades'].index(shade)

    def surge_shift(self,cell,shade,delta,extra=None):
        ids=self.surge_stock[cell,shade][:]
        if extra is not None and extra not in ids:ids.append(extra)
        if ids:
            self.emit('surge_belt_index',f'cell_{cell}_surge',cell=cell,shade=shade,ids=ids,delta_m=delta)
            yield from self.move(ids,[[self.positions[i][0]+delta,self.positions[i][1],self.positions[i][2]] for i in ids],f'cell_{cell}_surge','Index entire reversible surge belt',self.c.get('surge_belt_m_s',.3))

    def surge_return(self,cell,shade):
        # Caller owns the physical sorter, including entry/exit bridges.
        stock=self.surge_stock[cell,shade];resource=self.queue_cells[cell,shade][0]
        if not stock or resource.count or resource.queue:return False
        reservation=resource.request();yield reservation
        identity=stock[0];tool=f'SORTER-{cell}';bed=self.initial[tool][1];z=self.surge_z(cell,shade);lane_z=self.cell_z[cell]+self.c['shades'].index(shade)-1;v=self.c['speeds']['transfer_m_s']
        yield from self.move([tool],[[9.45,bed,z]],f'cell_{cell}_surge','Dock horizontal selector at surge belt',v)
        yield from self.surge_shift(cell,shade,-.7)
        stock.pop(0);yield from self.surge_shift(cell,shade,.4)
        yield from self.move([identity,tool],[[9.45,bed+self.H/2,lane_z],[9.45,bed,lane_z]],f'cell_{cell}_surge','Return approved stock at conveyor height',v)
        yield from self.move([identity],[[10.15,bed+self.H/2,lane_z]],f'cell_{cell}_surge','Discharge returned stock onto reserved tone zone',min(v,.6))
        self.inventory[cell,shade]+=1;self.locate([identity],'accepted_buffer');self.emit('surge_returned',f'cell_{cell}_surge',brick=identity,shade=shade,cell=cell);self.notify()
        self.env.process(self.guarded(self.buffer(identity,cell,shade,reservation)))
        return True

    def surge_store(self,identity,cell,shade,inspection_reservation):
        # Called with the sorter already reserved by the routing process.
        stock=self.surge_stock[cell,shade];limit=self.c['surge_slots_per_shade'];tool=f'SORTER-{cell}';bed=self.initial[tool][1];z=self.cell_z[cell];target_z=self.surge_z(cell,shade);v=self.c['speeds']['transfer_m_s']
        while len(stock)>=limit:
            self.emit('local_backpressure',f'cell_{cell}_surge',cell=cell,shade=shade,reason='Finite surge belt full; other cells remain enabled')
            returned=False
            for candidate in self.c['shades']:
                if (yield from self.surge_return(cell,candidate)):returned=True;break
            if not returned:yield self.changed | self.env.timeout(.25)
        yield from self.move([tool],[[9.45,bed,z]],f'cell_{cell}_surge','Return selector to observed input brick',v)
        yield from self.move([identity],[[9.45,bed+self.H/2,z]],f'cell_{cell}_surge','Load approved surplus onto supported selector',v)
        yield from self.move([identity,tool],[[9.45,bed+self.H/2,target_z],[9.45,bed,target_z]],f'cell_{cell}_surge','Select same-height surge belt',v)
        yield from self.surge_shift(cell,shade,-.4)
        yield from self.surge_shift(cell,shade,.7,extra=identity)
        stock.insert(0,identity);self.surge_peaks[cell,shade]=max(self.surge_peaks[cell,shade],len(stock))
        self.locate([identity],'accepted_reserve');self.stats['overflow_routes']+=1;self.emit('reserve_admitted',f'cell_{cell}_surge',brick=identity,cell=cell,shade=shade,occupancy=len(stock))
        self.inspect_zones[cell][-1].release(inspection_reservation);self.notify()

    def surge_worker(self,cell):
        while True:
            eligible=[s for s in self.c['shades'] if self.surge_stock[cell,s] and not self.queue_cells[cell,s][0].count and not self.queue_cells[cell,s][0].queue]
            if eligible:
                with self.router[cell].request() as request:
                    yield request
                    # Rotate by fullest belt; no classification is changed.
                    for shade in sorted(eligible,key=lambda s:-len(self.surge_stock[cell,s])):
                        if (yield from self.surge_return(cell,shade)):break
            yield self.changed | self.env.timeout(.25)

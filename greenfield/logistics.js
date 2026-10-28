/* Functional production logistics using Jacob's direct-access warehouse layout. */
'use strict';
window.FactoryLogistics=({Resource,B,L,D,H})=>{
 const A=window.FactoryLayout,F=A.forkOffset,ground=A.storageWoodY,truckY=A.truckWoodY;
 const rotate=(p,yaw)=>[Math.cos(yaw)*p[0]+Math.sin(yaw)*p[2],p[1],-Math.sin(yaw)*p[0]+Math.cos(yaw)*p[2]];
 return{
 initLogistics(){
  this.stored=0;this.loaded=0;this.shipped=0;this.produced=0;this.productionEnd=0;this.stock=[];this.orders=[];this.tasks=[];this.loadTasks=[[],[]];this.fleetPlans=[];this.fleetCalendar=new Map();
  this.storage=A.storage.map((s,i)=>({...s,state:'free',pallet:null,category:null,preferredCategory:Math.floor(i/32)}));
  this.handoffs=A.handoffs.map(s=>({...s,state:'free',pallet:null}));
  this.docks=A.docks.map(d=>({...d,order:null,queued:false,lock:new Resource(this)}));
  const homes=[[A.spineX,-22],[A.spineX-4,-22],[A.docks[0].x-3.975,-22],[A.docks[1].x-3.975,-22]];
  this.fleet=homes.map((p,id)=>{const v={id,role:id<2?'warehouse':'loader',dock:id-2,home:[p[0],0,p[1],0],actor:'amr-'+id,fork:'amr-fork-'+id};this.add(v.actor,v.home,'amr');this.add(v.fork,[p[0]-F,ground+.005,p[1],0],'amrFork');this.env.process(this.fleetWorker(v));return v});
 },
 *dispatchPallet(job){
  const category=job.shade===null?0:job.shade+1;let slot;while(!(slot=this.storage.find(s=>s.state==='free'&&s.preferredCategory===category)||this.storage.find(s=>s.state==='free')))yield this.changed;slot.state='reserved';slot.category=category;yield this.dispatch.request();
  const tool='dispatch',ids=job.ids.concat(job.wood),source=this.rec(job.wood).p.slice(),height=.965,target=[slot.x,ground,slot.z,slot.yaw],sign=Math.cos(slot.yaw);
  yield* this.move([tool],[[source[0]+1.4,4,source[2],0]],1.25,'finished-frame-approach');yield* this.move([tool],[[source[0]+1.4,source[1]+height,source[2],0]],.6,'lower-pallet-lifting-frame');yield* this.move([tool],[[source[0],source[1]+height,source[2],0]],.35,'insert-supported-pallet-forks');yield .25;
  yield* this.carry([{head:tool,ids,to:[source[0],4,source[2],0]}],.6,'lift-supported-output-pallet');job.lane.branches[job.well].release();yield* this.carry([{head:tool,ids,to:[target[0],4,target[2],target[3]]}],1.25,'finished-pallet-bridge');
  const vertical=Math.max(1.5*(4-target[1]-height)/.6,Math.sqrt(3*(4-target[1]-height))),withdraw=6,hold=2*vertical+withdraw+.25,centre=[target[0]+sign*1.3,0,target[2],target[3]];
  const permitted=this.reserveFleet({id:'gantry'},[{from:centre,to:centre,dt:hold,gantry:true}]);if(permitted>this.env.now)yield permitted-this.env.now;
  yield* this.carry([{head:tool,ids,to:[target[0],target[1]+height,target[2],target[3]]}],.6,'lower-pallet-in-warehouse');yield .25;
  const pallet={id:this.pallets.length,t:this.env.now,producedAt:job.completedAt,ids:job.ids.slice(),wood:job.wood,shade:job.shade,category,lane:job.lane.id,well:job.well,state:'placing',slot:slot.id};this.pallets.push(pallet);this.delivered++;this.mark();
  yield* this.move([tool],[[target[0]+sign*1.4,target[1]+height,target[2],target[3]]],.35,'withdraw-supported-pallet-forks');yield* this.move([tool],[[target[0]+sign*1.4,4,target[2],target[3]]],.6,'raise-empty-finished-frame');this.dispatch.release();slot.state='stored';slot.pallet=pallet.id;pallet.state='stored';pallet.storedAt=this.env.now;this.stock.push(pallet);this.stored++;this.mark();this.queueShipping();this.wake();
 },
 ensureTruck(category,dock){
  if(dock.order)return dock.order;const n=this.orders.filter(o=>o.category===category).length+1,id='truck-'+category+'-'+n;const order={id,number:n,category,capacity:8,physicalCapacity:20,reserved:0,loaded:0,status:'arriving',ready:this.env.event(),ids:[],palletIds:[],dock:dock.id};this.orders.push(order);dock.order=order;this.add(id,[dock.x,0,-36,Math.PI/2],'truck').visible=this.env.now;this.env.process(this.arriveTruck(order));return order;
 },
 *arriveTruck(order){const d=this.docks[order.dock],from=this.rec(order.id).p.slice(),to=[d.x,0,0,Math.PI/2],dt=Math.max(1.5*36/.8,Math.sqrt(6*36/2)),start=this.reserveFleet({id:order.id,truck:true},[{from,to,dt}]);if(start>this.env.now)yield start-this.env.now;yield* this.move([order.id],[to],.8,'truck-through-arrival');order.status='awaiting stock';order.ready.succeed();this.mark();this.queueShipping()},
 queueShipping(){
  for(const d of this.docks)if(!d.order){const candidate=[0,1,2,3].map(category=>({category,stock:this.stock.filter(p=>p.category===category&&p.state==='stored')})).filter(v=>v.stock.length-this.orders.filter(o=>o.category===v.category&&o.status!=='shipped').reduce((n,o)=>n+o.capacity-o.reserved,0)>=8).sort((a,b)=>a.stock[0].storedAt-b.stock[0].storedAt)[0];if(candidate)this.ensureTruck(candidate.category,d)}
  for(const dock of this.docks){const order=dock.order;if(!order||!order.ready.done||dock.queued||order.reserved>=order.capacity)continue;const p=this.stock.find(p=>p.category===order.category&&p.state==='stored');if(!p)continue;const handoff=this.handoffs.find(h=>h.state==='free');if(!handoff)continue;handoff.state='reserved';handoff.pallet=p.id;p.state='assigned';dock.queued=true;const task={kind:'warehouse',pallet:p,slot:this.storage.find(s=>s.id===p.slot),handoff,dock,order,position:order.reserved++,created:this.env.now};this.tasks.push(task);this.wake()}
 },
 *fleetWorker(v){while(true){const list=v.role==='warehouse'?this.tasks:this.loadTasks[v.dock];while(!list.length)yield this.changed;const task=list.shift();if(v.role==='loader')yield task.dock.lock.request();const steps=this.buildFleetTask(v,task);yield* this.executeFleetTask(v,task,steps);this.queueShipping()}},
 buildFleetTask(v,task){
  const steps=[],p=task.pallet;let at=this.rec(v.actor).p.slice(),height=this.rec(v.fork).p[1];
  const drive=(points,kind)=>{for(const p of points){const to=[p[0],0,p[1],p.length>2?p[2]:at[3]],d=Math.hypot(to[0]-at[0],to[2]-at[2]),angle=Math.abs(to[3]-at[3]);if(d<1e-7&&angle<1e-7)continue;const dt=Math.max(1.5*d/1.2,Math.sqrt(6*d/.6),1.5*angle/.8,.01);steps.push({kind,from:at.slice(),to,dt});at=to}};
  const lift=(woodY,kind,onEnd)=>{const to=woodY+.005,dt=Math.max(.7,1.5*Math.abs(to-height)/.2,Math.sqrt(6*Math.abs(to-height)/.6));steps.push({kind,from:at.slice(),to:at.slice(),height:[height,to],dt,onEnd});height=to};
  const hold=(kind,onEnd)=>steps.push({kind,from:at.slice(),to:at.slice(),dt:.6,onEnd});
  if(v.role==='warehouse'){
   const s=task.slot,aisle=A.aisles.find(a=>a.id===s.aisle),yaw=s.yaw,sign=Math.cos(yaw),approach=s.x+sign*F;
   drive([[v.home[0],-18.5],[A.spineX,-18.5],[A.spineX,-18.5,yaw],[aisle.x,-18.5],[aisle.x,s.z],[approach,s.z]],'amr-empty-to-stock');hold('amr-pallet-confirm',()=>{v.cargo=p.ids.concat(p.wood);p.state='to-handoff'});lift(ground+.20,'amr-lift-pallet');drive([[aisle.x,s.z],[aisle.x,-18.5],[A.spineX,-18.5]],'amr-clear-storage');hold('warehouse-slot-release',()=>{s.state='free';s.pallet=null;this.mark();this.wakeDemand()});
   drive([[A.spineX,-18.5,Math.PI],[A.spineX,task.handoff.z],[task.handoff.x-F,task.handoff.z]],'amr-loaded-to-handoff');lift(ground,'amr-lower-at-handoff',()=>{v.cargo=null;p.state='handoff';p.handoffAt=this.env.now});drive([[A.spineX,task.handoff.z]],'amr-withdraw-handoff');hold('handoff-warehouse-clear',()=>{task.handoff.state='ready';this.loadTasks[task.dock.id].push({...task,kind:'load'});this.wake()});drive([[A.spineX,-18.5],[v.home[0],-18.5,0],[v.home[0],v.home[2]]],'amr-return-home');
  }else{
   const h=task.handoff,d=task.dock,side=task.position%2===0?-1:1,row=Math.floor(task.position/2),targetZ=-7.3+row*1.3,targetX=d.x+side*.625,yaw=side<0?Math.PI:0,work=d.x+side*3.975,approach=targetX+side*F;
   drive([[v.home[0],-14.2],[h.x+F,-14.2,0],[h.x+F,h.z]],'loader-empty-to-handoff');hold('loader-pallet-confirm',()=>{v.cargo=p.ids.concat(p.wood);p.state='to-order'});lift(ground+.20,'loader-lift-pallet');drive([[A.docks[0].x-3.975,h.z]],'loader-clear-handoff');hold('handoff-loader-clear',()=>{h.state='free';h.pallet=null;this.queueShipping();this.mark()});
   drive([[A.docks[0].x-3.975,-14.2],[d.x-3.975,-14.2],[work,-14.2],[work,-14.2,yaw],[work,targetZ]],'loader-loaded-to-truck-side');lift(A.truckLiftY,'loader-raise-forks');drive([[approach,targetZ]],'loader-ground-side-approach');lift(truckY,'loader-place-on-trailer',()=>{v.cargo=null;this.confirmTruckLoad(task)});drive([[work,targetZ]],'loader-ground-withdrawal');lift(ground,'loader-reset-fork-height');drive([[work,-14.2],[v.home[0],-14.2],[v.home[0],-14.2,0],[v.home[0],v.home[2]]],'loader-return-home');hold('loader-bay-clear',()=>{task.dock.lock.release();task.dock.queued=false;if(task.order.loaded===task.order.capacity){task.order.status='departing';this.env.process(this.departTruck(task.order))}this.queueShipping();this.mark()});
  }
  return steps;
 },
 reserveFleet(v,steps){
  const tick=.5,size=.5,table=this.fleetCalendar,masks=[];let elapsed=0;
  for(const step of steps){for(let u=0;u<step.dt-1e-8;u+=tick){const end=Math.min(step.dt,u+tick),points=[];for(const q of [u,end,(u+end)/2]){let f=q/step.dt;f=f*f*(3-2*f);const x=step.from[0]+(step.to[0]-step.from[0])*f,z=step.from[2]+(step.to[2]-step.from[2])*f,yaw=step.from[3]+(step.to[3]-step.from[3])*f;for(const xx of (v.truck?[-8.25,8.25]:[-2.2,1.0]))for(const zz of (v.truck?[-1.275,1.275]:[-.73,.73])){const a=rotate([xx,0,zz],yaw);points.push([x+a[0],z+a[2]])}}const cells=[],pad=.015;for(let x=Math.floor((Math.min(...points.map(p=>p[0]))-pad)/size);x<=Math.floor((Math.max(...points.map(p=>p[0]))+pad)/size);x++)for(let z=Math.floor((Math.min(...points.map(p=>p[1]))-pad)/size);z<=Math.floor((Math.max(...points.map(p=>p[1]))+pad)/size);z++)cells.push(x+','+z);masks.push({from:elapsed+u,to:elapsed+end,cells})}elapsed+=step.dt}
  const keys=(m,start)=>{const out=[];for(let t=Math.floor((start+m.from-.05)/tick);t<=Math.floor((start+m.to+.05)/tick);t++)for(const c of m.cells)out.push(c+','+t);return out};let start=this.env.now,tries=0;while(masks.some(m=>keys(m,start).some(k=>table.has(k)))){start+=tick;if(++tries>100000)throw Error('No collision-free vehicle task reservation')}for(const m of masks)for(const k of keys(m,start))table.set(k,v.id);if(table.size>150000){const before=Math.floor(this.env.now/tick)-2;for(const k of table.keys())if(Number(k.slice(k.lastIndexOf(',')+1))<before)table.delete(k)}this.fleetPlans.push({vehicle:v.id,start,end:start+elapsed,delay:start-this.env.now});return start;
 },
 *executeFleetTask(v,task,steps){const start=this.reserveFleet(v,steps);if(start>this.env.now)yield start-this.env.now;v.cargo=null;for(const step of steps){const t=this.env.now;if(step.height){const dy=step.height[1]-step.height[0];for(const id of [v.fork].concat(v.cargo||[])){const p=this.rec(id).p.slice();p[1]+=dy;this.append(id,p,t,step.dt,step.kind,false)}}else if(step.from.some((x,i)=>Math.abs(x-step.to[i])>1e-8)){
    const from=step.from,to=step.to,co=Math.cos(from[3]),si=Math.sin(from[3]);for(const id of [v.fork].concat(v.cargo||[])){const r=this.rec(id),p=r.p,dx=p[0]-from[0],dz=p[2]-from[2],local=[co*dx-si*dz,p[1]-from[1],si*dx+co*dz],v2=rotate(local,to[3]),yaw=p[3]-from[3];this.append(id,[to[0]+v2[0],to[1]+v2[1],to[2]+v2[2],to[3]+yaw],t,step.dt,step.kind,false,{rigid:{from:from.slice(),to:to.slice(),local,yaw}})}this.append(v.actor,to,t,step.dt,step.kind,false)
   }yield step.dt;if(step.onEnd)step.onEnd();this.wake()}
 },
 confirmTruckLoad(task){const {pallet:p,order}=task;p.state='loaded';p.loadedAt=this.env.now;p.order=order.id;order.loaded++;order.ids.push(...p.ids,p.wood);order.palletIds.push(p.id);this.loaded++;this.mark()},
 *departTruck(order){const d=this.docks[order.dock],from=this.rec(order.id).p.slice(),to=[d.x,0,36,Math.PI/2],dt=Math.max(1.5*36/.8,Math.sqrt(6*36/2)),start=this.reserveFleet({id:order.id,truck:true},[{from,to,dt}]);if(start>this.env.now)yield start-this.env.now;yield* this.carry([{head:order.id,ids:order.ids,to}],.8,'truck-order-departure');order.status='shipped';order.departedAt=this.env.now;this.shipped+=order.loaded;for(const id of order.ids.concat(order.id))this.rec(id).hiddenAt=this.env.now;for(const id of order.palletIds){this.pallets[id].state='shipped';this.pallets[id].shippedAt=this.env.now}d.order=null;d.queued=false;this.mark();this.queueShipping();this.wake()}
 };
};

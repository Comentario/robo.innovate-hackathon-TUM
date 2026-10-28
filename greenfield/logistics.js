/* Shared warehouse and order-driven omnidirectional pallet transport. */
'use strict';
window.FactoryLogistics=({Resource,B,L,D,H})=>({
 initLogistics(){
  this.stored=0;this.loaded=0;this.shipped=0;this.produced=0;this.productionEnd=0;
  this.stock=[];this.orders=[];this.tasks=[];this.fleetPlans=[];this.fleetCalendar=new Map();
  this.storage=Array.from({length:4},(_,category)=>Array.from({length:9},(_,i)=>({category,id:category+'-'+i,x:66+category*6,z:-12+i*3,state:'free',pallet:null}))).flat();
  this.docks=Array.from({length:4},(_,category)=>({category,z:26+category*8,order:null,queued:false,lock:new Resource(this)}));
  for(const d of this.docks){this.add('dock-lift-'+d.category,[92.5,0,d.z,0],'dockLift');this.ensureTruck(d.category);}
  this.fleet=Array.from({length:4},(_,id)=>{const v={id,home:[65+id*5,0,-21,0],actor:'amr-'+id,fork:'amr-fork-'+id};this.add(v.actor,v.home,'amr');this.add(v.fork,[v.home[0]-1.4,.224,v.home[2],0],'amrFork');this.env.process(this.fleetWorker(v));return v});
 },
 *dispatchPallet(job){
  const category=job.shade===null?0:job.shade+1;let slot;
  while(!(slot=this.storage.find(s=>s.category===category&&s.state==='free')))yield this.changed;
  slot.state='reserved';yield this.dispatch.request();
  const tool='dispatch',ids=job.ids.concat(job.wood),source=this.rec(job.wood).p.slice(),height=.96,target=[slot.x,.224,slot.z,0];
  yield* this.move([tool],[[source[0]+1.4,4,source[2],0]],1.25,'finished-frame-approach');
  yield* this.move([tool],[[source[0]+1.4,source[1]+height,source[2],0]],.6,'lower-pallet-lifting-frame');
  yield* this.move([tool],[[source[0],source[1]+height,source[2],0]],.35,'insert-supported-pallet-forks');yield .25;
  yield* this.carry([{head:tool,ids,to:[source[0],4,source[2],0]}],.6,'lift-supported-output-pallet');job.lane.branches[job.well].release();
  yield* this.carry([{head:tool,ids,to:[target[0],4,target[2],0]}],1.25,'finished-pallet-bridge');
  // Reserve the low gantry envelope in the same traffic calendar used by AMRs.
  const descent=4-(target[1]+height),vertical=Math.max(1.5*descent/.6,Math.sqrt(3*descent)),withdraw=Math.max(1.5*1.4/.35,Math.sqrt(3*1.4)),hold=2*vertical+withdraw+.25,centre=[target[0]+1.3,0,target[2],0];
  const permitted=this.reserveFleet({id:'gantry'},[{from:centre,to:centre,dt:hold}]);if(permitted>this.env.now)yield permitted-this.env.now;
  yield* this.carry([{head:tool,ids,to:[target[0],target[1]+height,target[2],0]}],.6,'lower-pallet-in-warehouse');yield .25;
  const pallet={id:this.pallets.length,t:this.env.now,producedAt:job.completedAt,ids:job.ids.slice(),wood:job.wood,shade:job.shade,category,lane:job.lane.id,well:job.well,state:'placing',slot:slot.id};
  this.pallets.push(pallet);this.delivered++;this.mark();
  yield* this.move([tool],[[target[0]+1.4,target[1]+height,target[2],0]],.35,'withdraw-supported-pallet-forks');
  yield* this.move([tool],[[target[0]+1.4,4,target[2],0]],.6,'raise-empty-finished-frame');this.dispatch.release();
  slot.state='stored';slot.pallet=pallet.id;pallet.state='stored';pallet.storedAt=this.env.now;this.stock.push(pallet);this.stored++;this.mark();this.queueShipping();this.wake();
 },
 ensureTruck(category){
  const dock=this.docks[category];if(dock.order)return dock.order;
  const n=this.orders.filter(o=>o.category===category).length+1,id='truck-'+category+'-'+n;
  const order={id,number:n,category,capacity:8,reserved:0,loaded:0,status:'arriving',ready:this.env.event(),ids:[],palletIds:[],dock:category};
  this.orders.push(order);dock.order=order;this.add(id,[54,0,dock.z,0],'truck').visible=this.env.now;this.env.process(this.arriveTruck(order));return order;
 },
 *arriveTruck(order){const d=this.docks[order.category];yield* this.move([order.id],[[85,0,d.z,0]],.8,'truck-reverse-to-dock');order.status='awaiting stock';order.ready.succeed();this.mark();this.queueShipping()},
 queueShipping(){
  for(const dock of this.docks){if(dock.queued)continue;const item=this.stock.find(p=>p.category===dock.category&&p.state==='stored');if(!item)continue;const order=this.ensureTruck(dock.category);if(!order.ready.done||order.reserved>=order.capacity)continue;if(!order.started&&this.stock.filter(p=>p.category===dock.category&&p.state==='stored').length<order.capacity)continue;order.started=true;order.status='loading';
   const slot=this.storage.find(s=>s.id===item.slot);item.state='assigned';dock.queued=true;const position=order.reserved++;this.tasks.push({kind:'ship',pallet:item,slot,dock,order,position,created:this.env.now});this.wake();}
 },
 *fleetWorker(v){while(true){while(!this.tasks.length)yield this.changed;const task=this.tasks.shift();if(task.kind==='ship')yield task.dock.lock.request();const steps=this.buildFleetTask(v,task);yield* this.executeFleetTask(v,task,steps);this.queueShipping();}},
 buildFleetTask(v,task){
  const steps=[],p=task.pallet,slot=task.slot;let at=this.rec(v.actor).p.slice(),height=.224;
  const drive=(points,kind)=>{for(const point of points){const to=[point[0],at[1],point[1],0],d=Math.hypot(to[0]-at[0],to[2]-at[2]);if(d<1e-6)continue;const dt=Math.max(1.5*d/1.2,Math.sqrt(6*d/.6));steps.push({kind,from:at.slice(),to,dt});at=to;}};
  const lift=(to,kind,onEnd)=>{const dt=Math.max(.7,1.5*Math.abs(to-height)/.2,Math.sqrt(6*Math.abs(to-height)/.6));steps.push({kind,from:at.slice(),to:at.slice(),height:[height,to],dt,onEnd});height=to;};
  const hold=(kind,onEnd)=>steps.push({kind,from:at.slice(),to:at.slice(),dt:.6,onEnd});
  const platform=(level,kind)=>{const dy=level-at[1],to=[at[0],level,at[2],0],dt=Math.max(1.5*Math.abs(dy)/.15,Math.sqrt(6*Math.abs(dy)/.3));steps.push({kind,from:at.slice(),to,dt,platform:'dock-lift-'+task.dock.category});at=to;height+=dy};
   drive([[v.home[0],-17.5],[slot.x+2.7,-17.5],[slot.x+2.7,slot.z],[slot.x+1.4,slot.z]],'amr-empty-to-stock');
   hold('amr-pallet-confirm',()=>{v.cargo=p.ids.concat(p.wood);p.state='to-order'});lift(.424,'amr-lift-pallet');drive([[slot.x+2.7,slot.z]],'amr-clear-storage');
   hold('warehouse-slot-release',()=>{slot.state='free';slot.pallet=null;this.mark();this.wakeDemand()});
   drive([[slot.x+2.7,18],[101,18],[101,task.dock.z],[93,task.dock.z]],'amr-loaded-to-dock-platform');
   platform(.8,'dock-platform-raise-loaded-amr');
   const target=80.15+task.position*1.35;drive([[target+1.4,task.dock.z]],'amr-enter-trailer');
   lift(.86,'amr-place-directly-in-trailer',()=>{v.cargo=null;this.confirmTruckLoad(task)});
   drive([[93,task.dock.z]],'amr-reverse-out-of-trailer');platform(0,'dock-platform-lower-empty-amr');
   lift(.224,'amr-reset-fork-travel-height');drive([[101,task.dock.z]],'amr-clear-dock');
   hold('amr-dock-clear',()=>{task.dock.lock.release();if(task.order.loaded===task.order.capacity){task.order.status='departing';this.env.process(this.departTruck(task.order))}else{task.dock.queued=false;this.queueShipping()}this.mark()});
   drive([[101,-17.5],[v.home[0],-17.5],[v.home[0],v.home[2]]],'amr-return-home');
  return steps;
 },
 reserveFleet(v,steps){
  const tick=.5,size=.5,table=this.fleetCalendar,masks=[];let elapsed=0;
  for(const step of steps){for(let u=0;u<step.dt-1e-8;u+=tick){const end=Math.min(step.dt,u+tick),smooth=t=>{const x=t/step.dt;return x*x*(3-2*x)},a=smooth(u),b=smooth(end),x0=step.from[0]+(step.to[0]-step.from[0])*a,x1=step.from[0]+(step.to[0]-step.from[0])*b,z0=step.from[2]+(step.to[2]-step.from[2])*a,z1=step.from[2]+(step.to[2]-step.from[2])*b,cells=[];
    for(let x=Math.floor((Math.min(x0,x1)-2.10)/size);x<=Math.floor((Math.max(x0,x1)+1.00)/size);x++)for(let z=Math.floor((Math.min(z0,z1)-.73)/size);z<=Math.floor((Math.max(z0,z1)+.73)/size);z++)cells.push(x+','+z);
    masks.push({from:elapsed+u,to:elapsed+end,cells});}elapsed+=step.dt;}
  const keys=(m,start)=>{const out=[];for(let t=Math.floor((start+m.from-.05)/tick);t<=Math.floor((start+m.to+.05)/tick);t++)for(const c of m.cells)out.push(c+','+t);return out};
  let start=this.env.now,tries=0;while(masks.some(m=>keys(m,start).some(k=>table.has(k)))){start+=tick;if(++tries>50000)throw Error('No collision-free AMR task reservation')}
  for(const m of masks)for(const k of keys(m,start))table.set(k,v.id);if(table.size>100000){const before=Math.floor(this.env.now/tick)-2;for(const k of table.keys())if(Number(k.slice(k.lastIndexOf(',')+1))<before)table.delete(k)}
  this.fleetPlans.push({vehicle:v.id,start,end:start+elapsed,delay:start-this.env.now});return start;
 },
 *executeFleetTask(v,task,steps){const start=this.reserveFleet(v,steps);if(start>this.env.now)yield start-this.env.now;v.cargo=null;
  for(const step of steps){const t=this.env.now;if(step.height){const ids=[v.fork].concat(v.cargo||[]),dy=step.height[1]-step.height[0];for(const id of ids){const p=this.rec(id).p.slice();p[1]+=dy;this.append(id,p,t,step.dt,step.kind,false)}}else if(Math.hypot(step.to[0]-step.from[0],step.to[1]-step.from[1],step.to[2]-step.from[2])>1e-6){const ids=[v.actor,v.fork].concat(v.cargo||[],step.platform?[step.platform]:[]),dx=step.to[0]-step.from[0],dy=step.to[1]-step.from[1],dz=step.to[2]-step.from[2];for(const id of ids){const p=this.rec(id).p.slice();p[0]+=dx;p[1]+=dy;p[2]+=dz;this.append(id,p,t,step.dt,step.kind,false)}}yield step.dt;if(step.onEnd)step.onEnd();this.wake();}
 },
 confirmTruckLoad(task){const {pallet:p,order}=task,ids=p.ids.concat(p.wood);p.state='loaded';p.loadedAt=this.env.now;p.order=order.id;order.loaded++;order.ids.push(...ids);order.palletIds.push(p.id);this.loaded++;this.mark();
 },
 *departTruck(order){const dock=this.docks[order.category];yield* this.carry([{head:order.id,ids:order.ids,to:[54,0,dock.z,0]}],.8,'truck-order-departure');order.status='shipped';order.departedAt=this.env.now;this.shipped+=order.loaded;for(const id of order.ids.concat(order.id))this.rec(id).hiddenAt=this.env.now;for(const id of order.palletIds){this.pallets[id].state='shipped';this.pallets[id].shippedAt=this.env.now}dock.order=null;dock.queued=false;this.mark();this.queueShipping();this.wake();}
});

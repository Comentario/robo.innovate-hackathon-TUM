"""Copy one-step native contact reports; expose only known robot roles online."""
import hashlib
import json
from pathlib import Path
import numpy as np


def role_packet(callbacks,role_paths,actor_sides,dt):
    """Fixed shape1→shape0 convention; never choose a sign from observed data."""
    events=[];unknown=0
    for callback in callbacks:
        for header in callback['headers']:
            if not header['points']:continue  # Empty LOST metadata establishes no point/role claim.
            for slot in (0,1):
                actor=header['actor'+str(slot)];collider=header['collider'+str(slot)]
                if actor not in actor_sides:continue
                known=role_paths.get(collider)
                if known is None or known['side']!=actor_sides[actor] or header['proto_index'+str(slot)]!=0xFFFFFFFF:unknown+=1;continue
                sign=1. if slot==0 else -1.
                for point in header['points']:
                    normal=np.asarray(point['normal'],float);impulse=np.asarray(point['impulse'],float)
                    length=np.linalg.norm(normal)
                    if not np.isfinite(length) or abs(length-1.)>1e-3:unknown+=1;continue
                    normal=normal/length
                    projected=float(impulse@normal)*normal
                    events.append({'side':known['side'],'role':known['role'],
                        'point_world_m':point['position'],'normal_robot_world':(sign*normal).tolist(),
                        'normal_impulse_on_robot_world_Ns':(sign*projected).tolist(),
                        'normal_force_on_robot_world_N':(sign*projected/dt).tolist()})
    return {'robot_contacts':events,'unknown_robot_shapes':unknown}


class NativeObserver:
    def __init__(self,sim,stage,output,role_paths,actor_sides):
        from omni.physx import get_physx_simulation_interface
        from pxr import PhysicsSchemaTools,UsdUtils
        self.sim,self.role_paths,self.actor_sides=sim,role_paths,actor_sides
        self.decode=lambda value:str(PhysicsSchemaTools.intToSdfPath(value))
        self.stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt()
        self.output=Path(output);self.directory=self.output/'evaluation_truth/native_contacts';self.directory.mkdir(parents=True,exist_ok=True)
        self.active=False;self.out_of_window=0;self.errors=[];self.callbacks=[]
        self.subscription=get_physx_simulation_interface().subscribe_contact_report_events(self._callback)
        import omni.physx.bindings._physx as binding
        api=Path(binding.__file__).parent/'_physx.pyi'
        metadata={'schema':'native-shape-contact-copy-v1','stage_id':self.stage_id,'role_paths':role_paths,
            'actor_sides':actor_sides,'api_source':str(api),'api_sha256':hashlib.sha256(api.read_bytes()).hexdigest(),
            'normal_convention':'shape1 to shape0; force/impulse on robot = + for actor0, - for actor1; no sign fit',
            'point_impulse_convention':'Preserve full vector; compare dot(impulse,normal)*normal to tensor normal impulse.',
            'lifetime':'Copied in callback before next simulation; no stored SDK views','maximum_points_per_callback':1024,
            'online_whitelist':['side','role','point_world_m','normal_robot_world','normal_impulse_on_robot_world_Ns','normal_force_on_robot_world_N']}
        (self.directory/'metadata.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')

    def begin(self,step):
        if self.active:raise RuntimeError('Overlapping native-report interval')
        self.step=step;self.before=float(self.sim.current_time);self.callbacks=[];self.errors=[];self.active=True

    def _callback(self,headers,data):
        if not self.active:self.out_of_window+=1;return
        try:
            if len(data)>1024:raise RuntimeError('Native point buffer exceeds frozen capacity')
            callback={'observed_clock_s':float(self.sim.current_time),'raw_contact_data_count':len(data),'headers':[]}
            for h in headers:
                offset,count=int(h.contact_data_offset),int(h.num_contact_data)
                if count<0 or (count and (offset<0 or offset+count>len(data))):raise RuntimeError('Invalid native contact slice')
                header={k:self.decode(getattr(h,k)) for k in ('actor0','actor1','collider0','collider1')}
                header.update({'raw_'+k:int(getattr(h,k)) for k in ('actor0','actor1','collider0','collider1')})
                header.update(stage_id=int(h.stage_id),type=str(h.type),proto_index0=int(h.proto_index0),proto_index1=int(h.proto_index1),
                              contact_data_offset=offset,num_contact_data=count,points=[])
                if header['stage_id']!=self.stage_id:raise RuntimeError('Native contact from another stage')
                for i in range(offset,offset+count):
                    d=data[i];p={'data_index':i,'position':list(map(float,d.position)),'normal':list(map(float,d.normal)),
                        'impulse':list(map(float,d.impulse)),'separation':float(d.separation),'face_index0':int(d.face_index0),'face_index1':int(d.face_index1)}
                    if not np.isfinite([*p['position'],*p['normal'],*p['impulse'],p['separation']]).all():raise RuntimeError('Nonfinite native report')
                    if abs(np.linalg.norm(p['normal'])-1.)>1e-3:raise RuntimeError('Nonunit native contact normal')
                    header['points'].append(p)
                callback['headers'].append(header)
            self.callbacks.append(callback)
        except Exception as error:
            # Callback exceptions must become a failed record, not disappear inside Kit.
            self.errors.append(type(error).__name__+': '+str(error))

    def finish(self):
        self.active=False;after=float(self.sim.current_time);dt=float(self.sim.get_physics_dt())
        complete=not self.errors and abs(after-self.before-dt)<=1e-7
        complete=complete and all(self.before-1e-7<=c['observed_clock_s']<=after+1e-7 for c in self.callbacks)
        record={'step':self.step,'time_before_s':self.before,'time_after_s':after,'dt_s':dt,
            'callbacks':self.callbacks,'complete':complete,'errors':self.errors,'out_of_window_callbacks_total':self.out_of_window}
        path=self.directory/('step_'+str(self.step).zfill(4)+'.json')
        path.write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
        packet=role_packet(self.callbacks,self.role_paths,self.actor_sides,dt)
        packet.update(step=self.step,complete=bool(complete and not packet['unknown_robot_shapes']))
        return str(path.relative_to(self.output)),packet

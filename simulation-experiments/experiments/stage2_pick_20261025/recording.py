"""Evaluation-only native/state logging and isolated reciprocal contact view."""
import hashlib,importlib.util,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
from experiments.stage2_exposed_tip_20261025.model import save

def observer_module(name):
    path=ROOT/'experiments/stage2_contact_20261025/contact_capture.py'
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def robot_properties(robot):
    return {k:getattr(robot.root_physx_view,m)().cpu().numpy().tolist() for k,m in [('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'),('stiffnesses','get_dof_stiffnesses'),('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces')]}

class Recorder:
    """This object never returns actor identities/state to task control."""
    def __init__(self,context,output,case,sensor=None,selection=None):
        import bricksim.core as core
        from challenge2.layout import overlaps
        from isaaclab.utils.math import matrix_from_quat
        self.context,self.output,self.core=context,output,core;self.directory=output/'evaluation_truth';self.directory.mkdir(exist_ok=True)
        self.assets=['plate_source']+[b.name for b in context['bricks']];self.ids=['/World/envs/env_0/'+n for n in self.assets]
        self.edges=[]
        for upper in context['bricks']:
            lower=[b for b in context['bricks'] if b.layer==upper.layer-1 and overlaps(b,upper)] if upper.layer else [None]
            for a in lower:
                ap='/World/envs/env_0/'+(a.name if a else 'plate_source');bp='/World/envs/env_0/'+upper.name
                connection=core.lookup_physics_connection(ap,1,bp,0)
                if connection is None or connection.conn_path is None:raise RuntimeError('Native initial edge lookup failed')
                self.edges.append({'id':len(self.edges),'native_path':connection.conn_path,'a':ap,'b':bp})
        self.edge_map={e['native_path']:e['id'] for e in self.edges};self.endpoint_map={(e['a'],e['b']):e['id'] for e in self.edges}
        clock=float(context['sim'].current_time);polygons=[]
        if sensor is not None:
            K,R,t=sensor.cal['K'],sensor.cal['R'],sensor.cal['t']
            for brick in context['bricks']:
                data=context['scene'][brick.name].data;rotation=matrix_from_quat(data.root_quat_w[0:1])[0].cpu().numpy();position=data.root_pos_w[0].cpu().numpy()
                corners=np.array([[-.016,-.008,.0096],[.016,-.008,.0096],[.016,.008,.0096],[-.016,.008,.0096]])@rotation.T+position
                optical=corners@R.T+t;uv=optical[:,:2]/optical[:,2,None];uv=uv@K[:2,:2].T+K[:2,2]
                polygons.append({'id':'/World/envs/env_0/'+brick.name,'image_polygon':uv.tolist(),'layer':brick.layer,'top_surface_z_m':float(corners[:,2].mean()),'eligible_for_binding':brick.layer==max(b.layer for b in context['bricks'])})
        self.inventory={'ids':self.ids,'initial_edges':self.edges,'body_states_file':'states_000000.npz','measurement_time_s':clock,'projected_top_faces':polygons,'camera_frame_id':selection.get('frame_id') if selection else None,'source_properties':self.source_properties()}
        save(self.directory/'initial_inventory.json',self.inventory);self.write_states(0);self.initial_states=self.last_states.copy();self.stationary=False
        self.source_observer=None;self.bound=None
        if selection and selection.get('candidate'):
            import cv2
            selected=np.asarray(selection['candidate']['image_polygon'],np.float32);area=abs(cv2.contourArea(selected));matches=[]
            for p in polygons:
                if not p['eligible_for_binding']:continue
                polygon=np.asarray(p['image_polygon'],np.float32);intersection,_=cv2.intersectConvexConvex(selected,polygon);union=area+abs(cv2.contourArea(polygon))-intersection
                iou=float(intersection/union) if union>0 else 0.
                if iou>=.5:matches.append({'id':p['id'],'IoU':iou})
            binding={'measurement_time_s':clock,'frame_id':selection['frame_id'],'candidate_id':selection['candidate']['candidate_id'],'matches':matches,'unique':len(matches)==1,'scope':'Evaluation instrumentation only; never supplied to controller'}
            save(self.directory/'initial_binding.json',binding)
            if len(matches)!=1:raise RuntimeError('Evaluation-only initial selected-face binding ambiguous')
            self.bound=matches[0]['id'];name=self.bound.rsplit('/',1)[-1];module=observer_module('pick_evaluation_contact')
            module.NAMES=('source',);module.BODIES={'source':self.bound}
            proxy={'source':SimpleNamespace(data=SimpleNamespace(root_com_pos_w=context['scene'][name].data.root_com_pos_w))}
            self.source_observer=module.ContactObserver(context['sim'],proxy,self.directory)
        core.get_disassembled_connections(clear=True)

    def source_properties(self):
        return {p:{k:getattr(self.context['scene'][n].root_physx_view,m)().cpu().numpy().tolist() for k,m in [('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms')]} for p,n in zip(self.ids,self.assets)}

    def write_states(self,step):
        values=np.stack([self.context['scene'][n].data.root_state_w[0].cpu().numpy() for n in self.assets]);path=self.directory/f'states_{step:06d}.npz';np.savez_compressed(path,states=values);self.last_states=values
        return path.name,bool(np.isfinite(values).all())

    def before_step(self):
        if self.source_observer:
            name=self.bound.rsplit('/',1)[-1];self.source_observer.scene['source'].data.root_com_pos_w=self.context['scene'][name].data.root_com_pos_w
            self.source_observer.before_step()

    def sample(self,step):
        state_file,finite=self.write_states(step);unvisited=set(self.ids);active_edges=set();components=[]
        while unvisited:
            parts,edges=self.core.compute_connected_component(min(unvisited));unvisited-=set(parts)
            if not parts:raise RuntimeError('Missing native source part')
            components.append([self.ids.index(p) for p in parts if p in self.ids]);active_edges.update(edges)
        events=[]
        for event in self.core.get_disassembled_connections(clear=True):
            identity=self.edge_map.get(event.conn_path,self.endpoint_map.get((event.stud_path,event.hole_path)))
            events.append({'id':identity,'a':event.stud_path,'b':event.hole_path,'native_path':event.conn_path})
        row={'step':step,'time_s':float(self.context['sim'].current_time),'state_file':state_file,'edges':[self.edge_map.get(p,p) for p in sorted(active_edges)],'components':components,'break_events':events,'nonfinite':not finite,'contacts':{}}
        if self.source_observer:
            name=self.bound.rsplit('/',1)[-1];self.source_observer.scene['source'].data.root_com_pos_w=self.context['scene'][name].data.root_com_pos_w
            sample=self.source_observer.sample(step);data=sample['bodies']['source'];data['file']='evaluation_truth/'+data['file'];row['contacts']['source']=data
        with (self.directory/'trace.jsonl').open('a') as f:f.write(json.dumps(row,allow_nan=False)+'\n')
        if not finite:raise RuntimeError('Evaluation watchdog: nonfinite source state')
        if self.stationary:
            now=self.last_states;initial=self.initial_states;qa=now[:,3:7];qb=initial[:,3:7];qa=qa/np.linalg.norm(qa,axis=1)[:,None];qb=qb/np.linalg.norm(qb,axis=1)[:,None]
            angles=2*np.arccos(np.clip(abs((qa*qb).sum(axis=1)),0,1))
            if active_edges!=set(self.edge_map) or events or np.linalg.norm(now[:,:3]-initial[:,:3],axis=1).max()>.002 or angles.max()>np.deg2rad(2):raise RuntimeError('Stationary experimental guard failed; no pick authorization')

    def finish_control(self,protocol):
        if np.linalg.norm(self.last_states[:,7:10],axis=1).max()>protocol['max_terminal_linear_speed_m_s'] or np.linalg.norm(self.last_states[:,10:13],axis=1).max()>protocol['max_terminal_angular_speed_rad_s']:raise RuntimeError('Stationary terminal speed gate failed')


def settings(context,tool):
    from isaaclab.sim import get_current_stage
    from pxr import UsdPhysics
    from omni.isaac.dynamic_control import _dynamic_control
    import bricksim.core as core
    from experiments.stage2_idle_20261025.diagnose_breakage import threshold_snapshot
    stage=get_current_stage();robot=context['robot'];dc=_dynamic_control.acquire_dynamic_control_interface();actors={}
    for brick in context['bricks']:
        path='/World/envs/env_0/'+brick.name;p=dc.get_rigid_body_properties(dc.get_rigid_body(path));actors[path]=[int(p.solver_position_iteration_count),int(p.solver_velocity_iteration_count)]
    scenes=[{'path':str(p.GetPath()),'solverType':p.GetAttribute('physxScene:solverType').Get()} for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
    return {'physics_scenes':scenes,'source_actor_settings':actors,'robot_properties':robot_properties(robot),'source_properties':{n:{k:getattr(context['scene'][n.rsplit('/',1)[-1]].root_physx_view,m)().cpu().numpy().tolist() for k,m in [('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms')]} for n in ['/World/envs/env_0/plate_source']+list(actors)},'native_breakage':threshold_snapshot(core.get_breakage_thresholds()),'native_assembly':{'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force},'native_core_sha256':hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),'cooked_hashes':tool.cooked['canonical_sha256']}

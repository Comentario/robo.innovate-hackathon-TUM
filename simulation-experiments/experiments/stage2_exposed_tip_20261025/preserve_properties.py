"""Exact validated1769 targeted property route; no articulation-wide setters."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
base=SimpleNamespace(CONTACT=ROOT/'experiments/stage2_contact_20261025')
from experiments.stage2_contact_20261025.geometry import BODIES
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def install(scene,reference,output,protocol):
    import numpy as np
    original_reset=scene.reset;restores={'count':0}
    def reset_once(*args,**kwargs):
        import torch
        from isaaclab.sim import SimulationContext
        if restores['count']!=0:raise RuntimeError('Only one physical-property restore authorized')
        returned=original_reset(*args,**kwargs);restores['count']+=1
        robot=scene['robot'];view=robot.root_physx_view;sim=SimulationContext.instance()
        methods={'masses':'get_masses','inertias':'get_inertias','coms':'get_coms','stiffnesses':'get_dof_stiffnesses','dampings':'get_dof_dampings','effort_limits':'get_dof_max_forces'}
        def read():return {key:getattr(view,method)().cpu().numpy().tolist() for key,method in methods.items()}
        before=read();target=reference['robot_properties'];names=list(robot.body_names);link_paths=[list(map(str,paths)) for paths in view.link_paths]
        record={'count':restores['count'],'order':protocol['physical_property_initialization']['fixed_setter_order'],
            'completed_setters':[],'body_names':names,'link_paths':link_paths,
            'before':before,'after':None,'q_before':view.get_dof_positions().cpu().numpy().tolist(),
            'qdot_before':view.get_dof_velocities().cpu().numpy().tolist(),'physics_time_before_s':float(sim.current_time),
            'timing':'after_scene_reset_before_explicit_preassembly_step','sim_reset_internal_initialization_precedes_restore':True,
            'reference_sha256':sha(base.CONTACT/'proxy_reference.json'),
            'historical_link_mapping':'1754didnotrecordbody_names; unchangedpinnedasset/currentorder, exact10/11fingerlabels required'}
        save(output/'property_restoration.json',record)
        if len(names)!=len(target['masses'][0]) or names[10:12]!=['fr3_leftfinger','fr3_rightfinger'] or link_paths!=[['/World/envs/env_0/Robot/'+name for name in names]]:raise RuntimeError('Finger link order/path not verified')
        mask=[i for i in range(len(names)) if i not in (10,11)]
        for key in ('masses','coms','inertias'):
            if np.asarray(before[key]).shape!=np.asarray(target[key]).shape or not np.array_equal(np.asarray(before[key])[:,mask],np.asarray(target[key])[:,mask]):raise RuntimeError('Nonfinger physical properties already differ')
        if any(before[key]!=target[key] for key in ('stiffnesses','dampings','effort_limits')):raise RuntimeError('Actuator properties differ before preservation')
        indices=torch.tensor([0],dtype=torch.int64,device='cpu');target_views={};slices={}
        record.update(route='two_exact_finger_rigid_body_views',target_views={},targeted_writes=[])
        def read_target(rb):return {key:getattr(rb,method)().cpu().numpy().tolist() for key,method in (
            ('masses','get_masses'),('coms','get_coms'),('inertias','get_inertias'))}
        for label,index in (('left',10),('right',11)):
            path=BODIES[label];rb=sim.physics_sim_view.create_rigid_body_view(path)
            paths=list(map(str,rb.prim_paths));target_views[label]=rb
            slices[label]={'masses':np.asarray(target['masses'])[:,index:index+1],
                'coms':np.asarray(target['coms'])[:,index,:],'inertias':np.asarray(target['inertias'])[:,index,:]}
            buffers=read_target(rb)
            record['target_views'][label]={'path':path,'resolved_paths':paths,'count':int(rb.count),
                'articulation_link_index':index,'before':buffers,'after':None,'setter_indices':[0]}
            save(output/'property_restoration.json',record)
            if rb.count!=1 or paths!=[path]:raise RuntimeError('Exact one-finger RigidBodyView not resolved')
            for key in slices[label]:
                expected=np.asarray(before[key])[:,index:index+1] if key=='masses' else np.asarray(before[key])[:,index,:]
                if np.asarray(buffers[key]).shape!=expected.shape or not np.array_equal(buffers[key],expected):raise RuntimeError('Target view differs from articulation finger entry')
        for setter,key in (('set_masses','masses'),('set_coms','coms'),('set_inertias','inertias')):
            for label in ('left','right'):
                data=torch.tensor(slices[label][key],dtype=torch.float32,device='cpu')
                getattr(target_views[label],setter)(data,indices)
                record['targeted_writes'].append({'path':BODIES[label],'setter':setter,'view_index':0,'shape':list(data.shape)})
                save(output/'property_restoration.json',record)
            record['completed_setters'].append(setter);save(output/'property_restoration.json',record)
        for label,rb in target_views.items():record['target_views'][label]['after']=read_target(rb)
        record.update(after=read(),q_after=view.get_dof_positions().cpu().numpy().tolist(),
            qdot_after=view.get_dof_velocities().cpu().numpy().tolist(),physics_time_after_s=float(sim.current_time))
        save(output/'property_restoration.json',record)
        if record['after']!=target:raise RuntimeError('Strict1754 property readback failed; no alternateorder/tolerancefallback')
        if record['q_before']!=record['q_after'] or record['qdot_before']!=record['qdot_after'] or record['physics_time_before_s']!=record['physics_time_after_s']:raise RuntimeError('Propertypreservation changedq/qdot/time')
        return returned
    scene.reset=reset_once

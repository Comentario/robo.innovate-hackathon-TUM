"""Read-only effective contact/material rows after the frozen1822 initializer."""
import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
PATHS={'left':'/World/envs/env_0/Robot/fr3_leftfinger',
       'right':'/World/envs/env_0/Robot/fr3_rightfinger','coupon':'/World/envs/env_0/contact_coupon'}


def pin(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def getter_record(view,method):
    try:
        value=getattr(view,method)()
        data=value.detach().cpu().numpy().copy() if hasattr(value,'detach') else np.asarray(value).copy()
        if not np.isfinite(data).all():raise ValueError('Nonfinite runtime values: shape='+str(data.shape)+', dtype='+str(data.dtype))
        return {'status':'AVAILABLE','error':None,'values':data.tolist(),'shape':list(data.shape),'dtype':str(data.dtype)}
    except Exception as error:
        return {'status':'UNAVAILABLE','error':type(error).__name__+': '+str(error),'values':None,'shape':None,'dtype':None}


def capture_view(sim,path):
    result={'requested_path':path,'prim_paths':None,'count':None,'max_shapes':None,
        'row_to_collider_mapping':'UNKNOWN','view_error':None,'getters':{}}
    try:
        view=sim.physics_sim_view.create_rigid_body_view(path)
        result.update(prim_paths=list(view.prim_paths),count=int(view.count),max_shapes=int(view.max_shapes))
        if result['prim_paths']!=[path] or result['count']!=1:raise ValueError('Exact one-body view binding failed')
    except Exception as error:
        result['view_error']=type(error).__name__+': '+str(error);view=None
    for name in ('material_properties','contact_offsets','rest_offsets'):
        result['getters'][name]=getter_record(view,'get_'+name)
    return result


def usd_inventory(stage):
    from pxr import Usd,UsdPhysics,UsdShade
    def attribute(prim,name):
        attr=prim.GetAttribute(name);value=attr.Get() if attr else None
        if isinstance(value,float) and not math.isfinite(value):value={'nonfinite_scalar':'nan' if math.isnan(value) else 'inf' if value>0 else '-inf'}
        return {'value':value,'has_authored_value':bool(attr and attr.HasAuthoredValueOpinion())}
    result={}
    for label,path in PATHS.items():
        records=[]
        for prim in Usd.PrimRange(stage.GetPrimAtPath(path),Usd.TraverseInstanceProxies()):
            if not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            material,relation=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            mp=material.GetPrim() if material else None
            records.append({'path':str(prim.GetPath()),'type':prim.GetTypeName(),
                'collision_enabled':UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get(),
                'binding_purpose':'physics','material_path':str(material.GetPath()) if material else None,
                'binding_relationship':str(relation.GetPath()) if relation else None,
                'collider_attributes':{name:attribute(prim,name) for name in ('physxCollision:contactOffset','physxCollision:restOffset','physics:staticFriction','physics:dynamicFriction','physics:restitution')},
                'material_attributes':{name:attribute(mp,name) for name in ('physics:staticFriction','physics:dynamicFriction','physics:restitution','physxMaterial:frictionCombineMode','physxMaterial:restitutionCombineMode')} if mp else None,
                'runtime_row_index':None})
        result[label]=records
    return result


def replace_hook(original_main,read_hook):
    """Keep the parent's factory/lifecycle; never call its measured-trial hook."""
    def intercepted(*args,postassembly_hook=None,**kwargs):
        if postassembly_hook is None:raise RuntimeError('Missing pinned parent postassembly hook')
        def startup(**context):return read_hook(postassembly_hook,context)
        return original_main(*args,postassembly_hook=startup,**kwargs)
    return intercepted


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--protocol',type=Path,default=HERE/'protocol.json');parser.add_argument('--output',type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    protocol=json.loads(args.protocol.read_text());parent_pin=protocol['parent_runner']
    if protocol['execution_authorized'] is not True or pin(parent_pin['path'])['sha256']!=parent_pin['sha256']:raise RuntimeError('Unapproved/changed parent initializer')
    if '--mode' in remaining:raise RuntimeError('Diagnostic fixes parent mode to control')
    spec=importlib.util.spec_from_file_location('frozen1822_readback_parent',parent_pin['path']);parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
    from experiments.final_workcell_20261024 import render_core
    def read_hook(trial,context):
        from isaaclab.sim import get_current_stage
        from pxr import UsdGeom
        import bricksim.core as core
        import omni.physics.tensors.impl.api as tensor_api
        closure=inspect.getclosurevars(trial).nonlocals
        tool,plan,science,design,reference=[closure[name] for name in ('tool','plan','protocol','design','reference')]
        if Path(closure['output']).resolve()!=output:raise RuntimeError('Parent output binding differs')
        sim,robot,scene=context['sim'],context['robot'],context['scene'];coupon=scene['contact_coupon']
        entry={'time_s':float(sim.current_time),'q':robot.data.joint_pos[0].cpu().numpy().tolist(),'qdot':robot.data.joint_vel[0].cpu().numpy().tolist()}
        tool.validate(context);controller=parent.Controller(robot,science);initial=controller.state()
        tcp=np.asarray(initial['tcp_pose_table_wxyz'],float);expected=reference['tcp_pose_world_wxyz']
        if np.linalg.norm(tcp[:3]-np.asarray(expected[:3]))>plan['fixture_max_initial_pose_error_m'] or parent.qangle(tcp[3:],expected[3:])>plan['fixture_max_initial_angle_error_rad']:raise RuntimeError('Inherited initial TCP reference check failed')
        fixture=parent.fixture_initial(context,tool,initial,design,plan);parent.save(output/'fixture_initial.json',fixture)
        def snapshot():
            parts,edges=core.compute_connected_component('/World/envs/env_0/plate_source');cp,ce=core.compute_connected_component(PATHS['coupon'])
            return {'time_s':float(sim.current_time),'proprioception':controller.state(),
                'robot_link_poses_world_wxyz':robot.data.body_link_pose_w[0].cpu().numpy().tolist(),
                'source':{'parts':sorted(map(str,parts)),'edges':sorted(map(str,edges))},
                'coupon_component':{'parts':sorted(map(str,cp)),'edges':sorted(map(str,ce))},
                'coupon_state_world':coupon.data.root_state_w[0].cpu().numpy().tolist(),
                'settings':parent.settings(context,tool),'coupon_properties':parent.coupon_properties(coupon)}
        before=snapshot();views={label:capture_view(sim,path) for label,path in PATHS.items()};usd=usd_inventory(get_current_stage());after=snapshot()
        unchanged=before==after and entry['time_s']==before['time_s'] and entry['q']==before['proprioception']['q'] and entry['qdot']==before['proprioception']['qdot']
        graph_ok=len(before['source']['parts'])==301 and len(before['source']['edges'])==930 and before['coupon_component']=={'parts':[PATHS['coupon']],'edges':[]}
        report={'schema':'contact-material-offset-readback-v1','protocol_sha256':pin(args.protocol)['sha256'],'stage_meters_per_unit':float(UsdGeom.GetStageMetersPerUnit(get_current_stage())),
            'source_pins':{'parent_runner':pin(parent_pin['path']),'parent_protocol':pin(parent.HERE/'protocol.json'),
                'source_science':pin(parent.HERE/'source_science.json'),'tool_model':pin(inspect.getfile(type(tool))),'tensor_api':pin(inspect.getfile(tensor_api.RigidBodyView))},
            'initialization':{'explicit_preassembly_physics_steps':1,'measured_steps':0,'inherited_targeted_mass_restoration':True,
                'scope':'Existing reset/init/native preassembly and mass preservation retained; diagnostic makes no setters or extra steps.'},
            'shape_row_to_collider_mapping':'UNKNOWN','robot_body_names':list(robot.body_names),'hook_entry':entry,
            'before':before,'after':after,'views':views,'usd_colliders':usd,'fixture_initial_file':'fixture_initial.json',
            'settings_unchanged':unchanged,'graph_expected':graph_ok,'diagnostic_complete':unchanged and graph_ok,
            'physical_retry_authorized':False,'friction_pair_coefficient':'UNKNOWN; runtime material rows do not establish pair combination or row-to-PAD identity.'}
        parent.save(output/'readback.json',report)
        parent.save(output/'readback_complete.json',{'capture_completed':report['diagnostic_complete'],'measured_steps':0,'physical_retry_authorized':False})
        if not report['diagnostic_complete']:raise RuntimeError('Read-only initializer/state/graph invariant failed')
    original=render_core.main;render_core.main=replace_hook(original,read_hook)
    sys.argv=[sys.argv[0],*remaining,'--mode','control','--output',str(output)]
    try:parent.main()
    finally:render_core.main=original


if __name__=='__main__':main()

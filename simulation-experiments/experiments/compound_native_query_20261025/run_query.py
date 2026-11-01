"""One CPU cook/query of the approved48-cell compound; no contact authorization."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from experiments.stage2_active_query_20261025 import run_query as base


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def main():
    parser=argparse.ArgumentParser(add_help=False)
    for name in ('candidate','offline-audit','offline-manifest'):parser.add_argument('--'+name,type=Path,required=True)
    args,rest=parser.parse_known_args();sys.argv=[sys.argv[0],*rest]
    protocol=json.loads((HERE/'protocol.json').read_text())
    for path,key in ((args.candidate,'candidate_sha256'),(args.offline_audit,'audit_sha256'),(args.offline_manifest,'manifest_sha256')):
        if sha(path)!=protocol['offline_approval'][key]:raise RuntimeError('Offline approved input changed: '+key)
    candidate=json.loads(args.candidate.read_text());approved=json.loads(args.offline_audit.read_text())
    if not approved['offline_candidate_passed'] or len(candidate['cells'])!=48:raise RuntimeError('Exact48 offline-approved cells required')
    reference=json.loads((base.CONTACT/'proxy_reference.json').read_text())
    authoring={};properties={};cook={'tips':{}}

    def author(stage,root,config,output,scene):
        import numpy as np
        from pxr import UsdGeom,UsdPhysics,UsdShade,PhysxSchema
        from geometry import BODIES
        authoring.update(candidate_sha256=sha(args.candidate),offline_audit_sha256=sha(args.offline_audit),
            offline_manifest_sha256=sha(args.offline_manifest),registration_reference_sha256=sha(base.CONTACT/'proxy_reference.json'),tips={})
        reference_records={}
        for label in ('left','right'):
            parent=BODIES[label]+'/collisions/mesh_3';prim=stage.GetPrimAtPath(parent)
            if prim.GetTypeName()!='Cube' or prim.IsInstanceProxy():raise RuntimeError('Expected audited stock pad only')
            material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            if not material:raise RuntimeError('Pad physics material missing')
            material_path=str(material.GetPath());ops=UsdGeom.Xformable(prim).GetOrderedXformOps()
            UsdGeom.Xform.Define(stage,parent);UsdGeom.Xformable(prim).ClearXformOpOrder()
            for operation in ops:operation.GetAttr().Block()
            UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr(False)
            tip={'disabled_stock_parent':parent,'stock_parent_collision_enabled':UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get(),'reference_STL_only':True,'target_paths':[],'parts':{}}
            r=config['registration'][label];angle=np.deg2rad(r['rotation_z_deg']);c,s=np.cos(angle),np.sin(angle)
            rotation=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
            for cell in candidate['cells']:
                path=parent+'/part_'+cell['id'];v=np.asarray(cell['vertices_mm'])*config['stl_unit_m']@rotation.T+r['translation_m']
                mesh=UsdGeom.Mesh.Define(stage,path);mesh.CreatePointsAttr(v.tolist());mesh.CreateFaceVertexCountsAttr([3]*len(cell['triangles']))
                mesh.CreateFaceVertexIndicesAttr(np.asarray(cell['triangles'],int).ravel().tolist());mesh.CreateSubdivisionSchemeAttr('none')
                mesh.CreateExtentAttr([v.min(axis=0).tolist(),v.max(axis=0).tolist()])
                p=mesh.GetPrim();UsdPhysics.CollisionAPI.Apply(p).CreateCollisionEnabledAttr(True)
                UsdPhysics.MeshCollisionAPI.Apply(p).CreateApproximationAttr('convexHull')
                hull=PhysxSchema.PhysxConvexHullCollisionAPI.Apply(p);hull.CreateHullVertexLimitAttr(255)
                UsdShade.MaterialBindingAPI.Apply(p).Bind(material,materialPurpose='physics')
                bound,_=UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial('physics')
                xf=UsdGeom.Xformable(p).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0).GetInverse()
                if np.max(abs(np.array([list(row) for row in xf])-np.eye(4)))>1e-9:raise RuntimeError('Cell transform not identity')
                approximation=UsdPhysics.MeshCollisionAPI(p).GetApproximationAttr().Get();limit=hull.GetHullVertexLimitAttr().Get()
                if approximation!='convexHull' or limit!=255 or str(bound.GetPath())!=material_path:raise RuntimeError('Part settings/material readback mismatch')
                tip['target_paths'].append(path);tip['parts'][cell['id']]={'path':path,'vertices_finger_m':v.tolist(),
                    'triangles':cell['triangles'],'approximation':approximation,'hullVertexLimit':limit,
                    'physics_material_path':material_path,'collision_enabled':UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get(),'transform_finger':list(map(list,xf))}
            if len(tip['target_paths'])!=48:raise RuntimeError('Part inventory mismatch')
            authoring['tips'][label]=tip
            v,t,_=base.registered_vertices(config,label)
            reference_records[label]={'path':parent,'vertices_finger_m':v.tolist(),'triangles':t.tolist(),'material':material_path,
                'reference_only':True,'target_paths':tip['target_paths'],'cook_readback':{'approximation':'48 separate convexHull','hullVertexLimit':255},'transform_finger':list(map(list,UsdGeom.Xformable(prim).GetLocalTransformation()))}
        save(output/'compound_authoring.json',authoring)
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
        return reference_records

    def observe(phase,context):
        import numpy as np
        from pxr import UsdGeom,UsdPhysics,UsdShade,UsdUtils,PhysicsSchemaTools,PhysxSchema
        from isaaclab.sim import get_current_stage
        from omni.physx import get_physx_cooking_interface
        from omni.physx.bindings._physx import PhysxCollisionRepresentationResult
        from geometry import BODIES,cube_surface,metadata_scalar
        scene,robot=context['scene'],context['robot'];stage=get_current_stage();output=Path(context['output'])
        view=robot.root_physx_view
        robot_props={name:getattr(view,method)().cpu().numpy().tolist() for name,method in (
            ('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'),('stiffnesses','get_dof_stiffnesses'),
            ('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces'))}
        source={name:{key:getattr(scene[name].root_physx_view,method)().cpu().numpy().tolist() for key,method in (
            ('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'))} for name in ['plate_source']+[b.name for b in context['bricks']]}
        white={}
        for label in ('left','right'):
            white[label]=[];finger=UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0)
            for old in reference['white_colliders'][label]:
                p=stage.GetPrimAtPath(old['path'])
                if p.GetTypeName()!='Cube' or not UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get():raise RuntimeError('White collision changed')
                points,triangles=cube_surface(UsdGeom.Cube(p).GetSizeAttr().Get())
                xf=UsdGeom.Xformable(p).ComputeLocalToWorldTransform(0)*finger.GetInverse()
                from pxr import Gf
                points=np.asarray([list(xf.Transform(Gf.Vec3d(*v))) for v in points])
                material,_=UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial('physics')
                material_attrs={a.GetName():metadata_scalar(a.Get()) for a in (material.GetPrim().GetAttributes() if material else [])
                    if a.GetName().startswith(('physics:','physxMaterial:')) and isinstance(a.Get(),(float,int,bool,str))}
                props=PhysxSchema.PhysxCollisionAPI(p)
                row={'path':old['path'],'type':p.GetTypeName(),'enabled':UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get(),
                    'is_pad':False,'is_instance_proxy':p.IsInstanceProxy(),'approximation':'none',
                    'attributes':{a.GetName():{'usd_type':str(a.GetTypeName()),'sdk_value':metadata_scalar(a.Get()) if a.Get() is None or isinstance(a.Get(),(float,int,bool,str)) else str(a.Get())} for a in p.GetAttributes()},
                    'points_finger_m':points.tolist(),'triangle_indices':triangles,'authored_triangle_indices':triangles,
                    'reference_surface_kind':'analytic_cube_exact','bounds_finger_m':[points.min(axis=0).tolist(),points.max(axis=0).tolist()],
                    'contact_offset_m':metadata_scalar(props.GetContactOffsetAttr().Get()),'rest_offset_m':metadata_scalar(props.GetRestOffsetAttr().Get()),
                    'physics_material_path':str(material.GetPath()) if material else None,'physics_material_attributes':material_attrs,
                    'material_binding_status':'resolved' if material else 'unbound/default unknown'}
                for key,value in row.items():
                    if key in ('points_finger_m','bounds_finger_m'):
                        if np.max(abs(np.asarray(value)-old[key]))>1e-9:raise RuntimeError('White geometry differs from1754')
                    elif value!=old[key]:raise RuntimeError('White collider/material differs from1754: '+key)
                white[label].append(row)
        row={'robot':robot_props,'source':source,'white':white,'robot_matches_B0':robot_props==reference['robot_properties'],'white_matches_B0':True}
        properties[phase]=row;save(output/'property_checks.json',properties)
        if not row['robot_matches_B0']:raise RuntimeError('Robot mass/inertia/COM/actuators differ from1754')
        if phase=='initial':
            for label,tip in authoring['tips'].items():
                cook['tips'][label]={}
                for identity,part in tip['parts'].items():
                    answer={}
                    def ready(code,hulls):
                        answer.update(path=part['path'],result=str(code),result_valid=code==PhysxCollisionRepresentationResult.RESULT_VALID,hull_count=len(hulls or []),hulls=[])
                        for h in hulls or []:
                            answer['hulls'].append({'vertices_m':[[float(v.x),float(v.y),float(v.z)] for v in h.vertices],
                                'polygons':[{'plane':list(poly.plane),'indices':list(h.indices[poly.index_base:poly.index_base+poly.num_vertices])} for poly in h.polygons],
                                'vertex_count':len(h.vertices),'polygon_count':len(h.polygons)})
                    get_physx_cooking_interface().request_convex_collision_representation(stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt(),
                        collision_prim_id=PhysicsSchemaTools.sdfPathToInt(part['path']),run_asynchronously=False,on_result=ready)
                    cook['tips'][label][identity]=answer;save(output/'cook_results.json',cook)
                    if not answer.get('result_valid') or answer['hull_count']!=1:raise RuntimeError('Expected one valid native convex hull per explicit cell')
                    h=answer['hulls'][0]
                    if not 4<=h['vertex_count']<=255 or not 4<=h['polygon_count']<=255 or not np.isfinite(h['vertices_m']).all():raise RuntimeError('Native cooked geometry invalid/overCPUlimits')
        else:
            properties['unchanged']=properties['initial']==row;save(output/'property_checks.json',properties)
            if not properties['unchanged']:raise RuntimeError('Source/robot/white properties changed during query')
        return row

    base.main(proxy_author=author,protocol_path=HERE/'protocol.json',observation_hook=observe)


if __name__=='__main__':main()

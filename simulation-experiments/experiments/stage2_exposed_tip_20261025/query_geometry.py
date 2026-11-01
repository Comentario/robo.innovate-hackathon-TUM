"""Cook/readback and fixed active queries; no measured physics steps in G."""
import hashlib
import json
import os
import numpy as np
from pathlib import Path
from model import save,sha
from experiments.stage2_contact_20261025.geometry import BODIES


def capture(adapter,context,queries):
    from pxr import Gf,UsdGeom,UsdPhysics,UsdUtils,PhysicsSchemaTools
    from isaaclab.sim import get_current_stage
    from omni.physx import get_physx_cooking_interface,get_physx_scene_query_interface
    from omni.physx.bindings._physx import PhysxCollisionRepresentationResult
    from experiments.final_workcell_20261024 import render_core
    from omni.isaac.dynamic_control import _dynamic_control
    from diagnose_breakage import threshold_snapshot
    import bricksim.core as core
    sim,scene,robot=context['sim'],context['scene'],context['robot'];stage=get_current_stage();output=adapter.output
    names=['plate_source']+[b.name for b in context['bricks']]
    def snapshot():return {'time_s':float(sim.current_time),'q':robot.root_physx_view.get_dof_positions().cpu().numpy().tolist(),'qdot':robot.root_physx_view.get_dof_velocities().cpu().numpy().tolist(),'source':{n:{'pose':scene[n].root_physx_view.get_transforms().cpu().numpy().tolist(),'velocity':scene[n].root_physx_view.get_velocities().cpu().numpy().tolist()} for n in names}}
    def properties(view,robot=False):
        pairs=[('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms')]
        if robot:pairs += [('stiffnesses','get_dof_stiffnesses'),('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces')]
        return {key:getattr(view,method)().cpu().numpy().tolist() for key,method in pairs}
    robot_initial=properties(robot.root_physx_view,True);source_initial={n:properties(scene[n].root_physx_view) for n in names}
    initial=snapshot();parts,links=core.compute_connected_component('/World/envs/env_0/plate_source')
    if set(parts)!={'/World/envs/env_0/'+n for n in names} or len(parts)!=301 or len(links)!=930:raise RuntimeError('Native300/301/930 mismatch')
    if threshold_snapshot(core.get_breakage_thresholds())!=adapter.protocol['native_breakage'] or {'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force}!=adapter.protocol['native_assembly']:raise RuntimeError('Native physical settings mismatch')
    support=sim.get_physics_context().get_enable_scene_query_support()
    scenes=[{'path':str(p.GetPath()),'solver':p.GetAttribute('physxScene:solverType').Get(),'enable_scene_query_support':p.GetAttribute('physxScene:enableSceneQuerySupport').Get()} for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
    if support is not True or not scenes or any(p['solver']!='PGS' or p['enable_scene_query_support'] is not True for p in scenes):raise RuntimeError('Actual querysupport/PGS mismatch')
    dc=_dynamic_control.acquire_dynamic_control_interface();runtime={}
    for name in names[1:]:
        p=dc.get_rigid_body_properties(dc.get_rigid_body('/World/envs/env_0/'+name));runtime[name]=[int(p.solver_position_iteration_count),int(p.solver_velocity_iteration_count)]
    if any(v!=[32,4] for v in runtime.values()):raise RuntimeError('Actual source32/4 mismatch')
    result={'tips':{},'canonical_sha256':{}}
    for label,tip in adapter.records.items():
        result['tips'][label]={}
        canonical={}
        for kind,part in tip['parts'].items():
            answer={}
            def ready(code,hulls):
                answer.update(path=part['path'],result=str(code),result_valid=code==PhysxCollisionRepresentationResult.RESULT_VALID,hull_count=len(hulls or []),hulls=[])
                for h in hulls or []:answer['hulls'].append({'vertices_m':[[float(v.x),float(v.y),float(v.z)] for v in h.vertices],'polygons':[{'plane':list(p.plane),'indices':list(h.indices[p.index_base:p.index_base+p.num_vertices])} for p in h.polygons],'vertex_count':len(h.vertices),'polygon_count':len(h.polygons)})
            get_physx_cooking_interface().request_convex_collision_representation(stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt(),collision_prim_id=PhysicsSchemaTools.sdfPathToInt(part['path']),run_asynchronously=False,on_result=ready)
            result['tips'][label][kind]=answer;save(output/'cook_results.json',result)
            if not answer.get('result_valid') or answer['hull_count']!=1:raise RuntimeError('One valid convex hull per body/head required')
            h=answer['hulls'][0];v=np.asarray(h['vertices_m'])
            if not np.isfinite(v).all() or not 4<=h['vertex_count']<=255 or not 4<=h['polygon_count']<=255:raise RuntimeError('Actual CPU hull/count failure')
            # Order-invariant identity fingerprint; planes are not a fidelity oracle.
            planes=np.asarray([p['plane'] for p in h['polygons']],float);length=np.linalg.norm(planes[:,:3],axis=1)
            if not np.isfinite(planes).all() or np.any(length==0):raise RuntimeError('Nonfinite/zero cooked plane cannot be fingerprinted')
            planes=planes/length[:,None]
            quantum=adapter.cfg['canonical_hash_quantization']
            rows=np.c_[np.rint(planes[:,:3]/quantum['unit_normal']),np.rint(planes[:,3]/quantum['plane_offset_m'])].astype(np.int64)
            canonical[kind]={'vertices':sorted(map(tuple,np.rint(v/quantum['vertex_m']).astype(np.int64).tolist())),'normalized_planes':sorted(map(tuple,rows.tolist()))}
        result['canonical_sha256'][label]=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    save(output/'cook_results.json',result)
    records=[];frames={};api=get_physx_scene_query_interface()
    def vec(v):return [float(v.x),float(v.y),float(v.z)]
    def ray(identity,origin,direction,length,meta=None):
        hits=[]
        def callback(h):hits.append({'collision':str(h.collision),'rigid_body':str(h.rigid_body),'position_world_m':vec(h.position),'normal_world':vec(h.normal),'distance_m':float(h.distance),'face_index':int(h.face_index),'material':str(h.material),'protoIndex':int(h.protoIndex)});return True
        found=api.raycast_all(Gf.Vec3f(*origin),Gf.Vec3f(*direction),float(length),callback,False)
        row={'kind':'ray','id':identity,'origin_world_m':list(map(float,origin)),'direction_world':list(map(float,direction)),'length_m':float(length),'api_return_bool':bool(found),'callback_count':len(hits),'hits':hits,**(meta or {})};records.append(row);return row
    if queries:
        control=adapter.protocol['query_control'];a=ray('control_hit',control['ray_hit_origin_m'],control['ray_direction'],control['ray_length_m']);b=ray('control_miss',np.asarray(control['ray_hit_origin_m'])+control['miss_offset_world_m'],control['ray_direction'],control['ray_length_m'])
        for key,center in (('inside',control['center_world_m']),('outside',np.asarray(control['center_world_m'])+control['miss_offset_world_m'])):
            hits=[]
            def cb(h):hits.append({'collision':str(h.collision),'rigid_body':str(h.rigid_body),'protoIndex':int(h.protoIndex)});return True
            n=api.overlap_sphere(control['overlap_radius_m'],Gf.Vec3f(*center),cb,False);records.append({'kind':'overlap','id':'control_'+key,'api_return_count':int(n),'callback_count':len(hits),'hits':hits,'center_world_m':list(map(float,center)),'radius_m':control['overlap_radius_m']})
        save(output/'queries.json',records)
        if len(a['hits'])!=1 or a['hits'][0]['collision']!=control['path'] or not a['api_return_bool'] or b['hits'] or b['api_return_bool'] or records[2]['api_return_count']!=1 or records[2]['hits'][0]['collision']!=control['path'] or records[3]['api_return_count'] or records[3]['hits']:raise RuntimeError('Allhit cube hit/miss/overlap controls failed')
        if abs(a['hits'][0]['distance_m']-control['expected_hit_distance_m'])>control['distance_tolerance_m'] or np.max(abs(np.asarray(a['hits'][0]['normal_world'])-[0,0,1]))>control['normal_component_tolerance']:raise RuntimeError('Query metric/normal control failed')
    hand=UsdGeom.Xformable(stage.GetPrimAtPath('/World/envs/env_0/Robot/fr3_hand')).ComputeLocalToWorldTransform(0)
    for label,tip in adapter.records.items():
        xf=UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0);q=xf.ExtractRotationQuat();usd=np.r_[np.asarray(xf.ExtractTranslation()),q.GetReal(),q.GetImaginary()];phys=robot.data.body_link_pose_w[0,robot.body_names.index(BODIES[label].rsplit('/',1)[-1])].cpu().numpy()
        if np.linalg.norm(usd[:3]-phys[:3])>2e-6 or render_core.quaternion_error(usd[3:],phys[3:])>1e-4:raise RuntimeError('USD/PhysX finger-frame disagreement')
        frames[label]={'world_from_finger':list(map(list,xf)),'physics_body_link_pose_world_wxyz':phys.tolist(),'USD_pose_world_wxyz':usd.tolist()}
        if not queries:continue
        v=np.asarray(tip['parts']['body']['vertices_finger_m']);lo,hi=v.min(axis=0),v.max(axis=0);cfg=adapter.cfg['query'];padding=cfg['ray_padding_m']
        def local_ray(name,origin,direction,length,group,extra=None):
            ray(label+'_'+name,list(xf.Transform(Gf.Vec3d(*origin))),list(xf.TransformDir(Gf.Vec3d(*direction)).GetNormalized()),length,{'tip':label,'group':group,'origin_finger_m':list(map(float,origin)),'direction_finger':list(map(float,direction)),**(extra or {})})
        sign=1 if label=='left' else -1
        for ix,x in enumerate(cfg['grid_hand_x_offsets_m']):
            for iz,z in enumerate(np.linspace(lo[2]+cfg['end_margin_m'],hi[2]-cfg['end_margin_m'],9)):
                center=xf.GetInverse().Transform(hand.Transform(Gf.Vec3d(x,0,0)));origin=[center[0],lo[1]-padding if sign==1 else hi[1]+padding,z]
                local_ray(f'grid_{ix}_{iz}',origin,[0,sign,0],hi[1]-lo[1]+2*padding,'contact_grid')
        for axis in range(3):
            for direction in (-1,1):
                origin=(lo+hi)/2;origin[axis]=lo[axis]-padding if direction==1 else hi[axis]+padding;d=np.zeros(3);d[axis]=direction
                local_ray(f'bbox_{axis}_{direction}',origin,d,hi[axis]-lo[axis]+2*padding,'bounds_axis')
        for iz,z in enumerate(cfg['distal_z_m']):
            for direction in (-1,1):
                origin=[0.,lo[1]-padding if direction==1 else hi[1]+padding,z]
                local_ray(f'distal_{iz}_{direction}',origin,[0,direction,0],hi[1]-lo[1]+2*padding,'distal_taper')
        head=tip['head'];center=np.asarray(head['center_finger_m']);radius=head['radius_m'];height=head['height_m']
        for axis,direction in ((0,-1),(0,1),(1,-1),(1,1)):
            origin=center.copy();extent=radius if axis==0 else height/2;origin[axis]-=direction*(extent+padding);d=np.zeros(3);d[axis]=direction
            local_ray(f'head_{axis}_{direction}',origin,d,2*(extent+padding),'head_hit',{'target':tip['parts']['head']['path']})
        for direction in (-1,1):
            origin=center+[0,-direction*(height/2+padding),radius+.001]
            local_ray(f'head_miss_{direction}',origin,[0,direction,0],height+2*padding,'head_miss',{'target':tip['parts']['head']['path']})
        save(output/'queries.json',records)
    terminal=snapshot();endparts,endlinks=core.compute_connected_component('/World/envs/env_0/plate_source')
    report={'phase':adapter.phase,'initial':initial,'terminal':terminal,'frames':frames,'world_from_hand':list(map(list,hand)),'source_parts':sorted(parts),'native_connections':sorted(links),'runtime_source32_4':runtime,'physics_scenes':scenes,'scene_query_support_runtime':support,'native_breakage':threshold_snapshot(core.get_breakage_thresholds()),'native_assembly':{'enabled':core.get_assembly_thresholds().enabled,'required_force':core.get_assembly_thresholds().required_force},'native_core_sha256':sha(core.__file__),'dt_s':sim.get_physics_dt(),'OSQP_EPSILON':os.environ['OSQP_EPSILON'],'configured_query_support':adapter.configuration,'robot_properties_initial':robot_initial,'robot_properties_terminal':properties(robot.root_physx_view,True),'source_properties_initial':source_initial,'source_properties_terminal':{n:properties(scene[n].root_physx_view) for n in names},'preassembly_initialization_steps':1,'measured_postassembly_physics_steps':0,'cooked_hashes':result['canonical_sha256'],'queries':'queries.json' if queries else None,'query_count':len(records),'geometry':'exposed_geometry.json','property_restoration':'property_restoration.json','fixture_frames':adapter.fixture,'robot_properties_match_B0':True}
    save(output/'query_report.json',report)
    if report['robot_properties_initial']!=report['robot_properties_terminal'] or report['source_properties_initial']!=report['source_properties_terminal']:raise RuntimeError('Static cook/query changed physical properties')
    if initial!=terminal or set(parts)!=set(endparts) or set(links)!=set(endlinks):raise RuntimeError('Static cook/query changed measured state or graph')
    if queries and len(records)!=216:raise RuntimeError('Frozen216 query count mismatch')
    return result

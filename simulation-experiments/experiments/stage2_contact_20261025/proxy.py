"""One frozen supplied-tip decomposition; query actual cooked representations."""
import hashlib
import json
import math
from pathlib import Path
import struct
import time


def canonical_hash(hulls,config):
    import numpy as np
    q=config['canonical_hash'];keys=[]
    for hull in hulls:
        vertices=sorted(set(map(tuple,np.rint(np.asarray(hull['vertices_m'])/q['vertex_quantum_m']).astype('int64'))))
        planes=np.asarray(hull['planes'],float);planes=planes/np.linalg.norm(planes[:,:3],axis=1)[:,None]
        planes[:,:3]/=q['unit_plane_normal_quantum'];planes[:,3]/=q['plane_offset_quantum_m']
        planes=sorted(set(map(tuple,np.rint(planes).astype('int64'))))
        keys.append({'vertices':[[int(v) for v in row] for row in vertices],
                     'planes':[[int(v) for v in row] for row in planes]})
    keys.sort(key=lambda value:json.dumps(value,sort_keys=True))
    return hashlib.sha256(json.dumps(keys,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def inside_any(point,hulls,epsilon):
    import numpy as np
    return any(np.max(np.asarray(h['planes'])[:,:3]@point+np.asarray(h['planes'])[:,3]) <= epsilon for h in hulls)


def outside_all(point,hulls,epsilon):
    import numpy as np
    return all(np.max(np.asarray(h['planes'])[:,:3]@point+np.asarray(h['planes'])[:,3]) > epsilon for h in hulls)


def cooking_progress(output,value):
    """Publish the small watchdog record atomically for the foreground supervisor."""
    temporary=output/'proxy_cooking_progress.tmp'
    temporary.write_text(json.dumps(value)+'\n')
    temporary.replace(output/'proxy_cooking_progress.json')


def author_and_query(stage,root,config,output,approved=None):
    import numpy as np
    from pxr import UsdGeom,UsdPhysics,PhysxSchema,UsdUtils,PhysicsSchemaTools
    from omni.physx import get_physx_cooking_interface
    from omni.physx.bindings._physx import PhysxCollisionRepresentationResult
    from geometry import BODIES
    data=(root/config['stl']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=config['stl_sha256']:raise RuntimeError('Supplied STL hash mismatch')
    count=struct.unpack_from('<I',data,80)[0]
    if len(data)!=84+50*count:raise RuntimeError('Unexpected STL encoding')
    raw=np.asarray([list(struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])) for i in range(count)])
    vertices,inverse=np.unique(raw.reshape(-1,3),axis=0,return_inverse=True);triangles=inverse.reshape(-1,3)
    reference_path=Path(__file__).with_name(config['reference'])
    if hashlib.sha256(reference_path.read_bytes()).hexdigest()!=config['reference_sha256']:raise RuntimeError('B0 proxy reference changed')
    artifact={'schema':'R3-cooked-query-v1','config':config,'config_sha256':hashlib.sha256(Path(__file__).with_name('proxy_config.json').read_bytes()).hexdigest(),
        'frame':'finger_local_m','tips':{},'query_provenance':'Public SDK collision-representation cooking query for exact stage/prim; not a direct live PxShape vertex getter',
        'source_stl_sha256':config['stl_sha256'],'stl_triangles':triangles.tolist()}
    started=time.monotonic()
    cooking_progress(output,{'status':'cooking','started_monotonic_s':started,'limit_s':config['budgets']['cook_query_total_s']})
    for label in ('left','right'):
        path=BODIES[label]+'/collisions/mesh_3';prim=stage.GetPrimAtPath(path)
        if prim.GetTypeName()!='Cube' or prim.IsInstanceProxy():raise RuntimeError('Expected the audited stock pad Cube only: '+path)
        r=config['registration'][label];angle=math.radians(r['rotation_z_deg']);c,s=math.cos(angle),math.sin(angle)
        rotation=np.asarray([[c,-s,0],[s,c,0],[0,0,1.]])
        baked=(vertices*config['stl_unit_m'])@rotation.T+np.asarray(r['translation_m'])
        old_ops=UsdGeom.Xformable(prim).GetOrderedXformOps()
        mesh=UsdGeom.Mesh.Define(stage,path)
        UsdGeom.Xformable(mesh).ClearXformOpOrder()
        for op in old_ops:op.GetAttr().Block()
        mesh.CreatePointsAttr(baked.tolist());mesh.CreateFaceVertexCountsAttr([3]*count)
        mesh.CreateFaceVertexIndicesAttr(triangles.ravel().tolist());mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateExtentAttr([baked.min(axis=0).tolist(),baked.max(axis=0).tolist()])
        UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexDecomposition')
        api=PhysxSchema.PhysxConvexDecompositionCollisionAPI.Apply(prim)
        for key,value in config['collision'].items():
            if key!='approximation':getattr(api,'Create'+key[0].upper()+key[1:]+'Attr')(value)
        relative=UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0).GetInverse()
        matrix=np.asarray([list(row) for row in relative])
        if np.max(abs(matrix-np.eye(4)))>1e-9:raise RuntimeError('Proxy collider transform is not identity in finger frame')
        readback={key:getattr(api,'Get'+key[0].upper()+key[1:]+'Attr')().Get() for key in config['collision'] if key!='approximation'}
        if any(abs(readback[key]-value)>config['schema_float_readback_atol'] if isinstance(value,float) else readback[key]!=value
               for key,value in config['collision'].items() if key!='approximation'):
            raise RuntimeError('Cooking attribute readback mismatch')
        answer={}
        def result(code,convexes):
            answer['result']=str(code);answer['valid']=code==PhysxCollisionRepresentationResult.RESULT_VALID;answer['hulls']=[]
            for hull in convexes or []:
                hull_vertices=[[float(v.x),float(v.y),float(v.z)] for v in hull.vertices]
                planes=[list(p.plane) for p in hull.polygons]
                polygons=[list(hull.indices[p.index_base:p.index_base+p.num_vertices]) for p in hull.polygons]
                answer['hulls'].append({'vertices_m':hull_vertices,'planes':planes,'polygons':polygons})
        get_physx_cooking_interface().request_convex_collision_representation(
            stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt(),collision_prim_id=PhysicsSchemaTools.sdfPathToInt(path),
            run_asynchronously=False,on_result=result)
        artifact['tips'][label]={'path':path,'frame':'finger_local_m','identity_transform':matrix.tolist(),
            'stl_points_finger_m':baked.tolist(),'cooked_hulls':answer.get('hulls',[]),
            'cooking_result':answer.get('result','callback missing'),'cook_parameters_readback':readback}
        (output/'proxy_geometry.json').write_text(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
        if time.monotonic()-started>config['budgets']['cook_query_total_s']:raise RuntimeError('Frozen cooking wall budget exceeded')
        if not answer.get('valid') or not 1<len(answer['hulls'])<=config['collision']['maxConvexHulls']:raise RuntimeError('Invalid/missing/nondecomposed cooked result')
        for hull in answer['hulls']:
            v=np.asarray(hull['vertices_m']);planes=np.asarray(hull['planes'],float)
            if len(v)>config['collision']['hullVertexLimit'] or not np.isfinite(v).all() or not np.isfinite(planes).all():raise RuntimeError('Invalid cooked hull buffers')
            lengths=np.linalg.norm(planes[:,:3],axis=1)
            if np.any(lengths<1e-12):raise RuntimeError('Invalid cooked plane normal')
            planes/=lengths[:,None];hull['planes']=planes.tolist()
            if np.max(v@planes[:,:3].T+planes[:,3])>config['fidelity']['membership_epsilon_m']:raise RuntimeError('Cooked plane frame/orientation mismatch')
        all_vertices=np.concatenate([np.asarray(h['vertices_m']) for h in answer['hulls']])
        bounds=np.asarray([all_vertices.min(axis=0),all_vertices.max(axis=0)])
        if np.max(abs(bounds-np.asarray([baked.min(axis=0),baked.max(axis=0)])))>config['fidelity']['maximum_outer_bound_error_m']:raise RuntimeError('Cooked frame/bounds mismatch')
        digest=canonical_hash(answer['hulls'],config)
        if approved is not None and digest!=approved['tips'][label]['canonical_sha256']:raise RuntimeError('Own cooked hulls do not match independently approved G')
        artifact['tips'][label]={'path':path,'frame':'finger_local_m','identity_transform':matrix.tolist(),
            'stl_points_finger_m':baked.tolist(),'cooked_hulls':answer['hulls'],'canonical_sha256':digest,
            'cooking_result':answer['result'],'cook_parameters_readback':readback,'cooked_bounds_m':bounds.tolist()}
        (output/'proxy_geometry.json').write_text(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
    artifact['cook_seconds']=time.monotonic()-started
    (output/'proxy_geometry.json').write_text(json.dumps(artifact,indent=2,allow_nan=False)+'\n')
    cooking_progress(output,{'status':'complete','seconds':artifact['cook_seconds']})
    return artifact

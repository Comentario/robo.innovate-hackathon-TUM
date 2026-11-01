"""Stock collider audit and explicit surface-compatibility checks, SI meters."""
import json
import math
from pathlib import Path

ROBOT='/World/envs/env_0/Robot'
BODIES={'left':ROBOT+'/fr3_leftfinger','right':ROBOT+'/fr3_rightfinger',
        'coupon':'/World/envs/env_0/contact_coupon'}


def metadata_scalar(value):
    if isinstance(value,float) and not math.isfinite(value):
        return {'nonfinite_scalar':'nan' if math.isnan(value) else 'inf' if value>0 else '-inf'}
    return value


def cube_surface(size):
    """Exact Cube local surface, including the authored/default USD size."""
    size=float(size)
    if not math.isfinite(size) or size<=0:raise RuntimeError('Invalid Cube size')
    half=size/2
    points=[[x,y,z] for x in (-half,half) for y in (-half,half) for z in (-half,half)]
    quads=((0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3))
    triangles=[[f[0],f[1],f[2]] for f in quads]+[[f[0],f[2],f[3]] for f in quads]
    return points,triangles


def distance_to_triangles(point, vertices, triangles):
    """Minimum unsigned point-to-triangle distance; faces and clamped edges."""
    import numpy as np
    t=np.asarray(vertices,float)[np.asarray(triangles,int)]
    a,b,c=t[:,0],t[:,1],t[:,2]
    ab,ac=b-a,c-a; n=np.cross(ab,ac); n2=np.sum(n*n,axis=1)
    ap=np.asarray(point)-a
    projected=np.asarray(point)-n*(np.sum(ap*n,axis=1)/np.maximum(n2,1e-30))[:,None]
    v=projected-a
    d00=np.sum(ab*ab,axis=1);d01=np.sum(ab*ac,axis=1);d11=np.sum(ac*ac,axis=1)
    d20=np.sum(v*ab,axis=1);d21=np.sum(v*ac,axis=1)
    den=d00*d11-d01*d01
    u=(d11*d20-d01*d21)/np.maximum(den,1e-30)
    w=(d00*d21-d01*d20)/np.maximum(den,1e-30)
    interior=(u>=0)&(w>=0)&(u+w<=1)&(n2>1e-30)
    best=np.min(np.linalg.norm(projected[interior]-point,axis=1)) if interior.any() else float('inf')
    for p,q in ((a,b),(b,c),(c,a)):
        edge=q-p; fraction=np.clip(np.sum((point-p)*edge,axis=1)/np.maximum(np.sum(edge*edge,axis=1),1e-30),0,1)
        best=min(best,float(np.linalg.norm(p+fraction[:,None]*edge-point,axis=1).min()))
    return float(best)


def audit(stage, output, cooked=None):
    import numpy as np
    from scipy.spatial import ConvexHull
    from pxr import Gf,Usd,UsdGeom,UsdPhysics,UsdShade,PhysxSchema
    result={'surface_provenance':'Composed authored collision surface / mathematical convex hull, not an exported PhysX cooked mesh',
            'fingers':{}}
    # Inventory BOTH fingers completely before validating any one geometry.
    # A setup stop must not hide a second unsupported collider type.
    for label in ('left','right'):
        rows=[]
        for prim in Usd.PrimRange(stage.GetPrimAtPath(BODIES[label]),Usd.TraverseInstanceProxies()):
            if not prim.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():continue
            material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            rows.append({'path':str(prim.GetPath()),'type':prim.GetTypeName(),'enabled':True,
                'is_pad':str(prim.GetPath())==BODIES[label]+'/collisions/mesh_3',
                'physics_material_path':str(material.GetPath()) if material else None,
                'attributes':{a.GetName():{'usd_type':str(a.GetTypeName()),
                    'sdk_value':metadata_scalar(a.Get()) if a.Get() is None or isinstance(a.Get(),(float,int,bool,str)) else str(a.Get())}
                    for a in prim.GetAttributes()}})
        result['fingers'][label]={'body_path':BODIES[label],'colliders':rows}
    Path(output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for label in ('left','right'):
        root=BODIES[label]; finger=stage.GetPrimAtPath(root)
        inverse=UsdGeom.Xformable(finger).ComputeLocalToWorldTransform(0).GetInverse()
        rows=result['fingers'][label]['colliders']
        for row in rows:
            prim=stage.GetPrimAtPath(row['path'])
            xf=UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)*inverse
            if prim.IsA(UsdGeom.Cube):
                local_points,triangles=cube_surface(UsdGeom.Cube(prim).GetSizeAttr().Get())
                approximation='none';surface_kind='analytic_cube_exact'
            elif prim.IsA(UsdGeom.Mesh):
                mesh=UsdGeom.Mesh(prim);local_points=mesh.GetPointsAttr().Get()
                indices=list(mesh.GetFaceVertexIndicesAttr().Get());triangles=[];start=0
                for count in mesh.GetFaceVertexCountsAttr().Get():
                    face=indices[start:start+count];start+=count
                    triangles.extend([face[0],face[k],face[k+1]] for k in range(1,count-1))
                approximation=UsdPhysics.MeshCollisionAPI(prim).GetApproximationAttr().Get()
                surface_kind='mathematical_convex_hull' if approximation=='convexHull' else 'convex_authored_mesh'
                if approximation=='convexDecomposition' and row['is_pad'] and cooked is not None:
                    actual=cooked['tips'][label]
                    if actual['path']!=str(prim.GetPath()):raise RuntimeError('Cooked data belongs to another pad')
                    local_points=[];triangles=[]
                    for component in actual['cooked_hulls']:
                        offset=len(local_points);local_points.extend(component['vertices_m'])
                        for face in component['polygons']:
                            triangles.extend([offset+face[0],offset+face[k],offset+face[k+1]] for k in range(1,len(face)-1))
                    row['cooked_hulls']=actual['cooked_hulls'];row['cooked_canonical_sha256']=actual['canonical_sha256']
                    surface_kind='cooked_convex_union'
            else:raise RuntimeError('Unsupported stock collision type: '+str(prim.GetPath()))
            points=np.asarray([list(xf.Transform(Gf.Vec3d(p))) for p in local_points],float)
            hull=ConvexHull(points)
            # Mesh input must itself have hull support planes, not an arbitrary concave input.
            volume=abs(sum(np.dot(points[i],np.cross(points[j],points[k])) for i,j,k in triangles)/6)
            reference=triangles if approximation=='none' or surface_kind=='cooked_convex_union' else hull.simplices.tolist()
            material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            props=PhysxSchema.PhysxCollisionAPI(prim)
            material_attrs={a.GetName():metadata_scalar(a.Get()) for a in (material.GetPrim().GetAttributes() if material else [])
                if a.GetName().startswith(('physics:','physxMaterial:')) and isinstance(a.Get(),(float,int,bool,str))}
            row.update({'path':str(prim.GetPath()),'is_pad':str(prim.GetPath())==root+'/collisions/mesh_3',
                'enabled':True,'is_instance_proxy':prim.IsInstanceProxy(),'approximation':approximation,
                'points_finger_m':points.tolist(),'triangle_indices':reference,
                'authored_triangle_indices':triangles,'reference_surface_kind':surface_kind,
                'bounds_finger_m':[points.min(axis=0).tolist(),points.max(axis=0).tolist()],
                'contact_offset_m':metadata_scalar(props.GetContactOffsetAttr().Get()),'rest_offset_m':metadata_scalar(props.GetRestOffsetAttr().Get()),
                'physics_material_path':str(material.GetPath()) if material else None,'physics_material_attributes':material_attrs,
                'material_binding_status':'resolved' if material else 'unbound/default unknown'})
            Path(output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            if surface_kind!='cooked_convex_union' and (approximation not in ('convexHull','none') or (approximation=='none' and abs(volume-hull.volume)>max(1e-12,hull.volume*1e-4))):
                raise RuntimeError('Stock cooked surface cannot be safely represented: '+str(prim.GetPath()))
        pads=[row for row in rows if row['is_pad']]
        if len(pads)!=1 or len(rows)<2 or not (pads[0]['physics_material_path'] or '').endswith('/PhysicsMaterials/FingerPad'):
            raise RuntimeError('Stock pad/white-finger collision separation is ambiguous')
        bound=pads[0]['bounds_finger_m']
        inner=bound[0][1] if label=='left' else bound[1][1]
        result['fingers'][label]={'body_path':root,'pad_path':pads[0]['path'],
            'inner_plane_y_m':inner,'bounds_finger_m':bound,'colliders':rows}
    Path(output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def own_point(point_finger, separation, finger, protocol, outward_finger=None):
    pad=[];white=[]
    for collider in finger['colliders']:
        distance=distance_to_triangles(point_finger,collider['points_finger_m'],collider['triangle_indices'])
        (pad if collider['is_pad'] else white).append(distance)
    tolerance=abs(float(separation))+protocol['point_gate']['surface_slack_m']
    dp,dw=min(pad),min(white)
    result={'distance_pad_m':dp,'distance_white_m':dw,'tolerance_m':tolerance,
        'unique_pad':bool(dp<=tolerance and dw>tolerance+protocol['point_gate']['white_clearance_extra_m'])}
    actual=next((c for c in finger['colliders'] if c['is_pad'] and 'cooked_hulls' in c),None)
    if actual is not None:
        import numpy as np
        from proxy import inside_any,outside_all
        cfg=protocol['proxy_fidelity'];normal=np.asarray(outward_finger,float) if outward_finger is not None else np.zeros(3)
        norm=np.linalg.norm(normal)
        if not np.isfinite(normal).all() or norm<1e-12:
            result.update(unique_pad=False,outer_boundary_crossing=False)
        else:
            normal/=norm;delta=tolerance+cfg['contact_ray_extra_m'];epsilon=cfg['membership_epsilon_m']
            outside=outside_all(np.asarray(point_finger)+delta*normal,actual['cooked_hulls'],epsilon)
            inside=inside_any(np.asarray(point_finger)-delta*normal,actual['cooked_hulls'],epsilon)
            result.update(unique_pad=bool(result['unique_pad'] and outside and inside),
                outer_boundary_crossing=bool(outside and inside),outward_finger=normal.tolist(),
                ray_outside_all=outside,ray_inside_any=inside)
    return result


def self_test():
    import numpy as np
    assert abs(distance_to_triangles([.2,.2,1],[[0,0,0],[1,0,0],[0,1,0]],[[0,1,2]])-1)<1e-12
    assert abs(distance_to_triangles([2,0,0],[[0,0,0],[1,0,0],[0,1,0]],[[0,1,2]])-1)<1e-12
    print('Triangle face/edge distance contracts: PASS')
    points,triangles=cube_surface(2.)
    assert len(points)==8 and len(triangles)==12
    # Nonuniform scale, quarter-turn and translation: compose exactly once.
    rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]])
    points=(np.asarray(points)*[.01,.02,.03])@rotation.T+[.1,.2,.3]
    assert np.allclose(points.min(axis=0),[.08,.19,.27]) and np.allclose(points.max(axis=0),[.12,.21,.33])
    volume=abs(sum(np.dot(points[i],np.cross(points[j],points[k])) for i,j,k in triangles)/6)
    assert abs(volume-.02*.04*.06)<1e-14
    assert distance_to_triangles(np.array([.12,.2,.3]),points,triangles)<1e-14
    assert abs(distance_to_triangles(np.array([.13,.2,.3]),points,triangles)-.01)<1e-14
    print('Cube8corners/12triangles transformed bounds/surface/scaled-volume: PASS')


if __name__=='__main__':self_test()

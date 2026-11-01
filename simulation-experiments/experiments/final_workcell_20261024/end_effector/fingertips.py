"""Native finger visual audit before registering the user-supplied tip mesh."""
import json


def audit_native_fingers(stage, output):
    from pxr import Gf, Usd, UsdGeom, UsdShade
    records = []
    for name in ('fr3_leftfinger', 'fr3_rightfinger'):
        finger = stage.GetPrimAtPath('/World/envs/env_0/Robot/'+name)
        inverse = UsdGeom.Xformable(finger).ComputeLocalToWorldTransform(0).GetInverse()
        for prim in Usd.PrimRange(finger):
            if prim.GetTypeName() != 'Mesh':
                continue
            xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)*inverse
            points = [list(xf.Transform(Gf.Vec3d(p))) for p in UsdGeom.Mesh(prim).GetPointsAttr().Get()]
            records.append({'finger':name,'path':str(prim.GetPath()),'bounds_finger_m':
                [[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]],
                'point_count':len(points),'points_finger_m':points,
                'face_counts':list(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get()),
                'face_indices':list(UsdGeom.Mesh(prim).GetFaceVertexIndicesAttr().Get()),
                'source_layers':[{'path':str(v.layer.realPath),'prim':str(v.path)} for v in prim.GetPrimStack()],
                'material_subsets':[{'path':str(q.GetPath()),'face_indices':list(UsdGeom.Subset(q).GetIndicesAttr().Get()),
                    'material':str(UsdShade.MaterialBindingAPI(q).ComputeBoundMaterial()[0].GetPath())}
                    for q in prim.GetChildren() if q.GetTypeName()=='GeomSubset']})
    (output/'native_finger_visual_audit.json').write_text(json.dumps(records))
    return {'status':'STL registration pending native-pad geometry audit','mesh_records':len(records)}


def nominal_mount_parameters(spec, left):
    """User-confirmed orientation with explicitly nominal visual anchors."""
    sign = 1 if left else -1
    unit = spec['assumed_stl_unit_m']
    return sign*90., [sign*spec['width_center_cad_y_mm']*unit,
        sign*(spec['stock_pad_backplane_abs_finger_y_m']+spec['body_mount_cad_x_mm']*unit),
        spec['stock_pad_proximal_finger_z_m']+spec['broad_end_cad_z_mm']*unit]


def add_updated_tip_visuals(stage, cfg, output):
    """Flip taper distal and boss toward support; stock collisions remain."""
    import hashlib
    import struct
    from pathlib import Path
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdPhysics

    spec = cfg['final_layout'].get('fingertip_visual')
    if spec is None:
        return None
    path = Path(__file__).parent/spec['asset']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise RuntimeError('Unexpected supplied fingertip mesh')
    count = struct.unpack_from('<I',data,80)[0]
    if len(data) != 84+50*count:
        raise ValueError('Expected binary STL')
    points = []
    for i in range(count):
        points.extend([Gf.Vec3f(*p) for p in struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])])
    root = '/World/envs/env_0/Robot'
    mat = UsdShade.Material.Define(stage, root+'/UpdatedTipVisualMaterial')
    shader = UsdShade.Shader.Define(stage,str(mat.GetPath())+'/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.025,.026,.028))
    shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.65)
    shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(0.)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    screw_spec = spec['outside_screw_visual']
    screw_material = UsdShade.Material.Define(stage,root+'/UpdatedTipScrewVisualMaterial')
    screw_shader = UsdShade.Shader.Define(stage,str(screw_material.GetPath())+'/Surface')
    screw_shader.CreateIdAttr('UsdPreviewSurface')
    screw_shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.28,.29,.30))
    screw_shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.35)
    screw_shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.7)
    screw_material.CreateSurfaceOutput().ConnectToSource(screw_shader.ConnectableAPI(),'surface')
    def collision_fingerprint(parent):
        rows = [{'path':str(p.GetPath()), 'type':p.GetTypeName(),
            'attributes':[(a.GetName(),str(a.Get())) for a in p.GetAttributes()],
            'relationships':[(r.GetName(),list(map(str,r.GetTargets()))) for r in p.GetRelationships()]}
            for p in Usd.PrimRange(stage.GetPrimAtPath(parent), Usd.TraverseInstanceProxies())
            if p.HasAPI(UsdPhysics.CollisionAPI)]
        return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()

    reports = []
    boss_y, boss_z = spec['boss_axis_center_cad_yz_mm']
    probes = {'taper_distal':[0.,spec['width_center_cad_y_mm'],spec['taper_distal_cad_z_mm']],
        'body_mount_axis':[spec['body_mount_cad_x_mm'],boss_y,boss_z],
        'boss_front_axis':[spec['boss_front_cad_x_mm'],boss_y,boss_z],
        'broad_grip_axis':[0.,boss_y,boss_z], 'broad_proximal':[0.,boss_y,spec['broad_end_cad_z_mm']]}
    for name, left in (('fr3_leftfinger',True),('fr3_rightfinger',False)):
        angle, translation = nominal_mount_parameters(spec,left)
        parent = root+'/'+name
        collision_before = collision_fingerprint(parent)
        original = UsdGeom.Mesh(stage.GetPrimAtPath(parent+'/visuals'))
        subset = UsdGeom.Subset(stage.GetPrimAtPath(parent+'/visuals/material_1'))
        pad_faces = list(subset.GetIndicesAttr().Get())
        if len(pad_faces) != 262 or len(original.GetFaceVertexCountsAttr().Get()) != 624:
            raise RuntimeError('Native combined finger/pad geometry changed; refusing broad visual removal')
        white = UsdGeom.Subset(stage.GetPrimAtPath(parent+'/visuals/material_0'))
        def white_fingerprint():
            return hashlib.sha256(json.dumps({'points':list(map(list,original.GetPointsAttr().Get())),
                'indices':list(original.GetFaceVertexIndicesAttr().Get()),
                'white_faces':list(white.GetIndicesAttr().Get())},sort_keys=True).encode()).hexdigest()
        white_before = white_fingerprint()
        # Mesh holes suppress only the old pad triangles; white finger is kept.
        original.CreateHoleIndicesAttr(pad_faces)
        tip = UsdGeom.Xform.Define(stage,parent+'/UpdatedTipSTLVisual')
        transform = UsdGeom.Xformable(tip)
        transform.AddTranslateOp().Set(Gf.Vec3d(*translation))
        transform.AddRotateZOp().Set(angle)
        transform.AddRotateYOp().Set(180.)
        transform.AddScaleOp().Set(Gf.Vec3f(*([spec['assumed_stl_unit_m']]*3)))
        mesh = UsdGeom.Mesh.Define(stage,str(tip.GetPath())+'/Mesh')
        mesh.CreatePointsAttr(points)
        mesh.CreateFaceVertexCountsAttr([3]*count)
        mesh.CreateFaceVertexIndicesAttr(list(range(3*count)))
        mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDoubleSidedAttr(True)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
        tip.GetPrim().CreateAttribute('registrationStatus',Sdf.ValueTypeNames.String).Set(spec['status'])
        finger_inverse = UsdGeom.Xformable(stage.GetPrimAtPath(parent)).ComputeLocalToWorldTransform(0).GetInverse()
        xf = UsdGeom.Xformable(mesh).ComputeLocalToWorldTransform(0)*finger_inverse
        registered = [list(xf.Transform(Gf.Vec3d(v))) for v in points]
        bounds = [[min(v[i] for v in registered) for i in range(3)],
                  [max(v[i] for v in registered) for i in range(3)]]
        if abs(bounds[0][2]-spec['stock_pad_proximal_finger_z_m']) > 1e-6 or abs(bounds[1][2]-spec['distal_tip_finger_z_m']) > 1e-6:
            raise RuntimeError('Registered pad proximal alignment or derived distal extent failed')
        actual_probes = {key:list(xf.Transform(Gf.Vec3d(*point))) for key,point in probes.items()}
        grip_normal = list(xf.TransformDir(Gf.Vec3d(1,0,0)).GetNormalized())
        boss_direction = list(xf.TransformDir(Gf.Vec3d(-1,0,0)).GetNormalized())
        # Simple local outside-face estimate; this is not screw-hole metrology.
        sign = 1 if left else -1
        radius, protrusion = screw_spec['head_radius_m'], screw_spec['outward_protrusion_m']
        center = actual_probes['boss_front_axis']
        native_xf = UsdGeom.Xformable(original).ComputeLocalToWorldTransform(0)*finger_inverse
        indices = list(original.GetFaceVertexIndicesAttr().Get())
        white_ids = sorted({indices[3*f+k] for f in white.GetIndicesAttr().Get() for k in range(3)})
        native_points = original.GetPointsAttr().Get()
        nearby = [native_xf.Transform(Gf.Vec3d(native_points[i])) for i in white_ids]
        nearby = [p for p in nearby if abs(p[2]-center[2]) <= radius]
        outside = max(sign*p[1] for p in nearby) if nearby else spec['stock_pad_backplane_abs_finger_y_m']+screw_spec['fallback_wall_thickness_m']
        base_y = sign*max(outside,sign*center[1])
        end_y = base_y+sign*protrusion
        head_center = [center[0],(base_y+end_y)/2,center[2]]
        screw_parent = UsdGeom.Xform.Define(stage,parent+'/UpdatedTipFastenerVisual')
        cylinder = UsdGeom.Cylinder.Define(stage,str(screw_parent.GetPath())+'/Head')
        cylinder.CreateAxisAttr('Y');cylinder.CreateRadiusAttr(radius);cylinder.CreateHeightAttr(protrusion)
        cylinder.AddTranslateOp().Set(Gf.Vec3d(*head_center))
        UsdShade.MaterialBindingAPI.Apply(cylinder.GetPrim()).Bind(screw_material)
        screw_report = {'parent_finger':parent,'parent':str(screw_parent.GetPath()),'visual_only':True,
            'head_prim':str(screw_parent.GetPath())+'/Head','axis':cylinder.GetAxisAttr().Get(),'head_radius_m':float(cylinder.GetRadiusAttr().Get()),
            'head_height_m':float(cylinder.GetHeightAttr().Get()),'outward_protrusion_m':protrusion,'head_center_finger_m':head_center,
            'head_base_finger_y_m':base_y,'head_outer_finger_y_m':end_y,
            'head_envelope_finger_m':[[center[0]-radius,min(base_y,end_y),center[2]-radius],
                                      [center[0]+radius,max(base_y,end_y),center[2]+radius]],
            'outside_face_estimate':'Local white-visual vertex bound within head-radius height band; fallback nominal wall if empty',
            'nearby_white_vertices':len(nearby),'physical_fit_or_clearance_verified':False}
        collision_after, white_after = collision_fingerprint(parent), white_fingerprint()
        if collision_after != collision_before or white_after != white_before:
            raise RuntimeError('Visual correction changed stock collision or white-finger geometry')
        reports.append({'bounds_finger_m':bounds,'finger':name,'prim':str(tip.GetPath()),'removed_stock_pad_faces':len(pad_faces),
            'retained_white_finger_faces':624-len(pad_faces),'rotation_z_deg':angle,
            'rotation_y_deg':180.,'translation_finger_m':translation,
            'actual_matrix_CAD_mm_to_finger_m':list(map(list,xf)), 'probes_finger_m':actual_probes,
            'grip_normal_finger':grip_normal,'boss_direction_finger':boss_direction,
            'nominal_mount_plane_finger_y_m':(1 if left else -1)*spec['stock_pad_backplane_abs_finger_y_m'],
            'nominal_boss_depth_into_support_m':abs(spec['boss_front_cad_x_mm']-spec['body_mount_cad_x_mm'])*spec['assumed_stl_unit_m'],
            'outside_screw_visual':screw_report,
            'white_fingerprint_before':white_before,'white_fingerprint_after':white_after,
            'collision_fingerprint_before':collision_before,'collision_fingerprint_after':collision_after,
            'scale':spec['assumed_stl_unit_m'],'triangles':count})
    report = {'status':spec['status'],'sha256':spec['sha256'],'instances':reports,
        'collision_status':'Stock pad collision and friction unchanged; new STL contact geometry not yet validated',
        'registration':'User-confirmed proper X/Z flip and proximal/top edge aligned with stock pad; extra body length extends distally. Low CAD Z taper distal, bosses toward metal, broad CAD X0 gripping faces inward. Body plane CAD X-9.5 nominally aligns with stock pad backplane.',
        'reference_CAD_probes_mm':probes,
        'seating_status':'User-confirmed proximal alignment and boss-to-metal-hole attachment intent. Rigid visual attachment only; no form-fit or clearance certification.',
        'stock_pad_proximal_edge_finger_z_m':spec['stock_pad_proximal_finger_z_m'],
        'proximal_extension_vs_stock_m':spec['stock_pad_proximal_finger_z_m']-min(r['bounds_finger_m'][0][2] for r in reports),
        'distal_extension_vs_stock_m':max(r['bounds_finger_m'][1][2] for r in reports)-.05389988,
        'material_status':'Illustrative dark pad finish; physical material/color unknown'}
    (output/'updated_fingertips.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

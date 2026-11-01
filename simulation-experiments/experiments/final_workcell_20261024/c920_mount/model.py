"""Hand-attached C920 visual proxy. No optical, collision or rigid-body model."""
import math


def add_c920(stage, spec, hand_path):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdPhysics

    root = hand_path+'/C920ApproximateVisualMount'
    assembly = UsdGeom.Xform.Define(stage, root)
    assembly.GetPrim().CreateAttribute('calibrationStatus', Sdf.ValueTypeNames.String).Set(spec['status'])
    assembly.GetPrim().CreateAttribute('opticalTransformAvailable', Sdf.ValueTypeNames.Bool).Set(False)
    assembly.GetPrim().CreateAttribute('visualOnly', Sdf.ValueTypeNames.Bool).Set(True)
    mats = {}
    for name, color, rough in [('plastic', (.018,.020,.023), .43),
                               ('face', (.035,.039,.044), .30),
                               ('speaker', (.008,.009,.010), .75),
                               ('glass', (.009,.020,.028), .10),
                               ('tape', (.025,.025,.027), .58),
                               ('trim', (.18,.19,.20), .32)]:
        material = UsdShade.Material.Define(stage, root+'/Materials/'+name)
        shader = UsdShade.Shader.Define(stage, str(material.GetPath())+'/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(rough)
        shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(0.)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        mats[name] = material

    def bind(prim, name):
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(mats[name])

    def box(path, pos, size, material):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.)
        xf = UsdGeom.Xformable(cube)
        xf.AddTranslateOp().Set(Gf.Vec3d(*pos))
        xf.AddScaleOp().Set(Gf.Vec3d(*size))
        bind(cube.GetPrim(), material)

    # Compact folded monitor clip. Its underside lies against hand -X;
    # its rear tail is armward (hand Z=0), beneath/behind the housing.
    depth, width, length = spec['stand_size_depth_width_length_m']
    x = spec['stand_center_hand_x_m']
    box(root+'/FoldedStand/InnerLeaf', (x,0,length/2), (depth,width,length), 'plastic')
    box(root+'/FoldedStand/OuterLeaf', (x-depth*1.10,0,length*.48),
        (depth*.90,width*.94,length*.94), 'plastic')
    box(root+'/FoldedStand/RearTailContact', (x-depth*.55,0,.003),
        (depth*1.9,width*.94,.006), 'plastic')
    box(root+'/FoldedStand/FoldedFrontLip', (x-depth*.70,0,length-.003),
        (depth*1.5,width*.94,.006), 'plastic')
    for i,z in enumerate(spec['tape_centers_hand_z_m']):
        box(root+f'/Tape/Band{i}', (x-depth*1.25,0,z), (0.0018,width+.012,.009), 'tape')
        for sign in (-1,1):
            box(root+f'/Tape/Return{i}_{sign+1}', (x+.008,sign*(width/2+.005),z),
                (.019,.0018,.009), 'tape')

    hinge = spec['hinge_position_hand_m']
    cylinder = UsdGeom.Cylinder.Define(stage, root+'/Hinge')
    cylinder.CreateAxisAttr('Y'); cylinder.CreateRadiusAttr(.0045); cylinder.CreateHeightAttr(width*.85)
    UsdGeom.Xformable(cylinder).AddTranslateOp().Set(Gf.Vec3d(*hinge))
    bind(cylinder.GetPrim(), 'plastic')
    body = UsdGeom.Xform.Define(stage, root+'/TiltedBody')
    xf = UsdGeom.Xformable(body)
    xf.AddTranslateOp().Set(Gf.Vec3d(*hinge))
    xf.AddRotateYOp().Set(spec['illustrative_forward_hinge_deg'])
    center = spec['body_center_from_hinge_local_m']
    body_geometry = UsdGeom.Xform.Define(stage, str(body.GetPath())+'/Housing')
    UsdGeom.Xformable(body_geometry).AddTranslateOp().Set(Gf.Vec3d(*center))
    bpath = str(body_geometry.GetPath())
    depth,width,height = spec['body_size_depth_width_height_m']
    # In the reference the fascia faces toward the FRONT of the folded foot.
    # Map that forward direction to hand +Z (fingers), not outward hand -X.
    # Pitching the housing around +Y then tips the fascia toward hand +X.
    def rounded_extrusion(path, radial_height, lateral_width, axial_depth, mat):
        radius = min(.006, radial_height*.22)
        outline = []
        for cx,cy,start in [(radial_height/2-radius,lateral_width/2-radius,0),
                           (-radial_height/2+radius,lateral_width/2-radius,90),
                           (-radial_height/2+radius,-lateral_width/2+radius,180),
                           (radial_height/2-radius,-lateral_width/2+radius,270)]:
            for j in range(5):
                angle = math.radians(start+j*22.5)
                outline.append((cx+radius*math.cos(angle),cy+radius*math.sin(angle)))
        n = len(outline)
        points = [Gf.Vec3f(x,y,side*axial_depth/2) for side in (-1,1) for x,y in outline]
        faces = [list(reversed(range(n))),list(range(n,2*n))]
        faces += [[i,(i+1)%n,(i+1)%n+n,i+n] for i in range(n)]
        mesh = UsdGeom.Mesh.Define(stage,path)
        mesh.CreatePointsAttr(points); mesh.CreateFaceVertexCountsAttr([len(f) for f in faces])
        mesh.CreateFaceVertexIndicesAttr([v for f in faces for v in f]); mesh.CreateSubdivisionSchemeAttr('none')
        mesh.CreateDoubleSidedAttr(True); bind(mesh.GetPrim(),mat)
        return mesh
    rounded_extrusion(bpath+'/Shell',height,width,depth,'plastic')
    face = rounded_extrusion(bpath+'/GlossyCenter',height*.91,width*.52,.001,'face')
    UsdGeom.Xformable(face).AddTranslateOp().Set(Gf.Vec3d(0,0,depth/2+.0004))
    for sign in (-1,1):
        box(bpath+f'/Speaker{sign+1}',(0,sign*width*.365,depth/2+.0004),(.025,.020,.001),'trim')
        for row in range(7):
            for col in range(6):
                dot = UsdGeom.Cylinder.Define(stage,bpath+f'/Grille{sign+1}/Hole_{row}_{col}')
                dot.CreateAxisAttr('Z'); dot.CreateRadiusAttr(.00065); dot.CreateHeightAttr(.0004)
                UsdGeom.Xformable(dot).AddTranslateOp().Set(Gf.Vec3d((row-3)*.0031,
                    sign*width*.365+(col-2.5)*.0028,depth/2+.0011))
                bind(dot.GetPrim(),'speaker')
    for name,radius,front,material in [('LensRing',.011,depth/2+.0014,'trim'),
                                     ('LensGlass',.0087,depth/2+.0025,'glass')]:
        lens = UsdGeom.Cylinder.Define(stage,bpath+'/'+name)
        lens.CreateAxisAttr('Z'); lens.CreateRadiusAttr(radius); lens.CreateHeightAttr(.001)
        UsdGeom.Xformable(lens).AddTranslateOp().Set(Gf.Vec3d(0,0,front)); bind(lens.GetPrim(),material)
    descendants = list(Usd.PrimRange(assembly.GetPrim()))
    visual_only = all(not p.HasAPI(UsdPhysics.RigidBodyAPI) and not p.HasAPI(UsdPhysics.CollisionAPI)
                      and not p.HasAPI(UsdPhysics.MassAPI) and p.GetTypeName() != 'Camera'
                      for p in descendants)
    if not visual_only:
        raise RuntimeError('C920 must remain visual-only')
    pitch = math.radians(spec['illustrative_forward_hinge_deg'])
    return {'prim':root,'type':'Logitech C920 approximate visual proxy','hand_side':'-X; D435i remains +X',
        'lateral_center_hand_y_m':0.,'stand_armward_end_hand_z_m':0.,
        'wrist_face_contact':'nominal hand-origin wrist-face plane only; no measured surface contact',
        'folded_stand':True,'body_stand_angle_deg':spec['illustrative_forward_hinge_deg'],
        'decorative_fascia_normal_hand':[math.sin(pitch),0.,math.cos(pitch)],
        'reference_mapping':'holder underside toward hand +X; rear tail toward wrist -Z; fascia forward +Z tilted inward +X',
        'nominal_held_region_hand_m':[0.,0.,.1034],
        'angle_is_mechanical_limit_measurement':False,'optical_transform':None,
        'optical_camera_activated':False,'collision_or_mass_added':False,'visual_only_audit_passed':visual_only,'configuration':spec}

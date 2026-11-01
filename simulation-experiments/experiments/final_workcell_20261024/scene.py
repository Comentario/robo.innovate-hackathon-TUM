"""Small final-layout adapter around the existing FR3/BrickSim scene factory."""

import math
import hashlib
import json
import shutil
from pathlib import Path


def make_env_cfg(cfg, capture=False):
    from challenge2.env_cfg import make_env_cfg as existing_factory
    from isaaclab.sim import PreviewSurfaceCfg

    env = existing_factory(cfg, capture=capture)
    layout = cfg["final_layout"]
    table, robot = layout["table"], layout["robot"]
    env.scene.table.spawn.size = tuple(table["size_m"])
    env.scene.table.spawn.visual_material = PreviewSurfaceCfg(diffuse_color=(.86, .86, .83))
    if "_appearance" in cfg:
        env.scene.table.spawn.visual_material.roughness = cfg["_appearance"]["roughness"]["table"]
        env.scene.table.spawn.visual_material.metallic = 0.
    env.scene.table.init_state.pos = tuple(table["center_table_m"])
    env.scene.robot.init_state.pos = tuple(robot["base_table_m"])
    angle = math.radians(robot["yaw_table_deg"])
    env.scene.robot.init_state.rot = (math.cos(angle/2), 0., 0., math.sin(angle/2))
    env.scene.plate_source.spawn.color = (235, 235, 230)
    env.scene.plate_mixed.spawn.dimensions = (layout["target"]["studs"],)*2+(1,)
    env.scene.plate_mixed.spawn.color = (150, 150, 150)
    env.scene.plate_mixed.init_state.pos = tuple(layout["target"]["center_table_m"])
    # The photographed final layout uses one target plate and a round bowl.
    for name in list(vars(env.scene)):
        if name.startswith("scrap_"):
            delattr(env.scene, name)
    return env


def decorate_stage(stage, cfg, output):
    from pxr import UsdGeom, UsdShade, UsdPhysics, Sdf, Gf

    layout = cfg["final_layout"]
    appearance = cfg.get("_appearance")
    applied_materials = []
    untouched_brick_material_paths = set()
    if appearance is not None:
        # Native bindings can resolve to dimension/color-specific prototypes.
        # Prove plate materials are disjoint from all300 tower materials first.
        for prim in stage.GetPrimAtPath("/World/envs/env_0").GetChildren():
            if prim.GetName().startswith("brick_"):
                mat, _ = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(prim.GetPath().AppendChild("Body"))).ComputeBoundMaterial()
                if not mat:
                    raise RuntimeError(f"Missing tower visual material beneath {prim.GetPath()}")
                untouched_brick_material_paths.add(str(mat.GetPath()))
        for name, studs in (("plate_source", 32), ("plate_mixed", 48)):
            plate_path = Sdf.Path(f"/World/envs/env_0/{name}")
            mat, _ = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(plate_path.AppendChild("Body"))).ComputeBoundMaterial()
            prototype = mat.GetPath().GetParentPath() if mat else Sdf.Path.emptyPath
            expected_prototype = (prototype.GetParentPath() == Sdf.Path("/_Prototypes")
                and prototype.name.startswith(f"Brick_{studs}x{studs}x1_")
                and mat.GetPath().name == "LegoMaterial") if mat else False
            if (not mat or str(mat.GetPath()) in untouched_brick_material_paths
                or not (mat.GetPath().HasPrefix(plate_path) or expected_prototype)):
                raise RuntimeError(f"Plate material is shared with bricks or outside its expected prototype: {plate_path}")
            shader = UsdShade.Shader.Get(stage, mat.GetPath().AppendChild("PreviewSurface"))
            if not shader or shader.GetIdAttr().Get() != "UsdPreviewSurface":
                raise RuntimeError(f"Unexpected plate shader at {mat.GetPath()}")
            before = shader.GetInput("roughness").Get()
            shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(appearance["roughness"]["plates"])
            shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.)
            applied_materials.append({"shader": str(shader.GetPath()), "roughness_before": before,
                "roughness_after": shader.GetInput("roughness").Get(), "metallic": 0.,
                "diffuse_linear_unchanged": list(shader.GetInput("diffuseColor").Get())})
    def material(name, color):
        value = UsdShade.Material.Define(stage, f"/World/FinalMaterials/{name}")
        shader = UsdShade.Shader.Define(stage, f"{value.GetPath()}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        roughness = appearance["roughness"][name] if appearance else .65
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        if appearance:
            shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.)
            applied_materials.append({"shader": str(shader.GetPath()), "roughness_after": roughness,
                "metallic": 0., "diffuse_linear_unchanged": list(color)})
        value.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return value
    black, yellow, paper, bowl_mat = [material(name, color) for name, color in (
        ("black_tape", (.025, .025, .025)), ("yellow_tape", (.82, .96, .015)),
        ("paper_placeholder", (.96, .96, .93)), ("cream_bowl", (.87, .84, .74)))]
    def box(name, center, size, mat):
        prim = UsdGeom.Cube.Define(stage, f"/World/FinalLayout/{name}")
        prim.CreateSizeAttr(1.)
        transform = UsdGeom.Xformable(prim.GetPrim())
        transform.AddTranslateOp().Set(Gf.Vec3d(*center))
        transform.AddScaleOp().Set(Gf.Vec3d(*size))
        UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(mat)
        return prim
    for prefix, center, studs in (("source", (0., 0.), layout["source"]["studs"]),
                                  ("target", layout["target"]["center_table_m"][:2], layout["target"]["studs"])):
        width = studs*.008
        plate = layout[prefix]
        tape_width = plate["black_tape_width_m"]
        # Visual overlap uses nominal8mm-pitch units; 2026-10-25 hand measurement is14mm.
        tape_center_offset = width/2-plate["black_tape_covered_rows_each_y_edge"]*.008+tape_width/2
        for sign in (-1, 1):
            box(f"{prefix}_black_border_{sign+1}", (center[0], center[1]+sign*tape_center_offset, .0052),
                (width+.07, tape_width, .0003), black)
    target = layout["target"]
    x, y, _ = target["center_table_m"]
    studs, tape = target["studs"], target["tape_width_m"]
    cut_x, cut_y = target["zone_cut_studs"]
    local_x, local_y = (cut_x-studs/2)*.008, (cut_y-studs/2)*.008
    box("target_T_crossbar", (x, y+local_y, .0052), (studs*.008, tape, .0003), yellow)
    stem_length = cut_y*.008
    box("target_T_stem_toward_robot", (x+local_x, y-studs*.008/2+stem_length/2, .0052),
        (tape, stem_length, .0003), yellow)
    board = layout["marker_board"]
    box("marker_paper_backing", board["center_table_m"], (*board["size_m"], .0002), paper)
    asset_dir = Path(output).resolve()/"assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    board_source = Path(__file__).with_name(board["texture_file"])
    board_provenance = Path(__file__).with_name(board["provenance_file"])
    texture_path = asset_dir/board_source.name
    shutil.copy2(board_source, texture_path)
    shutil.copy2(board_provenance, asset_dir/board_provenance.name)
    pattern_metadata = json.loads(board_provenance.read_text())
    board_mat = material("charuco_pattern", (1., 1., 1.))
    board_shader = UsdShade.Shader.Get(stage, str(board_mat.GetPath())+"/PreviewSurface")
    texture = UsdShade.Shader.Define(stage, str(board_mat.GetPath())+"/Texture")
    texture.CreateIdAttr("UsdUVTexture")
    texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture_path)))
    texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    uv_reader = UsdShade.Shader.Define(stage, str(board_mat.GetPath())+"/UVReader")
    uv_reader.CreateIdAttr("UsdPrimvarReader_float2")
    uv_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(uv_reader.ConnectableAPI(), "result")
    board_shader.GetInput("diffuseColor").ConnectToSource(texture.ConnectableAPI(), "rgb")
    graphic = UsdGeom.Mesh.Define(stage, "/World/FinalLayout/CharucoPattern")
    half_x, half_y = (value/2 for value in board["pattern_size_m"])
    graphic.CreatePointsAttr([(-half_x, -half_y, 0.), (half_x, -half_y, 0.),
                              (half_x, half_y, 0.), (-half_x, half_y, 0.)])
    graphic.CreateFaceVertexCountsAttr([4])
    graphic.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    graphic.CreateSubdivisionSchemeAttr("none")
    # +u follows local+X; PNG row0 is at local+Y (v=1), without mirroring.
    UsdGeom.PrimvarsAPI(graphic).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
        UsdGeom.Tokens.vertex).Set([(0., 0.), (1., 0.), (1., 1.), (0., 1.)])
    transform = UsdGeom.Xformable(graphic)
    transform.AddTranslateOp().Set(Gf.Vec3d(*board["center_table_m"][:2], board["center_table_m"][2]+.00025))
    transform.AddRotateZOp().Set(board["pattern_rotation_table_deg"])
    UsdShade.MaterialBindingAPI.Apply(graphic.GetPrim()).Bind(board_mat)
    pattern_report = {"pattern_source": str(board_source), "texture_in_export_assets": str(texture_path),
        "texture_sha256": hashlib.sha256(texture_path.read_bytes()).hexdigest(),
        "provenance": pattern_metadata, "pattern_size_m": board["pattern_size_m"],
        "pattern_rotation_table_deg": board["pattern_rotation_table_deg"],
        "uv_convention": "+u local+X; PNG row0 local+Y before configured rotation; no mirror",
        "rotation_status": board["pattern_rotation_status"],
        "physical_print_scale": "unverified; nominal user-specified square dimensions",
        "texture_binding": "Absolute frozen output/assets path; keep this directory for USD reload"}

    # Analytic open cup: inner/outer side walls, bottom and rim; NO top disk.
    bowl = layout["reject_bowl"]
    n, wall, height = bowl["segments"], bowl["wall_m"], bowl["height_m"]
    cx, cy, cz = bowl["center_table_m"]
    rings = [(bowl["bottom_radius_m"], 0.), (bowl["outer_radius_m"], height),
             (bowl["bottom_radius_m"]-wall, wall), (bowl["outer_radius_m"]-wall, height)]
    points = [Gf.Vec3f(cx+r*math.cos(2*math.pi*i/n), cy+r*math.sin(2*math.pi*i/n), cz+z)
              for r, z in rings for i in range(n)]
    faces = []
    for i in range(n):
        j = (i+1) % n
        faces.extend(([i, j, n+j, n+i], [2*n+j, 2*n+i, 3*n+i, 3*n+j],
                      [n+i, n+j, 3*n+j, 3*n+i], [j, i, 2*n+i, 2*n+j]))
    faces.extend((list(reversed(range(n))), list(range(2*n, 3*n))))
    mesh = UsdGeom.Mesh.Define(stage, "/World/FinalLayout/RejectBowl")
    mesh.CreatePointsAttr(points)
    mesh.CreateFaceVertexCountsAttr([len(face) for face in faces])
    mesh.CreateFaceVertexIndicesAttr([index for face in faces for index in face])
    mesh.CreateSubdivisionSchemeAttr("none")
    mesh.CreateDoubleSidedAttr(True)
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(bowl_mat)
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr().Set("none")
    wrist = layout["wrist_camera"]
    placeholder = UsdGeom.Xform.Define(stage, wrist["parent_prim"]+"/WristD435iCalibrationRequired")
    placeholder.GetPrim().CreateAttribute("calibrationStatus", Sdf.ValueTypeNames.String).Set(wrist["status"])
    placeholder.GetPrim().CreateAttribute("opticalTransformAvailable", Sdf.ValueTypeNames.Bool).Set(False)
    c920_report = None
    if "additional_wrist_camera" in layout:
        from experiments.final_workcell_20261024.c920_mount.model import add_c920
        spec = layout["additional_wrist_camera"]
        c920_report = add_c920(stage, spec, spec["parent_prim"])
    from experiments.final_workcell_20261024.end_effector.fingertips import audit_native_fingers, add_updated_tip_visuals
    finger_audit = audit_native_fingers(stage, output)
    finger_report = add_updated_tip_visuals(stage, cfg, output) or finger_audit
    diagnostic = stage.GetPrimAtPath("/World/Overview")
    diagnostic.CreateAttribute("sensorPurpose", Sdf.ValueTypeNames.String).Set("Virtual diagnostic inspection only; not the physical wrist camera")
    return {"source_studs": layout["source"]["studs"], "target_studs": target["studs"],
        "target_zones": target["zones"], "routing_implemented": False, "target_empty": True,
        "reject_bowl_open_top": True, "bowl_collision_validation": "unvalidated static approximation",
        "wrist_camera_config_count": 1 + int(c920_report is not None), "additional_wrist_visual": c920_report, "fingertip_visual_update": finger_report, "wrist_optical_transform_available": False,
        "marker_board_pattern": pattern_report,
        "appearance_config": appearance, "applied_visual_materials": applied_materials,
        "native_tower_visual_material_paths_not_edited": sorted(untouched_brick_material_paths),
        "external_physical_cameras_modeled": 0, "diagnostic_cameras_are_virtual": True,
        "layout_estimates": layout}


def correct_wrist_mount_side(stage, cfg):
    """Rotate inherited camera AND bracket; author fixed joints before PhysX init."""
    from pxr import UsdGeom, UsdPhysics, Gf

    correction = cfg["final_layout"]["wrist_camera"].get("mount_side_correction")
    if correction is None:
        return None
    root = "/World/envs/env_0/Robot"
    hand = stage.GetPrimAtPath(root+"/fr3_hand")
    hand_world = UsdGeom.Xformable(hand).ComputeLocalToWorldTransform(0)
    rotation = Gf.Rotation(Gf.Vec3d(0, 0, 1), correction["rotation_about_hand_z_deg"])
    turn = Gf.Matrix4d(1).SetRotate(rotation)
    parent_world = UsdGeom.Xformable(stage.GetPrimAtPath(root)).ComputeLocalToWorldTransform(0)
    records = []
    for name, joint_name in (("D435", "fr3_hand_D435_joint"),
                             ("D435_mount", "fr3_hand_D435_mount_joint")):
        body = stage.GetPrimAtPath(root+"/"+name)
        joint = UsdPhysics.FixedJoint(stage.GetPrimAtPath(root+"/fr3_hand/"+joint_name))
        if not body or not joint or list(joint.GetBody1Rel().GetTargets()) != [body.GetPath()]:
            raise RuntimeError("Unexpected wrist mount asset/joint")
        pos = joint.GetLocalPos0Attr().Get()
        quat = joint.GetLocalRot0Attr().Get()
        new_pos = rotation.TransformDir(Gf.Vec3d(pos))
        new_quat = Gf.Quatf(rotation.GetQuat()) * quat
        joint.GetLocalPos0Attr().Set(Gf.Vec3f(new_pos))
        joint.GetLocalRot0Attr().Set(new_quat)
        # Rotate initial body poses by the same rigid hand-relative transform.
        # Gf uses row vectors: body * inv(hand) * turn * hand * inv(parent).
        world = UsdGeom.Xformable(body).ComputeLocalToWorldTransform(0)
        local = world * hand_world.GetInverse() * turn * hand_world * parent_world.GetInverse()
        xform = UsdGeom.Xformable(body)
        ops = {op.GetOpName(): op for op in xform.GetOrderedXformOps()}
        ops["xformOp:translate"].Set(local.ExtractTranslation())
        q = local.ExtractRotationQuat()
        orient = ops["xformOp:orient"]
        orient.Set(Gf.Quatd(q) if orient.GetPrecision() == UsdGeom.XformOp.PrecisionDouble else Gf.Quatf(q))
        records.append({"body": str(body.GetPath()), "joint": str(joint.GetPath()),
            "old_position_hand_m": list(pos), "new_position_hand_m": list(new_pos),
            "new_rotation_hand_wxyz": [new_quat.GetReal(), *new_quat.GetImaginary()]})
    return {"rotation_about_hand_z_deg": correction["rotation_about_hand_z_deg"],
        "status": correction["status"], "components": records}

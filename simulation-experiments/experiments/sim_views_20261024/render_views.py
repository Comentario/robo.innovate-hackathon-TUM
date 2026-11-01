"""Named camera views of one frozen, natively connected full300 FR3 workcell.

Run through the default Pueue queue. Physics advances only during the explicit
idle settling interval; every selected RGB view then shares the same state/time.
The panel is for display only. All simulator truth is separate from RGB files.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from challenge2.layout import Brick, HEIGHT, PITCH, connection_offset, overlaps


def load_geometry(path):
    spec = json.loads(Path(path).read_text())
    if spec["status"] != "confirmed_explicit_geometry":
        raise ValueError("Confirmed explicit full geometry is required; no provisional fallback")
    origins = spec["layer_origins_studs_xy"]
    if (spec["required_bricks"] != 300 or spec["layers"] != 10
            or spec["bricks_per_layer"] != 30 or spec["ridges_per_layer"] != 6
            or spec["bricks_per_ridge"] != 5
            or spec["world_axis_counts_by_yaw_quarter_turn"] != {"0": [5, 6], "1": [6, 5]}
            or spec["brick_dimensions_studs"] != [4, 2, 3]
            or spec["pitch_studs_xy"] != [4, 4]
            or len(origins) != 10 or any(not isinstance(o, list) or len(o) != 2 for o in origins)
            or any(not isinstance(v, int) for o in origins for v in o)
            or spec["layer_yaws_quarter_turn"] != [k % 2 for k in range(10)]
            or origins != [[1, 0] if k % 2 == 0 else [0, 1] for k in range(10)]):
        raise ValueError("Full300 explicit alternating rectangular lattice specification is invalid")
    rng = random.Random(26)
    palette = ["dark_red", "brown", "tan", "reject_4211201", "reject_6135191"]
    border = spec["border_studs"]
    bricks = [Brick(f"brick_{k}_{i}_{j}", border+origins[k][0]+i*4,
                    border+origins[k][1]+j*4, k, k % 2, rng.choice(palette))
              for k in range(10)
              for i in range(spec["world_axis_counts_by_yaw_quarter_turn"][str(k % 2)][0])
              for j in range(spec["world_axis_counts_by_yaw_quarter_turn"][str(k % 2)][1])]
    for layer in range(10):
        group = [b for b in bricks if b.layer == layer]
        left, bottom = min(b.x for b in group), min(b.y for b in group)
        right = max(b.x+b.footprint[0] for b in group)
        top = max(b.y+b.footprint[1] for b in group)
        if not (0 <= left < right <= spec["baseplate_studs"] and 0 <= bottom < top <= spec["baseplate_studs"]):
            raise ValueError("Full layer does not fit on the configured studded baseplate")
    for brick in bricks:
        if brick.layer and not any(a.layer == brick.layer-1 and overlaps(a, brick) for a in bricks):
            raise ValueError(f"Unsupported source brick {brick.name}")
    audit = geometry_audit(bricks)
    if (len(bricks) != spec["required_bricks"] or audit["expected_native_connection_count"] != 930
            or spec["expected_native_connections"] != audit["expected_native_connection_count"]) or any(
            interface["overlap_patch_studs_histogram"] != {1: 100} for interface in audit["adjacent_layer_interfaces"]):
        raise ValueError("Corrected rectangular photo-phase must yield100 one-stud patches per adjacent layer")
    if any(layer["footprint_center_studs_xy"] != [spec["baseplate_studs"]/2]*2 for layer in audit["layers"]):
        raise ValueError("Corrected symmetric layer centers must coincide with the baseplate center")
    return spec, bricks


def geometry_audit(bricks):
    """Contact patch area and whole-brick contact totals are distinct quantities."""
    layers, interfaces = [], []
    below = {b.name: (8 if b.layer == 0 else 0) for b in bricks}
    above = {b.name: 0 for b in bricks}
    for layer in range(1, 10):
        patches = []
        for upper in (b for b in bricks if b.layer == layer):
            uw, ud = upper.footprint
            for lower in (b for b in bricks if b.layer == layer-1):
                lw, ld = lower.footprint
                area = max(0, min(upper.x+uw, lower.x+lw)-max(upper.x, lower.x))*max(
                    0, min(upper.y+ud, lower.y+ld)-max(upper.y, lower.y))
                if area:
                    patches.append(area)
                    below[upper.name] += area
                    above[lower.name] += area
        interfaces.append({"lower_layer": layer-1, "upper_layer": layer,
            "native_connection_count": len(patches), "overlap_patch_studs_histogram": dict(Counter(patches))})
    for layer in range(10):
        group = [b for b in bricks if b.layer == layer]
        if not group:
            layers.append({"layer": layer, "bounds_studs_xyxy": None,
                "footprint_center_studs_xy": None,
                "per_brick_studs_touching_lower_histogram": {},
                "per_brick_studs_touching_upper_histogram": {}})
            continue
        bounds = [min(b.x for b in group), min(b.y for b in group),
                  max(b.x+b.footprint[0] for b in group), max(b.y+b.footprint[1] for b in group)]
        layers.append({"layer": layer, "bounds_studs_xyxy": bounds,
            "footprint_center_studs_xy": [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2],
            "per_brick_studs_touching_lower_histogram": dict(Counter(below[b.name] for b in group)),
            "per_brick_studs_touching_upper_histogram": dict(Counter(above[b.name] for b in group))})
    base_count = sum(b.layer == 0 for b in bricks)
    return {"layers": layers, "adjacent_layer_interfaces": interfaces,
        "baseplate_connection_count": base_count,
        "expected_native_connection_count": base_count+sum(i["native_connection_count"] for i in interfaces),
        "note": "One native edge per overlapping brick pair; stud counts are geometric overlap area. Full design layer centers coincide; remaining partial-layer bounds may shift."}


def normalize(vector):
    length = math.sqrt(sum(v*v for v in vector))
    if length < 1e-12:
        raise ValueError("Cannot orient camera from a zero vector")
    return tuple(v/length for v in vector)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def quaternion_error(a, b):
    # Normalize before acos: float32 quarter-turn quaternions are not unit-exact.
    a, b = normalize(tuple(float(v) for v in a)), normalize(tuple(float(v) for v in b))
    return 2*math.acos(min(1., abs(sum(x*y for x, y in zip(a, b)))))


def matrix_quaternion(matrix):
    """Proper rotation matrix to normalized WXYZ, without importing Isaac."""
    trace = sum(matrix[i][i] for i in range(3))
    if trace > 0:
        scale = math.sqrt(trace+1)*2
        q = (scale/4, (matrix[2][1]-matrix[1][2])/scale,
             (matrix[0][2]-matrix[2][0])/scale, (matrix[1][0]-matrix[0][1])/scale)
    else:
        i = max(range(3), key=lambda index: matrix[index][index])
        j, k = (i+1) % 3, (i+2) % 3
        scale = math.sqrt(1+matrix[i][i]-matrix[j][j]-matrix[k][k])*2
        values = [0., 0., 0., 0.]
        values[0] = (matrix[k][j]-matrix[j][k])/scale
        values[i+1] = scale/4
        values[j+1] = (matrix[j][i]+matrix[i][j])/scale
        values[k+1] = (matrix[k][i]+matrix[i][k])/scale
        q = tuple(values)
    return normalize(q)


def camera_pose(center, view):
    eye = tuple(c+d for c, d in zip(center, view["eye_offset_m"]))
    target = tuple(c+d for c, d in zip(center, view["target_offset_m"]))
    forward = normalize(tuple(t-e for e, t in zip(eye, target)))
    up = normalize(tuple(view["up_world"]))
    fallback = abs(sum(a*b for a, b in zip(forward, up))) > .999
    if fallback:
        up = min(((0., 1., 0.), (1., 0., 0.), (0., 0., 1.)),
                 key=lambda axis: abs(sum(a*b for a, b in zip(forward, axis))))
    right = normalize(cross(forward, up))
    actual_up = cross(right, forward)
    # OpenGL/Usd.Camera looks along -Z, with +Y image-up.
    matrix = [[right[i], actual_up[i], -forward[i]] for i in range(3)]
    return {"eye_world_m": eye, "target_world_m": target,
            "quaternion_wxyz_opengl": matrix_quaternion(matrix), "up_fallback_used": fallback,
            "rotation_camera_to_world": matrix}


def selected_views(config, selector):
    views = config["views"]
    identifiers = [view["id"] for view in views]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Camera view IDs must be unique")
    requested = identifiers if selector == "all" else selector.split(",")
    if not requested or len(requested) != len(set(requested)) or any(name not in identifiers for name in requested):
        raise ValueError("--views must be all or a comma-separated selection of configured IDs")
    return [next(view for view in views if view["id"] == name) for name in requested]


def make_panel(output, views, config):
    from PIL import Image, ImageDraw
    tile_width, tile_height = config["panel"]["thumbnail_size"]
    caption = 24
    columns = min(config["panel"]["columns"], len(views))
    rows = math.ceil(len(views)/columns)
    panel = Image.new("RGB", (columns*tile_width, rows*(tile_height+caption)+28), (245, 245, 245))
    draw = ImageDraw.Draw(panel)
    draw.text((8, 8), "Same frozen physics state; independent cameras; display panel only", fill=(0, 0, 0))
    for index, view in enumerate(views):
        x, y = index % columns*tile_width, 28+index//columns*(tile_height+caption)
        with Image.open(output/"images"/f"{view['id']}.png") as source:
            panel.paste(source.convert("RGB").resize((tile_width, tile_height)), (x, y))
        draw.text((x+8, y+tile_height+5), view["id"], fill=(0, 0, 0))
    panel.save(output/"panel.png")


def self_test():
    for eye, up in (((0, 0, .36), (0, 1, 0)), ((0, 0, .36), (0, 0, 1)),
                    ((.18, 0, .32), (0, 0, 1)), ((0, 0, -.36), (0, 1, 0))):
        pose = camera_pose((0., 0., 0.), {"eye_offset_m": eye, "target_offset_m": (0, 0, 0), "up_world": up})
        assert abs(sum(v*v for v in pose["quaternion_wxyz_opengl"])-1) < 1e-10
        rotation = pose["rotation_camera_to_world"]
        w, x, y, z = pose["quaternion_wxyz_opengl"]
        reconstructed = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
        assert max(abs(rotation[i][j]-reconstructed[i][j]) for i in range(3) for j in range(3)) < 1e-10
        toward_target = normalize(tuple(-v for v in eye))
        assert max(abs(-rotation[i][2]-toward_target[i]) for i in range(3)) < 1e-10
        for i in range(3):
            for j in range(3):
                assert abs(sum(rotation[k][i]*rotation[k][j] for k in range(3))-(1 if i == j else 0)) < 1e-10
    assert camera_pose((0, 0, 0), {"eye_offset_m": (0, 0, 1), "target_offset_m": (0, 0, 0),
                                "up_world": (0, 0, 1)})["up_fallback_used"]
    assert quaternion_error((.70710677, 0, 0, .70710677), (math.sqrt(.5), 0, 0, math.sqrt(.5))) < 1e-7
    print("camera pose tiny contracts passed")


def main(case_adapter=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--cameras", type=Path)
    parser.add_argument("--views", default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    if case_adapter is not None:
        parser.add_argument("--case", required=True)
        parser.add_argument("--benchmark", type=Path, required=True)
    if "--self-test" in sys.argv:
        parser.parse_args()
        self_test()
        return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("Render jobs must use the frozen default Pueue queue")
    from isaaclab.app import AppLauncher
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if args.geometry is None or args.cameras is None or args.output is None:
        parser.error("--geometry, --cameras and --output are required")
    if not args.enable_cameras:
        parser.error("--enable_cameras is required")
    spec, bricks = load_geometry(args.geometry)
    args.case_metadata = None
    if case_adapter is not None:
        spec, bricks, args.case_metadata = case_adapter(spec, bricks, args.benchmark, args.case)
    config = json.loads(args.cameras.read_text())
    selector = args.views
    if args.case_metadata is not None:
        permitted = args.case_metadata["views"]
        selector = ",".join(permitted) if selector == "all" else selector
        if selector.split(",") != permitted:
            parser.error("Benchmark captures require exactly the frozen ordered camera views")
    views = selected_views(config, selector)
    output = args.output
    (output/"images").mkdir(parents=True, exist_ok=True)
    (output/"evaluation_truth").mkdir(exist_ok=True)
    app = AppLauncher(args).app
    try:
        render(app, args, spec, bricks, config, views)
    except BaseException as error:
        # Kit shutdown may block after initialization failure: expose the error
        # and persist it BEFORE closing the app, rather than hiding the traceback.
        text = traceback.format_exc()
        failure = {"completed": False, "exception_type": type(error).__name__,
                   "error": str(error), "traceback": text,
                   "connection_diagnostic": "connection_failure.json" if (output/"connection_failure.json").exists() else None}
        (output/"failure.json").write_text(json.dumps(failure, indent=2))
        print("RENDER_FAILURE_BEFORE_APP_CLOSE", text, file=sys.stderr, flush=True)
        raise
    finally:
        shutdown = {"completed": False, "capture_validated": (output/"run_complete.json").exists()}
        (output/"shutdown.json").write_text(json.dumps(shutdown, indent=2))
        print("APP_CLOSE_BEGIN", json.dumps(shutdown), flush=True)
        app.close(wait_for_replicator=False)
        shutdown["completed"] = True
        (output/"shutdown.json").write_text(json.dumps(shutdown, indent=2))
        print("APP_CLOSE_RETURNED", flush=True)


def render(app, args, spec, bricks, config, views):
    import numpy as np
    import torch
    from PIL import Image
    from pxr import UsdGeom, UsdLux, Gf
    from isaaclab.scene import InteractiveScene
    from isaaclab.sim import SimulationContext, get_current_stage
    from isaaclab.utils.math import matrix_from_quat
    from bricksim.core import (create_connection, compute_connected_component, get_disassembled_connections,
        get_assembled_connections, get_assembly_thresholds, set_assembly_thresholds,
        get_breakage_thresholds, compute_connection_transform, compute_graph_transform)
    from challenge2.env_cfg import make_env_cfg
    from bricksim.mdp.brick_part import set_brick_part_xform

    output = args.output
    width, height = config["image_size"]
    cfg = json.loads((ROOT/"configs/workcell.json").read_text())
    cfg.update(source_cells=6, source_layers=10, baseplate_studs=spec["baseplate_studs"], source_xy=spec["source_xy_m"])
    env_cfg = make_env_cfg(cfg, capture=True)
    # Reuse the square scene factory, but remove the sixty unwanted source
    # configs BEFORE asset spawning; no extra disconnected bricks may render.
    desired_names = {brick.name for brick in bricks}
    pruned_source_names = []
    for name in list(vars(env_cfg.scene)):
        if name.startswith("brick_") and name not in desired_names:
            delattr(env_cfg.scene, name)
            pruned_source_names.append(name)
    if {name for name in vars(env_cfg.scene) if name.startswith("brick_")} != desired_names:
        raise RuntimeError("Scene config does not contain exactly the requested active source bricks")
    # make_env_cfg enables automatic clutch detection. For this explicit static
    # preassembly, prevent reset from authoring links that the manual loop would
    # duplicate. Keep all forces/other thresholds and breakage checks unchanged.
    assembly_thresholds = get_assembly_thresholds()
    assembly_thresholds.enabled = False
    set_assembly_thresholds(assembly_thresholds)
    if get_assembly_thresholds().enabled:
        raise RuntimeError("Automatic assembly detection remained enabled for explicit preassembly")
    configured_positions, configured_quaternions = [], []
    for brick in bricks:
        asset = getattr(env_cfg.scene, brick.name)
        asset.init_state.pos, asset.init_state.rot = brick.pose(cfg["source_xy"], spec["baseplate_studs"])
        asset.spawn.color = tuple(cfg["colors"][brick.color])
        configured_positions.append(asset.init_state.pos)
        configured_quaternions.append(asset.init_state.rot)
    camera_cfg = env_cfg.scene.overview
    camera_cfg.width, camera_cfg.height = width, height
    camera_cfg.data_types = ["rgb", "distance_to_image_plane"]
    camera_cfg.update_latest_camera_pose = True
    camera_cfg.spawn.focal_length = config["focal_length_mm"]
    camera_cfg.spawn.horizontal_aperture = config["horizontal_aperture_mm"]
    camera_cfg.spawn.clipping_range = tuple(config["clipping_range_m"])
    sim = SimulationContext(env_cfg.sim)
    sim.get_physics_context().set_physx_update_transformations_settings(update_to_usd=True)
    scene = InteractiveScene(env_cfg.scene)
    stage = get_current_stage()
    actual_source_names = {name for name in scene.rigid_objects if name.startswith("brick_")}
    spawned_source_names = {prim.GetName() for prim in stage.GetPrimAtPath("/World/envs/env_0").GetChildren()
                            if prim.GetName().startswith("brick_")}
    if actual_source_names != desired_names or spawned_source_names != desired_names:
        raise RuntimeError("Actual scene contains missing or extra source brick assets")
    sim.reset()
    scene.reset()
    # Installed omni.rtx.settings.core exposes this process-local auto-exposure
    # switch. Do not modify shared Kit files or global workstation settings.
    import carb.settings
    render_settings = carb.settings.get_settings()
    render_settings.set_bool("/rtx/post/histogram/enabled", False)
    render_setting_paths = ("/rtx/post/histogram/enabled", "/rtx/post/tonemap/op",
        "/rtx/post/tonemap/filmIso", "/rtx/post/tonemap/exposureTime",
        "/rtx/post/tonemap/fNumber", "/rtx/post/tonemap/cm2Factor")
    resolved_settings = {path: render_settings.get(path) for path in render_setting_paths}
    robot = scene["robot"]
    robot.write_joint_state_to_sim(robot.data.default_joint_pos, robot.data.default_joint_vel)
    robot.set_joint_position_target(robot.data.default_joint_pos)
    # reset() internally steps unconnected bodies. Restore authored lattice in
    # BOTH PhysX/caches and USD before native graph authoring, without a step.
    placement_checks = []
    expected_poses = {brick.name: (*position, *quaternion) for brick, position, quaternion
                      in zip(bricks, configured_positions, configured_quaternions)}
    expected_poses["plate_source"] = (*cfg["source_xy"], 0., 1., 0., 0., 0.)
    if float(scene.env_origins[0].abs().max()) > 1e-8:
        raise RuntimeError("This static single-workcell renderer expects an identity environment origin")
    for name, pose in expected_poses.items():
        asset = scene[name]
        target = torch.tensor([[*pose, 0., 0., 0., 0., 0., 0.]], dtype=torch.float32, device=asset.device)
        asset.write_root_state_to_sim(target)
        set_brick_part_xform(stage.GetPrimAtPath(f"/World/envs/env_0/{name}"), pose[:3], pose[3:])

    def verify_placement(label):
        positions, angles, usd_positions, usd_angles, speeds = [], [], [], [], []
        for name, expected in expected_poses.items():
            asset = scene[name]
            raw = asset.root_physx_view.get_transforms()[0].cpu().numpy()
            velocity = asset.root_physx_view.get_velocities()[0].cpu().numpy()
            transform = UsdGeom.Xformable(stage.GetPrimAtPath(f"/World/envs/env_0/{name}")).ComputeLocalToWorldTransform(0)
            usd_pos = np.asarray(transform.ExtractTranslation())
            usd_q = transform.ExtractRotationQuat()
            usd_quat = (usd_q.GetReal(), *usd_q.GetImaginary())
            if not np.isfinite(np.r_[raw, velocity, usd_pos, usd_quat]).all():
                raise RuntimeError(f"Nonfinite actual pose/velocity for {name} at {label}")
            positions.append(float(np.linalg.norm(raw[:3]-np.asarray(expected[:3]))))
            angles.append(quaternion_error((raw[6], *raw[3:6]), expected[3:]))
            usd_positions.append(float(np.linalg.norm(usd_pos-np.asarray(expected[:3]))))
            usd_angles.append(quaternion_error(usd_quat, expected[3:]))
            speeds.append(float(np.max(np.abs(velocity))))
        audit = {"stage": label, "max_physics_position_error_m": max(positions),
            "max_physics_orientation_error_rad": max(angles), "max_usd_position_error_m": max(usd_positions),
            "max_usd_orientation_error_rad": max(usd_angles), "max_absolute_velocity": max(speeds),
            "position_tolerance_m": 2e-6, "orientation_tolerance_rad": 1e-4}
        placement_checks.append(audit)
        (output/"placement_checks.json").write_text(json.dumps(placement_checks, indent=2))
        if max(positions+usd_positions) > 2e-6 or max(angles+usd_angles) > 1e-4 or max(speeds) > 1e-8:
            raise RuntimeError(f"Actual lattice differs from configured static geometry: {audit}")
        print("PLACEMENT_VERIFIED", json.dumps(audit), flush=True)

    verify_placement("restored_after_reset_before_native_links")
    source_path = "/World/envs/env_0/plate_source"
    pre_parts, pre_connections = compute_connected_component(source_path)
    assembled_before = get_assembled_connections(clear=False)
    preassembly = {"automatic_assembly_enabled": get_assembly_thresholds().enabled,
        "breakage_detection_enabled": get_breakage_thresholds().enabled,
        "source_component_parts_before_manual": len(pre_parts),
        "source_component_connections_before_manual": len(pre_connections),
        "assembled_events_before_manual": [repr(event) for event in assembled_before],
        "mode": "Explicit native preassembly; automatic detector disabled only in this process"}
    (output/"preassembly.json").write_text(json.dumps(preassembly, indent=2))
    print("PRE_MANUAL_GRAPH", json.dumps(preassembly), flush=True)
    if pre_connections or assembled_before:
        raise RuntimeError("Unexpected pre-existing native connections before explicit graph authoring")
    expected_connections = 0
    layer_in_progress = -1
    for brick in bricks:
        if brick.layer != layer_in_progress:
            print("NATIVE_LAYER_BEGIN", brick.layer, "completed_links", expected_connections, flush=True)
            layer_in_progress = brick.layer
        lower = [a for a in bricks if a.layer == brick.layer-1 and overlaps(a, brick)] if brick.layer else [None]
        for support in lower:
            offset, yaw = connection_offset(support, brick, spec["baseplate_studs"])
            stud_path = f"/World/envs/env_0/{support.name if support else 'plate_source'}"
            hole_path = f"/World/envs/env_0/{brick.name}"
            try:
                create_connection(stud_path, 1, hole_path, 0, offset, yaw)
            except BaseException as error:
                diagnostic = {"completed_native_links": expected_connections, "layer": brick.layer,
                    "stud_path": stud_path, "stud_interface": 1, "hole_path": hole_path,
                    "hole_interface": 0, "offset_studs": offset, "yaw_quarter_turn": yaw,
                    "error": str(error), "traceback": traceback.format_exc(), "preassembly": preassembly}
                for name, operation in (("computed_native_target_transform", lambda: compute_connection_transform(
                        stud_path, 1, hole_path, 0, offset, yaw)),
                        ("existing_graph_transform", lambda: compute_graph_transform(stud_path, hole_path))):
                    try:
                        diagnostic[name] = operation()
                    except BaseException as diagnostic_error:
                        diagnostic[name] = {"error": repr(diagnostic_error)}
                (output/"connection_failure.json").write_text(json.dumps(diagnostic, indent=2))
                print("NATIVE_CONNECTION_FAILURE", json.dumps(diagnostic), file=sys.stderr, flush=True)
                raise
            expected_connections += 1
            if expected_connections % spec["bricks_per_layer"] == 0:
                progress = {"completed_native_links": expected_connections,
                    "expected_native_links": spec["expected_native_connections"], "layer": brick.layer}
                (output/"connection_progress.json").write_text(json.dumps(progress, indent=2))
                print("NATIVE_CONNECTION_PROGRESS", json.dumps(progress), flush=True)
    print("NATIVE_GRAPH_AUTHORED", expected_connections, flush=True)
    if expected_connections != spec["expected_native_connections"]:
        raise RuntimeError("Authored native-link count differs from the explicit geometry specification")
    parts_initial, connections_initial = compute_connected_component(source_path)
    if len(parts_initial) != len(bricks)+1 or len(connections_initial) != expected_connections:
        raise RuntimeError("Active source graph is incomplete before settling")
    verify_placement("after_native_links_before_capture")
    for _ in range(config["settle_steps"]):
        scene.write_data_to_sim()
        sim.step()
        scene.update(sim.get_physics_dt())
    if get_disassembled_connections(clear=True):
        raise RuntimeError("Native connections broke during idle settling; refusing reduced benchmark")
    parts, connections = compute_connected_component(source_path)
    if set(parts) != set(parts_initial) or set(connections) != set(connections_initial):
        raise RuntimeError("Full native source graph changed during settling")

    roots = torch.stack([scene[brick.name].data.root_state_w[0] for brick in bricks]).cpu().numpy()
    position_drift = np.linalg.norm(roots[:, :3]-np.asarray(configured_positions), axis=1)
    orientation_drift = [quaternion_error(actual, expected) for actual, expected in zip(roots[:, 3:7], configured_quaternions)]
    settle_audit = {"steps": config["settle_steps"], "max_position_drift_m": float(position_drift.max()),
        "max_orientation_drift_rad": max(orientation_drift),
        "max_linear_speed_m_s": float(np.linalg.norm(roots[:, 7:10], axis=1).max()),
        "max_angular_speed_rad_s": float(np.linalg.norm(roots[:, 10:13], axis=1).max()),
        "note": "Static initialized state; no post-connection physics step, equilibrium/dynamics/clutch stability unvalidated" if config["settle_steps"] == 0 else "Idle settling audit; finite steps do not establish mechanical equilibrium or calibrated clutch forces"}
    highest_layer = max(brick.layer for brick in bricks)
    if args.case_metadata is not None:
        # Never follow removed/remaining truth with either camera or key light.
        center = np.asarray(args.case_metadata["fixed_reference_center_world_m"], np.float64)
    else:
        center = np.mean([scene[b.name].data.root_pos_w[0].cpu().numpy() for b in bricks if b.layer == 9], axis=0)
        center[2] += HEIGHT+.0017
    lighting = config["lighting"]
    dome = UsdLux.DomeLight.Get(stage, "/World/Light")
    dome.GetIntensityAttr().Set(lighting["dome_intensity"])
    key = UsdLux.SphereLight.Define(stage, "/World/ExperimentKey")
    key.CreateRadiusAttr(lighting["key_radius_m"])
    key.GetIntensityAttr().Set(lighting["key_intensity"])
    UsdGeom.Xformable(key.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(*(center+np.asarray(lighting["key_offset_m"]))))
    camera = scene["overview"]

    def physics_state():
        return torch.cat([robot.data.joint_pos.flatten(), robot.data.joint_vel.flatten(),
            robot.data.body_state_w.flatten(), scene["plate_source"].data.root_state_w.flatten(),
            *(scene[brick.name].data.root_state_w.flatten() for brick in bricks)]).clone()

    frozen = physics_state()
    frozen_time = float(sim.current_time)
    np.save(output/"evaluation_truth/frozen_physics_state.npy", frozen.cpu().numpy())
    truth_images, camera_records = [], []
    for view in views:
        verify_placement(f"before_view_{view['id']}")
        pose = camera_pose(center.tolist(), view)
        camera.set_world_poses(positions=torch.tensor([pose["eye_world_m"]], dtype=torch.float32),
            orientations=torch.tensor([pose["quaternion_wxyz_opengl"]], dtype=torch.float32), convention="opengl")
        camera.reset()
        for _ in range(config["render_warmup_frames"]):
            sim.render()
        camera.update(0., force_recompute=True)
        if float(sim.current_time) != frozen_time or not torch.equal(physics_state(), frozen):
            raise RuntimeError("Physics state/time changed during render-only camera capture")
        verify_placement(f"after_render_{view['id']}")
        rgb = camera.data.output["rgb"][0, :, :, :3].cpu().numpy()
        depth = camera.data.output["distance_to_image_plane"][0, :, :, 0].cpu().numpy()
        if rgb.shape != (height, width, 3) or rgb.dtype != np.uint8:
            raise RuntimeError("Unexpected RGB shape/type; refusing silent conversion")
        if rgb.max() == rgb.min():
            raise RuntimeError("Uniform RGB frame; refusing to call it a useful scene render")
        if any(render_settings.get(path) != value for path, value in resolved_settings.items()):
            raise RuntimeError("Resolved exposure/tone-mapping settings changed between camera views")
        actual_eye = camera.data.pos_w[0].cpu().numpy()
        actual_quaternion = camera.data.quat_w_opengl[0].cpu().numpy()
        if np.max(np.abs(actual_eye-np.asarray(pose["eye_world_m"]))) > 1e-6 or 1-abs(float(actual_quaternion@np.asarray(pose["quaternion_wxyz_opengl"]))) > 1e-5:
            raise RuntimeError("Actual camera pose does not match the named preset")
        Image.fromarray(rgb).save(output/"images"/f"{view['id']}.png")
        np.save(output/"evaluation_truth"/f"{view['id']}_depth.npy", depth)
        camera_to_world = UsdGeom.Xformable(stage.GetPrimAtPath("/World/Overview")).ComputeLocalToWorldTransform(0)
        world_to_camera = camera_to_world.GetInverse()
        intrinsics = camera.data.intrinsic_matrices[0].cpu().numpy()

        def project(points):
            values = []
            for point in points:
                q = world_to_camera.Transform(Gf.Vec3d(*[float(v) for v in point]))
                z = -float(q[2])
                values.append([float(intrinsics[0, 0]*q[0]/z+intrinsics[0, 2]),
                               float(-intrinsics[1, 1]*q[1]/z+intrinsics[1, 2]), z])
            return values

        instances = []
        for brick in bricks:
            data = scene[brick.name].data
            position = data.root_pos_w[0].cpu().numpy()
            rotation = matrix_from_quat(data.root_quat_w[0:1])[0].cpu().numpy()
            corners = np.array([[-.016, -.008, HEIGHT], [.016, -.008, HEIGHT],
                                [.016, .008, HEIGHT], [-.016, .008, HEIGHT]])
            studs = np.array([[(i-1.5)*PITCH, (j-.5)*PITCH, HEIGHT+.0017] for i in range(4) for j in range(2)])
            polygon, stud_pixels = project(corners@rotation.T+position), project(studs@rotation.T+position)
            visible = []
            for u, v, z in stud_pixels:
                ix, iy = int(round(u)), int(round(v))
                visible.append(bool(z > 0 and 0 <= ix < width and 0 <= iy < height
                    and np.isfinite(depth[iy, ix]) and abs(float(depth[iy, ix])-z) < .002))
            fraction = sum(visible)/8
            inside = all(z > 0 and 0 <= u < width and 0 <= v < height for u, v, z in polygon)
            role = "not_visible" if fraction == 0 else "exposed_top" if brick.layer == highest_layer and inside and fraction >= .75 else "visible_lower" if brick.layer < highest_layer else "ambiguous"
            instances.append({"id": brick.name, "layer": brick.layer, "color": brick.color,
                "polygon": [point[:2] for point in polygon], "role": role,
                "orientation_deg": math.degrees(math.atan2(polygon[1][1]-polygon[0][1], polygon[1][0]-polygon[0][0])) % 180,
                "visible_stud_fraction_8_samples": fraction,
                "studs": [{"x": p[0], "y": p[1], "visible": vis} for p, vis in zip(stud_pixels, visible)]})
        camera_record = {"id": view["id"], "requested": view, **pose, "intrinsics": intrinsics.tolist(),
            "actual_eye_world_m": actual_eye.tolist(), "actual_quaternion_wxyz_opengl": actual_quaternion.tolist(),
            "resolved_render_settings": resolved_settings, "rgb_standard_deviation": float(rgb.std()),
            "camera_to_world_opengl": [[float(camera_to_world[i][j]) for j in range(4)] for i in range(4)],
            "physics_time_s": frozen_time, "camera_matching": "approximate; no measured physical intrinsics/extrinsics"}
        camera_records.append(camera_record)
        truth_images.append({"file": f"{view['id']}.png", "width": width, "height": height,
            "instances": instances, "intrinsics": intrinsics.tolist(), "physics_time_s": frozen_time,
            "highest_remaining_layer": highest_layer,
            "correlation_group": args.case_metadata["case"]["id"] if args.case_metadata is not None else "one_full300_frozen_sim_scene"})
        print("RENDER_SAVED", view["id"], "physics_time", frozen_time, flush=True)

    if get_disassembled_connections(clear=True):
        raise RuntimeError("Native connections broke during camera capture")
    parts_after, connections_after = compute_connected_component(source_path)
    if set(parts_after) != set(parts) or set(connections_after) != set(connections):
        raise RuntimeError("Active source graph changed during camera capture")
    if float(sim.current_time) != frozen_time or not torch.equal(physics_state(), frozen):
        raise RuntimeError("Final physics state/time differs from the shared capture snapshot")
    verify_placement("final_capture")
    truth = output/"evaluation_truth"
    (truth/"annotations.json").write_text(json.dumps({"images": truth_images,
        "role_policy": "Uppermost remaining cohort first; visible_lower is not a physical accessibility judgment",
        "visibility_method": "Eight depth-tested stud samples, not pixel-exact instance masks or gripper accessibility"}, indent=2))
    (truth/"cameras.json").write_text(json.dumps(camera_records, indent=2))
    (truth/"native_graph.json").write_text(json.dumps({"parts": parts_after, "connections": connections_after}, indent=2))
    active_records, active_states = [], []
    for brick in bricks:
        asset = scene[brick.name]
        raw = asset.root_physx_view.get_transforms()[0].cpu().numpy()
        velocity = asset.root_physx_view.get_velocities()[0].cpu().numpy()
        state = [float(v) for v in np.r_[raw[:3], raw[6], raw[3:6], velocity]]
        active_states.append(state)
        active_records.append({"id": brick.name, "layer": brick.layer, "color": brick.color,
            "root_state_world": state, "position_world_m": state[:3], "quaternion_wxyz": state[3:7]})
    np.save(truth/"active_root_states.npy", np.asarray(active_states, np.float64))
    (truth/"active_bricks.json").write_text(json.dumps({"active_ids": [b.name for b in bricks],
        "removed_ids": args.case_metadata["removed_ids"] if args.case_metadata is not None else [],
        "highest_remaining_layer": highest_layer, "frame": "world_robot_base", "pose_origin": "body_bottom_center",
        "state_fields": ["x", "y", "z", "qw", "qx", "qy", "qz", "vx", "vy", "vz", "wx", "wy", "wz"],
        "root_states_array": "active_root_states.npy", "records": active_records}, indent=2))
    if args.case_metadata is not None:
        (truth/"case_state.json").write_text(json.dumps(args.case_metadata, indent=2))
    stage.GetRootLayer().Export(str(truth/("partial_workcell.usda" if args.case_metadata is not None else "full300_workcell.usda")))
    make_panel(output, views, config)
    manifest = {"geometry": spec, "selected_views": [v["id"] for v in views], "camera_config": config,
        "geometry_contact_audit": geometry_audit(bricks),
        "benchmark_case": args.case_metadata,
        "highest_remaining_layer": highest_layer,
        "preassembly": preassembly,
        "placement_checks": placement_checks,
        "brick_count": len(bricks), "native_connected_parts": len(parts_after), "native_connections": len(connections_after),
        "pruned_unspawned_square_factory_source_configs": sorted(pruned_source_names),
        "actual_source_asset_count": len(actual_source_names), "spawned_source_prim_count": len(spawned_source_names),
        "settling": settle_audit, "physics_time_s": frozen_time, "all_capture_states_exactly_equal": True,
        "resolved_render_settings": resolved_settings,
        "capture_semantics": "Sequential camera relocation/render-only at one physics snapshot; no detector fusion",
        "capture_mode": config.get("capture_mode", "static_initialized_not_physics_settled" if config["settle_steps"] == 0 else "idle_settled_snapshot"),
        "post_connection_physics_steps": config["settle_steps"],
        "dynamic_connection_stability_validated": False,
        "rgb_directory": "images", "truth_directory": "evaluation_truth", "panel_display_only": True,
        "frozen_state_sha256": hashlib.sha256(frozen.cpu().numpy().tobytes()).hexdigest(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "camera_matching": "Approximate nominal pinhole; not calibrated D435i equivalence"}
    (output/"manifest.json").write_text(json.dumps(manifest, indent=2))
    # This sentinel certifies validated capture, independently of Kit cleanup.
    # Explicit timeline.stop() previously blocked before a success marker.
    (output/"run_complete.json").write_text(json.dumps({"completed": True, "capture_validated": True,
        "case_id": args.case_metadata["case"]["id"] if args.case_metadata is not None else None,
        "views": len(views), "bricks": len(bricks), "shutdown_status_file": "shutdown.json"}))
    print("CAPTURE_COMPLETE_VALIDATED", flush=True)


if __name__ == "__main__":
    main()

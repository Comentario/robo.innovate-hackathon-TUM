"""Render the explicit full stack for the bounded pretrained detection comparison.

Run only through submit_render.py/Pueue. The geometry gate deliberately rejects
missing layer origins. No detector receives simulator identities, geometry or
depth: those outputs are written separately for evaluation only.
"""

import argparse
import json
import math
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from challenge2.layout import Brick, PLATE, HEIGHT, PITCH, connection_offset, overlaps


def geometry(path):
    """Load confirmed full geometry, refusing to replace unknown offsets."""
    spec = json.loads(Path(path).read_text())
    if spec["status"] != "confirmed_explicit_geometry":
        raise ValueError("Exact geometry is unresolved; supply confirmed layer origins before rendering the benchmark.")
    origins = spec["layer_origins_studs_xy"]
    assert len(origins) == 10 and all(isinstance(o, list) and len(o) == 2 for o in origins)
    assert all(isinstance(v, int) for o in origins for v in o)
    assert spec["required_bricks"] == 360 and spec["bricks_per_layer"] == [6, 6]
    assert spec["brick_dimensions_studs"] == [4, 2, 3]
    assert len(spec["layer_yaws_quarter_turn"]) == 10
    assert all(q in (0, 1) for q in spec["layer_yaws_quarter_turn"])
    palette = ["dark_red", "brown", "tan", "reject_4211201", "reject_6135191"]
    rng = random.Random(26)
    pad = 3
    bricks = [Brick(f"brick_{k}_{i}_{j}", pad + origins[k][0] + i*spec["pitch_studs_xy"][0],
                    pad + origins[k][1] + j*spec["pitch_studs_xy"][1], k,
                    spec["layer_yaws_quarter_turn"][k], rng.choice(palette))
              for k in range(10) for i in range(6) for j in range(6)]
    assert len(bricks) == 360
    for b in bricks:
        w, d = b.footprint
        assert 0 <= b.x and 0 <= b.y and b.x+w <= spec["baseplate_studs"] and b.y+d <= spec["baseplate_studs"]
        if b.layer:
            assert any(a.layer == b.layer-1 and overlaps(a,b) for a in bricks), f"Unsupported brick {b.name}"
    return spec, bricks


def main():
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise SystemExit("Submit via submit_render.py to the default Pueue queue.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", required=True)
    parser.add_argument("--output", required=True)
    from isaaclab.app import AppLauncher
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    spec, bricks = geometry(args.geometry)
    output = Path(args.output)
    (output / "images").mkdir(parents=True, exist_ok=True)
    (output / "evaluation_truth").mkdir(exist_ok=True)
    app = AppLauncher(args).app

    import numpy as np
    import torch
    from PIL import Image
    from pxr import UsdGeom, UsdLux, Gf
    from isaaclab.scene import InteractiveScene
    from isaaclab.sim import SimulationContext, get_current_stage
    from isaaclab.utils.math import matrix_from_quat
    from bricksim.core import create_connection, compute_connected_component, get_disassembled_connections
    from challenge2.env_cfg import make_env_cfg

    cfg = json.loads((ROOT / "configs/workcell.json").read_text())
    cfg.update(source_cells=6, source_layers=10, baseplate_studs=spec["baseplate_studs"],
               source_xy=spec["source_xy_m"])
    env_cfg = make_env_cfg(cfg, capture=True)
    for b in bricks:
        asset = getattr(env_cfg.scene, b.name)
        asset.init_state.pos, asset.init_state.rot = b.pose(cfg["source_xy"], spec["baseplate_studs"])
        asset.spawn.color = tuple(cfg["colors"][b.color])
    env_cfg.scene.overview.width = 1280
    env_cfg.scene.overview.height = 720
    env_cfg.scene.overview.data_types = ["rgb", "distance_to_image_plane"]
    env_cfg.scene.overview.update_latest_camera_pose = True
    # Approximate nominal focal length, explicitly not a measured calibration.
    env_cfg.scene.overview.spawn.focal_length = 24.0
    env_cfg.scene.overview.spawn.horizontal_aperture = 33.25
    sim = SimulationContext(env_cfg.sim)
    sim.get_physics_context().set_physx_update_transformations_settings(update_to_usd=True)
    scene = InteractiveScene(env_cfg.scene)
    stage = get_current_stage()
    sim.reset()
    scene.reset()
    robot = scene["robot"]
    robot.write_joint_state_to_sim(robot.data.default_joint_pos, robot.data.default_joint_vel)
    robot.set_joint_position_target(robot.data.default_joint_pos)
    for b in bricks:
        lower = [a for a in bricks if a.layer == b.layer-1 and overlaps(a,b)] if b.layer else [None]
        for a in lower:
            off, yaw = connection_offset(a, b, spec["baseplate_studs"])
            create_connection(f"/World/envs/env_0/{a.name if a else 'plate_source'}", 1,
                              f"/World/envs/env_0/{b.name}", 0, off, yaw)
    source_path = "/World/envs/env_0/plate_source"
    parts, connections = compute_connected_component(source_path)
    if len(parts) != 361:
        raise RuntimeError(f"Expected 360 bricks plus anchored plate, found {len(parts)}")
    print("FULL_STACK", len(parts)-1, "bricks", len(connections), "native connections", flush=True)
    for _ in range(24):
        scene.write_data_to_sim()
        sim.step()
        scene.update(sim.get_physics_dt())
    if get_disassembled_connections(clear=True):
        raise RuntimeError("Native connections broke during idle settling; full-stack render invalid")
    parts2, _ = compute_connected_component(source_path)
    if len(parts2) != 361:
        raise RuntimeError("Full native source graph did not survive settling")

    # The six views vary heading, slight obliquity, ambient light and a key light.
    # They do not alter brick counts or remove layers to mimic partly removed photos.
    center = np.mean([scene[b.name].data.root_pos_w[0].cpu().numpy() for b in bricks if b.layer == 9], axis=0)
    center[2] += HEIGHT
    sphere = UsdLux.SphereLight.Define(stage, "/World/ExperimentKey")
    sphere.CreateRadiusAttr(0.04)
    xf = UsdGeom.Xformable(sphere.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(*(center + np.array((0.35,0.15,0.45)))))
    dome = UsdLux.DomeLight.Get(stage, "/World/Light")
    camera = scene["overview"]
    views = [
        ("sim_01", 0, .015, .36, 160., 500.),
        ("sim_02", 10, .020, .36, 220., 400.),
        ("sim_03", 90, .025, .37, 140., 650.),
        ("sim_04", 90, .065, .38, 180., 400.),
        ("sim_05", 0, .025, .36, 100., 700.),
        ("sim_06", -10, .080, .39, 120., 850.),
    ]
    truth_images = []
    for name, heading, slant, height, ambient, key in views:
        angle = math.radians(heading)
        eye = center + np.array((slant*math.sin(angle), -slant*math.cos(angle), height))
        camera.set_world_poses_from_view(torch.tensor([eye], device="cpu", dtype=torch.float32),
                                         torch.tensor([center], device="cpu", dtype=torch.float32))
        dome.GetIntensityAttr().Set(ambient)
        sphere.GetIntensityAttr().Set(key)
        camera.reset()
        for _ in range(12):
            sim.render()
        camera.update(sim.get_physics_dt(), force_recompute=True)
        rgb = camera.data.output["rgb"][0,:,:,:3].cpu().numpy()
        depth = camera.data.output["distance_to_image_plane"][0,:,:,0].cpu().numpy()
        Image.fromarray(rgb).save(output / "images" / f"{name}.png")
        np.save(output / "evaluation_truth" / f"{name}_depth.npy", depth)
        # Read camera USD OpenGL transform; project evaluation geometry only.
        camera_to_world = UsdGeom.Xformable(stage.GetPrimAtPath("/World/Overview")).ComputeLocalToWorldTransform(0)
        world_to_camera = camera_to_world.GetInverse()
        intr = camera.data.intrinsic_matrices[0].cpu().numpy()

        def project(points):
            out = []
            for p in points:
                q = world_to_camera.Transform(Gf.Vec3d(*[float(v) for v in p]))
                z = -float(q[2])
                out.append([float(intr[0,0]*q[0]/z+intr[0,2]),
                            float(-intr[1,1]*q[1]/z+intr[1,2]), z])
            return out

        instances = []
        for b in bricks:
            asset = scene[b.name].data
            p = asset.root_pos_w[0].cpu().numpy()
            rotation = matrix_from_quat(asset.root_quat_w[0:1])[0].cpu().numpy()
            local_corners = np.array([[-.016,-.008,HEIGHT],[.016,-.008,HEIGHT],
                                      [.016,.008,HEIGHT],[-.016,.008,HEIGHT]])
            local_studs = np.array([[(i-1.5)*PITCH,(j-.5)*PITCH,HEIGHT+.0017]
                                    for i in range(4) for j in range(2)])
            polygon = project(local_corners @ rotation.T + p)
            stud_pixels = project(local_studs @ rotation.T + p)
            visible = []
            for u,v,z in stud_pixels:
                ix, iy = int(round(u)), int(round(v))
                visible.append(bool(0<=ix<1280 and 0<=iy<720 and np.isfinite(depth[iy,ix]) and abs(float(depth[iy,ix])-z)<.002))
            fraction = sum(visible)/8
            if fraction == 0:
                continue
            a,baxis = polygon[0],polygon[1]
            orientation = math.degrees(math.atan2(baxis[1]-a[1],baxis[0]-a[0])) % 180
            inside = all(0<=u<1280 and 0<=v<720 for u,v,z in polygon)
            role = "exposed_top" if b.layer == 9 and inside and fraction>=.75 else "visible_lower" if b.layer<9 else "ambiguous"
            instances.append({"id": b.name, "polygon": [q[:2] for q in polygon],
                "orientation_deg": orientation, "role": role, "layer": b.layer,
                "visible_stud_fraction_8_samples": fraction,
                "studs": [{"x":q[0],"y":q[1],"visible":vis} for q,vis in zip(stud_pixels,visible)]})
        truth_images.append({"file": f"{name}.png", "width":1280,"height":720,
                             "instances":instances,"intrinsics":intr.tolist(),
                             "camera_matching":"approximate; no physical calibration", "correlation_group":"one_full360_sim_scene"})
        print("RENDER_SAVED",name,"truth visible",len(instances),flush=True)
    (output / "evaluation_truth/annotations.json").write_text(json.dumps({"images":truth_images},indent=2))
    (output / "geometry_manifest.json").write_text(json.dumps({"geometry":spec,
        "brick_count":360,"native_connected_parts":len(parts2),"native_connection_count":len(connections),
        "views":len(views),"truth_not_perception_input":True},indent=2))
    stage.GetRootLayer().Export(str(output / "full360_workcell.usda"))
    sim.stop()
    (output / "run_complete.json").write_text('{"completed":true}')
    app.close()


if __name__ == "__main__":
    main()

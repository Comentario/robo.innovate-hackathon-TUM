"""Queued appearance-only comparison of two fixed diagnostic views."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np


VIEWS = ("diagnostic_table_top", "diagnostic_oblique")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rotation(quaternion):
    w, x, y, z = np.asarray(quaternion)/np.linalg.norm(quaternion)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def source_states(directory):
    truth = directory/"evaluation_truth"
    active = read(truth/"active_bricks.json")
    states = np.load(truth/"active_root_states.npy", allow_pickle=False)
    if len(active["active_ids"]) != 300 or len(set(active["active_ids"])) != 300 or states.shape != (300, 13):
        raise ValueError("Source inventory/state dimensions differ from required300")
    return dict(zip(active["active_ids"], states))


def diagnostics(image, mask=None):
    pixels = image.reshape(-1, 3) if mask is None else image[mask > 0]
    if not len(pixels):
        return {"pixels": 0}
    gray = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2GRAY).ravel()
    return {"pixels": len(gray), "gray_mean": float(gray.mean()), "gray_std": float(gray.std()),
            "gray_p1_p50_p99": np.percentile(gray, [1, 50, 99]).tolist(),
            "gray_le1_fraction": float((gray <= 1).mean()), "gray_ge254_fraction": float((gray >= 254).mean()),
            "any_rgb_channel_ge254_fraction": float((pixels >= 254).any(axis=1).mean())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "before-scene", "after-scene", "appearance-config", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Appearance comparison must use default Pueue")
    args.output.mkdir(parents=True, exist_ok=True)
    manifests = [read(directory/"manifest.json") for directory in (args.before, args.after)]
    robots = [read(directory/"robot_initialization.json") for directory in (args.before, args.after)]
    graphs = [read(directory/"evaluation_truth/native_graph.json") for directory in (args.before, args.after)]
    states = [source_states(directory) for directory in (args.before, args.after)]
    if set(states[0]) != set(states[1]):
        raise ValueError("Source brick identity set changed")
    a, b = [np.asarray([state[name] for name in sorted(states[0])]) for state in states]
    dots = np.abs(np.sum(a[:, 3:7]*b[:, 3:7], axis=1)/(np.linalg.norm(a[:, 3:7], axis=1)*np.linalg.norm(b[:, 3:7], axis=1)))
    position_error = float(np.linalg.norm(a[:, :3]-b[:, :3], axis=1).max())
    orientation_error = float((2*np.arccos(np.clip(dots, 0, 1))).max())
    cameras = [{camera["id"]: camera for camera in read(directory/"evaluation_truth/cameras.json")} for directory in (args.before, args.after)]
    camera_errors = {}
    for view in VIEWS:
        x, y = cameras[0][view], cameras[1][view]
        camera_errors[view] = {"intrinsics_max_abs": float(np.max(np.abs(np.asarray(x["intrinsics"])-y["intrinsics"]))),
                              "eye_max_abs_m": float(np.max(np.abs(np.asarray(x["actual_eye_world_m"])-y["actual_eye_world_m"]))),
                              "rotation_matrix_max_abs": float(np.max(np.abs(rotation(x["actual_quaternion_wxyz_opengl"])-rotation(y["actual_quaternion_wxyz_opengl"]))))}
    counts = all(all(manifest[key] == expected for key, expected in
                 (("brick_count", 300), ("actual_source_asset_count", 300), ("spawned_source_prim_count", 300),
                  ("native_connected_parts", 301), ("native_connections", 930), ("post_connection_physics_steps", 0)))
                 and manifest["all_capture_states_exactly_equal"] for manifest in manifests)
    guards = {"scene_config_equal": read(args.before_scene) == read(args.after_scene), "required_counts_and_static_capture": bool(counts),
              "exposure_and_tonemapping_unchanged": manifests[0]['resolved_render_settings'] == manifests[1]['resolved_render_settings'],
              "native_graph_counts": all(len(set(graph["parts"])) == len(graph["parts"]) == 301 and len(set(graph["connections"])) == len(graph["connections"]) == 930 for graph in graphs),
              "native_part_set_unchanged": set(graphs[0]["parts"]) == set(graphs[1]["parts"]),
              "requested_default_q_equal": robots[0]["requested_joint_positions_native_units"] == robots[1]["requested_joint_positions_native_units"],
              "actual_q_equal": bool(np.allclose(robots[0]["actual_joint_positions_native_units"], robots[1]["actual_joint_positions_native_units"], atol=1e-8, rtol=0)),
              "preassembly_steps_unchanged": robots[0]["preassembly_physics_steps"] == robots[1]["preassembly_physics_steps"],
              "source_position_within_2um": position_error <= 2e-6, "source_orientation_within_1e_minus4_rad": orientation_error <= 1e-4,
              "source_velocities_equal": bool(np.allclose(a[:, 7:], b[:, 7:], atol=1e-8, rtol=0)),
              "cameras_unchanged_1e_minus6": all(value <= 1e-6 for error in camera_errors.values() for value in error.values())}
    report = {"schema": "appearance-only-fixed-view-comparison-v1", "guards": guards,
              "source_max_position_difference_m": position_error, "source_max_orientation_difference_rad": orientation_error,
              "camera_errors": camera_errors, "appearance_parameters": read(args.appearance_config), "views": [],
              "provenance": {"source_sha256": sha(Path(__file__)), "appearance_config_sha256": sha(args.appearance_config),
                             "before_scene_sha256": sha(args.before_scene), "after_scene_sha256": sha(args.after_scene),
                             "before_output": str(args.before.resolve()), "after_output": str(args.after.resolve()),
                             "before_manifest_sha256": sha(args.before/"manifest.json"), "after_manifest_sha256": sha(args.after/"manifest.json"),
                             "opencv": cv2.__version__, "numpy": np.__version__},
              "interpretation": "Brightness/contrast/clipping diagnostics only, not a realism metric or a measured sim-to-real improvement. No histogram fitting or physical photometric/camera calibration. Source-face ROI uses baseline evaluation polygons and can include occluding robot pixels."}
    if not all(guards.values()):
        (args.output/"comparison.json").write_text(json.dumps(report, indent=2)+"\n")
        raise RuntimeError("Appearance-only invariance guard failed; see comparison.json")
    annotations = {image["file"]: image for image in read(args.before/"evaluation_truth/annotations.json")["images"]}
    for view in VIEWS:
        images = [cv2.imread(str(directory/"images"/(view+".png"))) for directory in (args.before, args.after)]
        if any(image is None for image in images) or images[0].shape != images[1].shape:
            raise ValueError("Matched diagnostic PNG missing or dimensions differ")
        instances = annotations[view+".png"]["instances"]
        highest = max(instance["layer"] for instance in instances)
        mask = np.zeros(images[0].shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.rint(instance["polygon"]).astype(np.int32) for instance in instances if instance["layer"] == highest], 1)
        panels = np.concatenate(images, axis=1)
        panel = np.zeros((panels.shape[0]+32, panels.shape[1], 3), np.uint8); panel[32:] = panels
        for label, x in (("BEFORE: frozen yaw45 baseline", 10), ("AFTER: lighting/materials only", images[0].shape[1]+10)):
            cv2.putText(panel, label, (x, 22), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1)
        panel_path = args.output/(view+"_before_after.png")
        if not cv2.imwrite(str(panel_path), panel):
            raise RuntimeError("Could not save comparison panel")
        report["views"].append({"view": view, "panel": str(panel_path), **{label: {
            "image_sha256": sha(directory/"images"/(view+".png")), "whole_frame": diagnostics(image),
            "fixed_source_face_roi": diagnostics(image, mask)} for label, directory, image in zip(("before", "after"), (args.before, args.after), images)}})
    (args.output/"comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"guards_passed": True, "views": [view["view"] for view in report["views"]]}))


if __name__ == "__main__":
    main()

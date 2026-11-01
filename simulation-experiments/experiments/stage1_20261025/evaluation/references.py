"""Evaluation-only references from active simulator inventory and sensor visibility.

Never import this module from perception. Actual depth reads belong to the
queued reference/scoring process, not lightweight development checks.
"""
import json
import math
from pathlib import Path

import numpy as np


HEIGHT, STUD_TOP, PITCH = .0096, .0113, .008


def rotation(q):
    q = np.asarray(q, float)
    if q.shape != (4,) or not np.isfinite(q).all() or np.linalg.norm(q) < .5:
        raise ValueError("Invalid actual quaternion")
    w, x, y, z = q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def design_records(geometry):
    records = {}
    for layer in range(geometry["layers"]):
        yaw = geometry["layer_yaws_quarter_turn"][layer]
        nx, ny = geometry["world_axis_counts_by_yaw_quarter_turn"][str(yaw)]
        width, depth = (4, 2) if yaw == 0 else (2, 4)
        origin = geometry["layer_origins_studs_xy"][layer]
        for i in range(nx):
            for j in range(ny):
                x = geometry["border_studs"]+origin[0]+4*i
                y = geometry["border_studs"]+origin[1]+4*j
                name = f"brick_{layer}_{i}_{j}"
                records[name] = {
                    "id": name, "layer": layer, "ridge": i if yaw else j,
                    "long_index": j if yaw else i, "yaw_rad": yaw*math.pi/2,
                    "position": np.array([geometry["source_xy_m"][0]+(x+width/2-geometry["baseplate_studs"]/2)*PITCH,
                                          geometry["source_xy_m"][1]+(y+depth/2-geometry["baseplate_studs"]/2)*PITCH,
                                          .0032+layer*HEIGHT]),
                    "quaternion": np.array([math.cos(yaw*math.pi/4), 0., 0., math.sin(yaw*math.pi/4)]),
                    "grid_bounds": [x, y, x+width, y+depth]}
    if len(records) != 300:
        raise ValueError("Expected corrected300-brick design")
    return records


def expected_active_ids(design, case):
    top = {name for name, b in design.items() if b["layer"] == 9}
    keep = case["keep_only_top_ridge_brick"]
    if keep is not None:
        keep = {tuple(x) for x in keep}
        removed = {name for name in top if (design[name]["ridge"], design[name]["long_index"]) not in keep}
    else:
        remove = {tuple(x) for x in case["remove_top_ridge_brick"]}
        removed = {name for name in top if (design[name]["ridge"], design[name]["long_index"]) in remove}
    return set(design)-removed, removed


def camera_model(record):
    # OpenGL +X right,+Y up,-Z forward -> optical +X right,+Y down,+Z forward.
    r = np.diag([1., -1., -1.])@rotation(record["actual_quaternion_wxyz_opengl"]).T
    return {"K": np.asarray(record["intrinsics"], float), "R": r,
            "eye": np.asarray(record["actual_eye_world_m"], float)}


def project(world, camera):
    optical = (np.asarray(world)-camera["eye"])@camera["R"].T
    pixel = optical@camera["K"].T
    return pixel[:, :2]/pixel[:, 2:3], optical[:, 2]


def geometry_for(record, camera):
    r = rotation(record["quaternion"])
    corners = np.array([[-.016,-.008,HEIGHT], [.016,-.008,HEIGHT],
                        [.016,.008,HEIGHT], [-.016,.008,HEIGHT]])
    studs = np.array([[(i-1.5)*PITCH, (j-.5)*PITCH, STUD_TOP] for i in range(4) for j in range(2)])
    polygon, z = project(corners@r.T+record["position"], camera)
    pixels, stud_z = project(studs@r.T+record["position"], camera)
    return polygon, z, pixels, stud_z


def sample_returns(pixels, expected_z, depth, camera, body_height):
    height, width = depth.shape
    visible, lower, valid = [], [], []
    for (u, v), z in zip(pixels, expected_z):
        in_frame = np.isfinite([u, v, z]).all() and z > 0 and 0 <= round(float(u)) < width and 0 <= round(float(v)) < height
        if not in_frame:
            visible.append(False); lower.append(False); valid.append(False)
            continue
        x, y = int(round(float(u))), int(round(float(v)))
        d = float(depth[y, x])
        good = np.isfinite(d) and d > 0
        valid.append(bool(good))
        visible.append(bool(good and abs(d-z) < .002))
        if good:
            optical = d*np.array([(x-camera["K"][0,2])/camera["K"][0,0],
                                   (y-camera["K"][1,2])/camera["K"][1,1], 1.])
            world = optical@camera["R"]+camera["eye"]
            lower.append(bool(world[2] <= body_height-.003))
        else:
            lower.append(False)
    return {"visible_stud_samples": sum(visible), "valid_samples": sum(valid),
            "lower_return_samples": sum(lower), "visible_flags": visible, "lower_flags": lower}


def intersects(a, b):
    a, b = a["grid_bounds"], b["grid_bounds"]
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def build_reference(capture, view, geometry, case, sensor_depth=None):
    capture = Path(capture)
    directory = capture/"evaluation_truth"
    manifest = json.loads((capture/"manifest.json").read_text())
    inventory = json.loads((directory/"active_bricks.json").read_text())
    design = design_records(geometry)
    expected, removed = expected_active_ids(design, case)
    active_ids = inventory["active_ids"]
    if len(active_ids) != len(set(active_ids)) or set(active_ids) != expected or set(inventory["removed_ids"]) != removed:
        raise ValueError(f"Actual active/removed inventory mismatch: {case['id']}")
    if len(active_ids) != case["expected"]["active_bricks"] or manifest["actual_source_asset_count"] != len(active_ids) or manifest["spawned_source_prim_count"] != len(active_ids):
        raise ValueError("Rendered asset count differs from frozen inventory")
    graph = json.loads((directory/"native_graph.json").read_text())
    if len(set(graph["parts"])) != case["expected"]["connected_parts"] or len(set(graph["connections"])) != case["expected"]["native_connections"]:
        raise ValueError("Native graph differs from frozen case")
    if {x.rsplit("/",1)[-1] for x in graph["parts"]} != expected|{"plate_source"}:
        raise ValueError("Native graph contains ghost/missing bodies")
    states = np.load(directory/inventory["root_states_array"], allow_pickle=False)
    if states.shape != (len(active_ids), 13):
        raise ValueError("Actual source roots have unexpected shape")
    metadata = {r["id"]: r for r in inventory["records"]}
    active = []
    for name, state in zip(active_ids, states):
        if not np.isfinite(state).all() or not np.allclose(state, metadata[name]["root_state_world"], rtol=0, atol=1e-9):
            raise ValueError("Explicit root ordering differs from exported metadata")
        nominal = design[name]
        if np.linalg.norm(state[:3]-nominal["position"]) > 2e-6:
            raise ValueError("Actual body drift violates geometry gate")
        dot = min(1., abs(float(np.dot(np.asarray(state[3:7],float)/np.linalg.norm(state[3:7]), nominal["quaternion"]))))
        if 2*math.acos(dot) > .0001:
            raise ValueError("Actual orientation drift violates geometry gate")
        active.append({**nominal, "position": np.asarray(state[:3],float), "quaternion": np.asarray(state[3:7],float)})
    max_z = max(float(b["position"][2]) for b in active)
    highest = [b for b in active if float(b["position"][2]) >= max_z-2e-6]
    layers = {b["layer"] for b in highest}
    if len(layers) != 1 or inventory["highest_remaining_layer"] != next(iter(layers)):
        raise ValueError("Highest physical roots disagree with inventory layer")
    current_layer = next(iter(layers))
    body_height = float(np.median([b["position"][2]+HEIGHT*rotation(b["quaternion"])[2,2] for b in highest]))
    stud_height = float(np.median([b["position"][2]+STUD_TOP*rotation(b["quaternion"])[2,2] for b in highest]))
    layer_heights = {str(layer): {
        "body_top_world_m": float(np.median([b["position"][2]+HEIGHT*rotation(b["quaternion"])[2,2] for b in active if b["layer"] == layer])),
        "stud_top_world_m": float(np.median([b["position"][2]+STUD_TOP*rotation(b["quaternion"])[2,2] for b in active if b["layer"] == layer]))}
        for layer in sorted({b["layer"] for b in active})}
    top_yaws = [math.atan2(rotation(b["quaternion"])[1,0],rotation(b["quaternion"])[0,0]) for b in highest]
    current_yaw = math.atan2(float(np.sin(2*np.asarray(top_yaws)).mean()),float(np.cos(2*np.asarray(top_yaws)).mean()))/2
    camera_record = next(c for c in json.loads((directory/"cameras.json").read_text()) if c["id"] == view)
    camera = camera_model(camera_record)
    original_depth = np.load(directory/f"{view}_depth.npy", allow_pickle=False)
    if original_depth.ndim != 2:
        raise ValueError("Expected axial image-plane depth")
    sensor_depth = original_depth if sensor_depth is None else sensor_depth
    if sensor_depth.shape != original_depth.shape:
        raise ValueError("Sensor control changed image dimensions")
    height, width = original_depth.shape
    instances = []
    for b in active:
        polygon, z, pixels, stud_z = geometry_for(b, camera)
        samples = sample_returns(pixels, stud_z, original_depth, camera, body_height)
        full = bool(np.isfinite(polygon).all() and (z > 0).all() and (polygon[:,0] >= 0).all() and (polygon[:,0] < width).all() and (polygon[:,1] >= 0).all() and (polygon[:,1] < height).all())
        n = samples["visible_stud_samples"]
        role = "exposed_top" if b["layer"] == current_layer and full and n >= 6 else "ambiguous" if b["layer"] == current_layer and n else "visible_lower" if b["layer"] < current_layer and n else "not_visible"
        r = rotation(b["quaternion"])
        above = [a["id"] for a in active if a["layer"] > b["layer"] and intersects(a,b)]
        instances.append({"id": b["id"], "layer": b["layer"], "role": role,
                          "polygon": polygon.tolist(), "center_world_xy_m": b["position"][:2].tolist(),
                          "yaw_world_rad": math.atan2(r[1,0],r[0,0]), "ridge_key": f"L{b['layer']}_R{b['ridge']}",
                          "long_index": b["long_index"], "full_face_in_frame": full, **samples,
                          "higher_projection_overlap_ids": above, "vertical_projection_uncovered": not above})
    current_design = [b for b in design.values() if b["layer"] == current_layer]
    current_active = [b for b in active if b["layer"] == current_layer]
    missing, unknown_removed = [], []
    for b in current_design:
        if b["id"] in expected:
            continue
        anchors = sorted((a for a in current_active if a["ridge"] == b["ridge"]), key=lambda x:x["long_index"])
        left = [a for a in anchors if a["long_index"] < b["long_index"]]
        right = [a for a in anchors if a["long_index"] > b["long_index"]]
        bounded = bool(left and right)
        polygon, z, pixels, stud_z = geometry_for(b, camera)
        samples = sample_returns(pixels, stud_z, sensor_depth, camera, body_height)
        full = bool((z > 0).all() and (polygon[:,0] >= 0).all() and (polygon[:,0] < width).all() and (polygon[:,1] >= 0).all() and (polygon[:,1] < height).all())
        reason = "extent_unknown" if not bounded else "visibility_unknown" if not full or samples["lower_return_samples"] < 6 else "observable_internal_absence"
        entry = {"id": b["id"], "reference_id": b["id"], "layer": current_layer, "polygon": polygon.tolist(),
                 "center_world_xy_m": b["position"][:2].tolist(), "yaw_world_rad": b["yaw_rad"],
                 "ridge_key": f"L{current_layer}_R{b['ridge']}", "long_index": b["long_index"],
                 "classification": reason, "left_anchor": left[-1]["id"] if left else None,
                 "right_anchor": right[0]["id"] if right else None, **samples}
        (missing if reason == "observable_internal_absence" else unknown_removed).append(entry)
    all_polygon_points = [p for b in design.values() for p in geometry_for(b,camera)[0]]
    points = np.asarray(all_polygon_points)
    x0,y0 = points.min(axis=0);x1,y1 = points.max(axis=0)
    return {"case_id": case["id"], "view": view, "width": width, "height": height,
            "current_layer": current_layer, "physical_highest_bricks": len(highest),
            "body_top_world_m": body_height, "stud_top_world_m": stud_height,
            "layer_heights": layer_heights, "current_yaw_world_rad": current_yaw,
            "instances": instances, "missing_references": missing, "unknown_removed": unknown_removed,
            "removed_noncurrent_layer_ids": sorted(name for name in removed if design[name]["layer"] != current_layer),
            "stack_roi_polygon": [[float(x0),float(y0)],[float(x1),float(y0)],[float(x1),float(y1)],[float(x0),float(y1)]],
            "visibility_counts": {role:sum(b["role"]==role for b in instances) for role in ("exposed_top","ambiguous","visible_lower","not_visible")},
            "actual_camera_eye_world_m": camera["eye"].tolist(),
            "actual_camera_rotation_world_to_optical": camera["R"].tolist(),
            "actual_camera_intrinsics": camera["K"].tolist(),
            "note": "References are scoring-only; lower footprint visibility and vertical projection do not establish physical gripper accessibility."}

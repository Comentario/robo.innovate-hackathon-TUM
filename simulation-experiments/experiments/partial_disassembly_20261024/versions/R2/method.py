"""Depth-assisted individual 2x4 hypotheses from observed ridge windows.

Only sensor depth/RGB, nominal calibration, the existing depth-direction method
and physical brick dimensions are supplied. No scene layout/count/poses or
designed top height is available. All sensor batches run through Pueue.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time

import cv2
import numpy as np


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project(points, calibration):
    camera = np.asarray(points)@calibration["R"].T+calibration["t"]
    pixels = camera@calibration["K"].T
    return pixels[:, :2]/pixels[:, 2:3]


def unproject_observed(depth, calibration, depth_config):
    stride = depth_config["pixel_stride"]
    v, u = np.mgrid[0:depth.shape[0]:stride, 0:depth.shape[1]:stride]
    observed = depth[::stride, ::stride]
    K = calibration["K"]
    rays = np.stack(((u-K[0, 2])/K[0, 0], (v-K[1, 2])/K[1, 1], np.ones_like(u)), axis=-1)
    world = (observed[:, :, None]*rays-calibration["t"])@calibration["R"]
    valid = np.isfinite(observed) & (observed > 0)
    roi = depth_config["source_roi_world_xy_m"]
    valid &= ((world[:, :, 0] >= roi["x"][0]) & (world[:, :, 0] < roi["x"][1])
              & (world[:, :, 1] >= roi["y"][0]) & (world[:, :, 1] < roi["y"][1]))
    return world[valid]


def grid_samples(array, world_xy, depth_config):
    roi, resolution = depth_config["source_roi_world_xy_m"], depth_config["raster_resolution_m"]
    x = np.floor((world_xy[:, 0]-roi["x"][0])/resolution).astype(int)
    y = np.floor((world_xy[:, 1]-roi["y"][0])/resolution).astype(int)
    valid = (x >= 0) & (x < array.shape[1]) & (y >= 0) & (y < array.shape[0])
    values = np.full(len(x), np.nan, np.float64)
    values[valid] = array[y[valid], x[valid]]
    return values


def group_fragments(mask, angle, depth_config, config):
    resolution, roi = depth_config["raster_resolution_m"], depth_config["source_roi_world_xy_m"]
    axis = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-axis[1], axis[0]])
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    fragments, rejected = [], []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])*resolution**2
        if area < config["minimum_fragment_area_m2"]:
            continue
        rows, columns = np.nonzero(labels == label)
        points = np.column_stack((roi["x"][0]+(columns+.5)*resolution,
                                  roi["y"][0]+(rows+.5)*resolution))
        u, v = points@axis, points@normal
        width = float(np.ptp(v)+resolution)
        record = {"label": label, "area_m2": area, "u_min": float(u.min()-resolution/2),
            "u_max": float(u.max()+resolution/2), "v_center": float((v.min()+v.max())/2), "width_m": width}
        if abs(width-config["brick_width_m"]) > config["ridge_width_tolerance_m"]:
            rejected.append({**record, "reason": "fragment_width_incompatible_with_2stud_ridge"})
        else:
            fragments.append(record)
    groups = []
    for fragment in sorted(fragments, key=lambda f: (f["v_center"], f["u_min"])):
        matching = [g for g in groups if abs(g["v_center"]-fragment["v_center"]) <= config["ridge_transverse_join_tolerance_m"]]
        if matching:
            group = min(matching, key=lambda g: abs(g["v_center"]-fragment["v_center"]))
            group["fragments"].append(fragment)
            total = sum(f["area_m2"] for f in group["fragments"])
            group["v_center"] = sum(f["v_center"]*f["area_m2"] for f in group["fragments"])/total
            group["u_min"], group["u_max"] = min(group["u_min"], fragment["u_min"]), max(group["u_max"], fragment["u_max"])
        else:
            groups.append({"v_center": fragment["v_center"], "u_min": fragment["u_min"],
                           "u_max": fragment["u_max"], "fragments": [fragment]})
    return groups, rejected, axis, normal


def end_evidence(group, sign, mask, observed_heights, axis, normal, depth_config, config, surface_z):
    end = group["u_min"] if sign < 0 else group["u_max"]
    v = group["v_center"]+np.linspace(-.5, .5, 32)*config["brick_width_m"]*config["end_sample_width_fraction"]
    inside_u = end-sign*config["end_sample_offset_m"]
    outside_u = end+sign*config["end_sample_offset_m"]
    inside = inside_u*axis+v[:, None]*normal
    outside = outside_u*axis+v[:, None]*normal
    inside_values = grid_samples(mask, inside, depth_config)
    outside_values = grid_samples(mask, outside, depth_config)
    actual_outside_z = grid_samples(observed_heights, outside, depth_config)
    inside_support = float(np.mean(np.isfinite(inside_values) & (inside_values > 0)))
    outside_support = float(np.mean(np.isfinite(outside_values) & (outside_values > 0)))
    observed_lower = np.isfinite(actual_outside_z) & (actual_outside_z <= surface_z-config["minimum_outside_height_drop_m"])
    lower_fraction = float(observed_lower.mean())
    supported = (inside_support >= config["minimum_inside_end_coverage"]
        and outside_support <= config["maximum_outside_end_coverage"]
        and lower_fraction >= config["minimum_observed_lower_end_fraction"])
    return {"status": "observed" if supported else "unknown", "coordinate_u_m": end,
        "inside_top_coverage": inside_support, "outside_top_coverage": outside_support,
        "actual_observed_lower_fraction": lower_fraction,
        "outside_depth_valid_fraction": float(np.isfinite(actual_outside_z).mean()),
        "note": "No projected return is not evidence of lower surface; only finite actual depth can support the end"}


def count_phase(group, ends, config):
    length = config["brick_length_m"]
    span = group["u_max"]-group["u_min"]
    nearest = round(span/length)
    alternatives = [{"count": n, "span_residual_m": abs(span-n*length),
        "origin_u_m": (group["u_min"]+group["u_max"]-n*length)/2,
        "length_supported": abs(span-n*length) <= config["maximum_integer_span_residual_m"]}
        for n in (nearest-1, nearest, nearest+1) if n >= 1]
    alternatives.sort(key=lambda a: (a["span_residual_m"], a["count"]))
    eligible = [a for a in alternatives if a["length_supported"]]
    selected = len(eligible) == 1 and all(end["status"] == "observed" for end in ends)
    return {"status": "selected" if selected else "uncertain", "selected": eligible[0] if selected else None,
        "best_window_hypothesis": alternatives[0] if alternatives else None, "alternatives": alternatives,
        "original_chain_extent": "unknown", "count_semantics": "Current observed window only; no missing-end inference"}


def plane_evidence(rgb, surface_z, calibration, depth_config, config, Evidence):
    gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
    roi = depth_config["source_roi_world_xy_m"]
    pps = config["evidence"]["pixels_per_stud"]
    scale = pps/config["stud_pitch_m"]
    G = np.array([[scale, 0, pps-roi["x"][0]*scale], [0, scale, pps-roi["y"][0]*scale], [0, 0, 1]], np.float64)
    R, t = calibration["R"], calibration["t"]
    H = calibration["K"]@np.column_stack((R[:, 0], R[:, 1], R[:, 2]*(surface_z+config["stud_height_m"])+t))
    image_to_chart = G@np.linalg.inv(H)
    size = (math.ceil((roi["x"][1]-roi["x"][0])*scale)+2*pps,
            math.ceil((roi["y"][1]-roi["y"][0])*scale)+2*pps)
    rectified = cv2.warpPerspective(gray, image_to_chart, size)
    return Evidence(rectified, config["evidence"]), G, image_to_chart


def chart_xy(world_xy, G):
    return (np.column_stack((world_xy, np.ones(len(world_xy))))@G.T)[:, :2]


def seam_evidence(coordinate, transverse, axis, normal, surface_z, evidence, G, calibration, config):
    width = config["brick_width_m"]*config["end_sample_width_fraction"]
    v = transverse+np.linspace(-width/2, width/2, 32)
    scale = config["evidence"]["pixels_per_stud"]/config["stud_pitch_m"]
    half = config["seam_search_half_window_m"]
    candidates = []
    for shift in np.linspace(-half, half, 2*math.ceil(half*scale)+1):
        xy = (coordinate+shift)*axis+v[:, None]*normal
        chart = chart_xy(xy, G).astype(np.float32)
        gx = cv2.remap(evidence.gx, chart[:, 0:1], chart[:, 1:2], cv2.INTER_LINEAR).ravel()
        gy = cv2.remap(evidence.gy, chart[:, 0:1], chart[:, 1:2], cv2.INTER_LINEAR).ravel()
        strength = np.abs(gx*axis[0]+gy*axis[1])
        candidates.append({"shift": float(shift), "strength": strength})
    noise_values = np.concatenate([c["strength"] for c in candidates])
    median = float(np.median(noise_values))
    mad = float(np.median(np.abs(noise_values-median)))
    threshold = max(config["seam_gradient_floor"], median+config["seam_noise_mad_multiplier"]*mad)
    best = min(candidates, key=lambda c: (-float((c["strength"] >= threshold).mean()), -float(np.median(c["strength"])), abs(c["shift"])))
    support = float((best["strength"] >= threshold).mean())
    measured_u = coordinate+best["shift"]
    line = np.array([measured_u*axis+(transverse-width/2)*normal, measured_u*axis+(transverse+width/2)*normal])
    pixels = project(np.column_stack((line, np.full(2, surface_z))), calibration)
    return {"supported": support >= config["seam_minimum_common_width_support"], "support": support,
        "observed_offset_u_m": best["shift"], "gradient_threshold": threshold, "line_xy": pixels.tolist(),
        "note": "Observed common cross-edge support, not independently labeled physical seam truth"}


def analyze(depth, rgb, calibration, depth_module, depth_config, config, Evidence, view, condition):
    direction, mask, ridge_mask, _ = depth_module.analyze(depth, calibration, depth_config, view, condition)
    result = {"view": view, "condition": condition, "direction_status": direction["status"],
        "depth_direction": direction, "ridges": [], "candidates": [], "rejected_fragments": [],
        "limitations": ["Known2x4 footprint/type and nominal camera calibration assist hypotheses.",
            "Measured dominant horizontal band is treated as body-top plane; not a calibrated per-brick root pose.",
            "Equal metric divisions are inferred, not automatically observed brick seams.",
            "Current full-stack views do not validate missing runs, removed ends or physical gripper accessibility."]}
    if direction["status"] != "supported":
        return result, mask, ridge_mask
    surface_z = direction["estimated_surface_height_world_m"]
    groups, rejected, axis, normal = group_fragments(mask, math.radians(direction["direction_world_deg_mod180"]), depth_config, config)
    result["rejected_fragments"] = rejected
    observed = unproject_observed(depth, calibration, depth_config)
    observed_heights = np.full(mask.shape, -np.inf, np.float64)
    rows, columns = depth_module.raster_indices(observed, depth_config)
    np.maximum.at(observed_heights, (rows, columns), observed[:, 2])
    observed_heights[~np.isfinite(observed_heights)] = np.nan
    evidence, G, image_to_chart = plane_evidence(rgb, surface_z, calibration, depth_config, config, Evidence)
    for group_index, group in enumerate(groups):
        identity = f"ridge_{group_index:02d}"
        ends = [end_evidence(group, sign, mask, observed_heights, axis, normal, depth_config, config, surface_z) for sign in (-1, 1)]
        phase = count_phase(group, ends, config)
        ridge = {"id": identity, "fragments": group["fragments"], "transverse_center_m": group["v_center"],
            "observed_extent_u_m": [group["u_min"], group["u_max"]], "original_extent": "unknown",
            "end_evidence": ends, "count_phase": phase, "boundaries": []}
        result["ridges"].append(ridge)
        best = phase["selected"] or phase["best_window_hypothesis"]
        if best is None:
            continue
        boundaries = []
        for index in range(best["count"]+1):
            u = best["origin_u_m"]+index*config["brick_length_m"]
            v = group["v_center"]
            line = np.array([u*axis+(v-config["brick_width_m"]/2)*normal,
                             u*axis+(v+config["brick_width_m"]/2)*normal])
            model_pixels = project(np.column_stack((line, np.full(2, surface_z))), calibration)
            seam = seam_evidence(u, v, axis, normal, surface_z, evidence, G, calibration, config)
            is_end = index in (0, best["count"])
            depth_end_observed = is_end and ends[0 if index == 0 else 1]["status"] == "observed"
            observed_u = (group["u_min"] if index == 0 else group["u_max"]) if depth_end_observed else u+seam["observed_offset_u_m"]
            if depth_end_observed:
                observed_line = line+(observed_u-u)*axis
                displayed_line = project(np.column_stack((observed_line, np.full(2, surface_z))), calibration).tolist()
            else:
                displayed_line = seam["line_xy"] if seam["supported"] else model_pixels.tolist()
            boundary = {"id": f"{identity}_b{index:02d}", "index": index, "coordinate_u_m": u,
                "provenance": "observed" if depth_end_observed or seam["supported"] else "inferred",
                "source": "depth_current_end" if depth_end_observed else "rgb_common_cross_edge" if seam["supported"] else "metric_2x4_phase",
                "observed_coordinate_u_m": observed_u if depth_end_observed or seam["supported"] else None,
                "model_line_xy": model_pixels.tolist(), "line_xy": displayed_line,
                "rgb_verification": seam}
            boundaries.append(boundary)
        ridge["boundaries"] = boundaries
        for index in range(best["count"]):
            start = best["origin_u_m"]+index*config["brick_length_m"]
            end = start+config["brick_length_m"]
            transverse = group["v_center"]
            corners_xy = np.array([start*axis+(transverse-config["brick_width_m"]/2)*normal,
                end*axis+(transverse-config["brick_width_m"]/2)*normal,
                end*axis+(transverse+config["brick_width_m"]/2)*normal,
                start*axis+(transverse+config["brick_width_m"]/2)*normal])
            polygon = project(np.column_stack((corners_xy, np.full(4, surface_z))), calibration)
            resolution = depth_config["raster_resolution_m"]
            us = np.arange(start+resolution/2, end, resolution)
            vs = np.arange(transverse-config["brick_width_m"]/2+resolution/2,
                           transverse+config["brick_width_m"]/2, resolution)
            uu, vv = np.meshgrid(us, vs)
            footprint = uu.ravel()[:, None]*axis+vv.ravel()[:, None]*normal
            coverage_values = grid_samples(mask, footprint, depth_config)
            coverage = float(np.mean(np.isfinite(coverage_values) & (coverage_values > 0)))
            stud_xy = np.array([(start+(i+.5)*config["stud_pitch_m"])*axis
                +(transverse+(j-.5)*config["stud_pitch_m"])*normal for i in range(4) for j in range(2)])
            observations = [evidence.stud(point) for point in chart_xy(stud_xy, G)]
            confirmed = [i for i, observation in enumerate(observations) if observation["score"] >= config["stud_confirm_score"]]
            edge_polygon = cv2.perspectiveTransform(polygon.astype(np.float32)[None], image_to_chart)[0]
            _, edges = evidence.edges(edge_polygon)
            edge_score = float(.4*edges[0]+.1*edges[1]+.4*edges[2]+.1*edges[3])
            reasons = []
            if phase["status"] != "selected":
                reasons.append("current_window_count_or_phase_uncertain")
            if coverage < config["minimum_slot_top_coverage"]:
                reasons.append("insufficient_top_band_material_coverage")
            if len(confirmed) < config["minimum_confirmed_studs"]:
                reasons.append("insufficient_rgb_stud_support")
            if not (set(confirmed)&{0, 1} and set(confirmed)&{6, 7} and any(i % 2 == 0 for i in confirmed) and any(i % 2 == 1 for i in confirmed)):
                reasons.append("stud_support_not_distributed_across_both_ends_and_rows")
            if edge_score < config["minimum_edge_score"]:
                reasons.append("weak_rgb_long_side_edge_support")
            result["candidates"].append({"id": f"{identity}_s{index:02d}", "parent_ridge_id": identity, "index": index,
                "coordinate_u_m": [start, end], "polygon": polygon.tolist(),
                "box_xyxy": [*polygon.min(axis=0).tolist(), *polygon.max(axis=0).tolist()],
                "decision": "uncertain" if reasons else "present", "reason_flags": reasons,
                "center_world_xy_m": (((start+end)/2)*axis+transverse*normal).tolist(),
                "yaw_world_rad": math.atan2(axis[1], axis[0]), "surface_height_world_m": surface_z,
                "boundary_ids": [boundaries[index]["id"], boundaries[index+1]["id"]],
                "support": {"top_band_coverage": coverage, "confirmed_studs": len(confirmed),
                    "stud_scores": [float(o["score"]) for o in observations], "edge_score": edge_score, "edge_scores": edges},
                "physical_exposure": "highest_measured_surface_hypothesis", "gripper_accessibility": "unverified"})
    return result, mask, ridge_mask


def overlay(rgb, result):
    canvas = rgb.copy()
    for ridge in result["ridges"]:
        for boundary in ridge["boundaries"]:
            a, b = np.rint(boundary["line_xy"]).astype(int)
            color = (230, 180, 0) if boundary["provenance"] == "observed" else (220, 0, 220)
            cv2.line(canvas, tuple(a), tuple(b), color, 1)
    for candidate in result["candidates"]:
        polygon = np.rint(candidate["polygon"]).astype(np.int32)
        color = (0, 220, 0) if candidate["decision"] == "present" else (0, 210, 240)
        cv2.polylines(canvas, [polygon], True, color, 1)
        cv2.putText(canvas, f"{candidate['index']}:{candidate['decision'][0]}", tuple(np.rint(polygon.mean(axis=0)).astype(int)),
                    cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
    return canvas


def self_test(config):
    # Measured spans, not a hardcoded brick count; both ends are necessary.
    for count in (3, 7):
        group = {"u_min": .01, "u_max": .01+count*config["brick_length_m"]-.001}
        phase = count_phase(group, [{"status": "observed"}]*2, config)
        assert phase["status"] == "selected" and phase["selected"]["count"] == count
        assert count_phase(group, [{"status": "unknown"}, {"status": "observed"}], config)["status"] == "uncertain"
    # Two separated material fragments share one phase; gaps cannot reindex them.
    depth_config = {"raster_resolution_m": .001, "source_roi_world_xy_m": {"x": [0., .2], "y": [0., .08]}}
    mask = np.zeros((80, 200), bool)
    mask[20:36, 10:42] = True; mask[20:36, 106:170] = True
    groups, _, _, _ = group_fragments(mask, 0., depth_config, config)
    assert len(groups) == 1 and len(groups[0]["fragments"]) == 2
    phase = count_phase(groups[0], [{"status": "observed"}]*2, config)
    assert phase["status"] == "selected" and phase["selected"]["count"] == 5
    missing_depth = np.full(mask.shape, np.nan)
    end = end_evidence(groups[0], -1, mask, missing_depth, np.array([1., 0.]), np.array([0., 1.]), depth_config, config, .1)
    assert end["status"] == "unknown" and end["actual_observed_lower_fraction"] == 0
    print("metric count, shared gap phase and unknown-end tiny contracts passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    cv2.setNumThreads(2); cv2.setRNGSeed(26)
    if args.self_test:
        self_test(config); return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("All sensor batches require the frozen default Pueue queue")
    if args.inputs is None or args.output is None:
        parser.error("--inputs and --output required")
    depth_module = load_module("frozen_depth_ridges", args.inputs/"upstream/depth_ridges.py")
    Evidence = load_module("frozen_evidence", args.inputs/"upstream/evidence.py").Evidence
    depth_config = json.loads((args.inputs/"upstream/depth_config.json").read_text())
    package = json.loads((args.inputs/"calibration.json").read_text())
    started, cases = time.monotonic(), []
    for condition in config["conditions"]:
        for view, nominal in package["views"].items():
            calibration = {"K": np.asarray(package["K"], np.float64),
                "R": np.asarray(nominal["R_world_to_camera"], np.float64), "t": np.asarray(nominal["t_world_to_camera_m"], np.float64)}
            depth = np.load(args.inputs/"depth"/f"{view}.npy", allow_pickle=False)
            rgb = cv2.imread(str(args.inputs/"images"/f"{view}.png"))
            if rgb is None or rgb.shape[:2] != depth.shape:
                raise ValueError("Original RGB/depth dimensions differ")
            if condition == "invalid":
                depth = np.full_like(depth, np.nan)
            elif condition == "flat_plane":
                depth = depth_module.flat_plane_depth(depth.shape, calibration, depth_config["flat_control_world_height_m"])
            result, mask, ridges = analyze(depth, rgb, calibration, depth_module, depth_config, config, Evidence, view, condition)
            folder = args.output/condition/view; folder.mkdir(parents=True, exist_ok=True)
            write_json(folder/"detections.json", result)
            cv2.imwrite(str(folder/"overlay.png"), overlay(rgb, result))
            cv2.imwrite(str(folder/"top_band_world_xy.png"), mask.astype(np.uint8)*255)
            cv2.imwrite(str(folder/"ridge_mask_world_xy.png"), ridges.astype(np.uint8)*255)
            present = sum(c["decision"] == "present" for c in result["candidates"])
            if condition != "real" and present:
                raise RuntimeError("Negative control unexpectedly declares present bricks")
            cases.append({"condition": condition, "view": view, "ridges": len(result["ridges"]),
                "raw_candidates": len(result["candidates"]), "present": present})
            print("DEPTH_BRICK_CASE", json.dumps(cases[-1]), flush=True)
    write_json(args.output/"runtime.json", {"seconds": time.monotonic()-started, "cases": cases,
        "versions": {"numpy": np.__version__, "opencv": cv2.__version__},
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest()})
    write_json(args.output/"run_complete.json", {"completed": True, "cases": len(cases)})


if __name__ == "__main__":
    main()

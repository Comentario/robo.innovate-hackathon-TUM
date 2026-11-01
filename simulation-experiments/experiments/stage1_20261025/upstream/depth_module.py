"""Depth-only highest supported surface-band ridge direction.

No brick poses, layer count, designed height, yaw or RGB features are used.
RGB is opened only after analysis for the display arrow. Full sensor batches
must run through the frozen default Pueue queue job.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

import cv2
import numpy as np


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def axial_distance(a, b):
    return abs((a-b+90) % 180-90)


def axial_consensus(angles, weights):
    if not angles:
        return {"angle_deg_mod180": None, "concentration": 0., "count": 0}
    theta = np.radians(np.asarray(angles)*2)
    weights = np.asarray(weights, np.float64)
    vector = np.array([np.sum(weights*np.cos(theta)), np.sum(weights*np.sin(theta))])/weights.sum()
    return {"angle_deg_mod180": float(math.degrees(math.atan2(vector[1], vector[0]))/2 % 180),
            "concentration": float(np.linalg.norm(vector)), "count": len(angles)}


def horizontal_points(depth, calibration, config):
    """Unproject distance_to_image_plane as optical Z, never ray length."""
    stride = config["pixel_stride"]
    v, u = np.mgrid[0:depth.shape[0]:stride, 0:depth.shape[1]:stride]
    sampled = depth[::stride, ::stride].astype(np.float64)
    K, R, t = calibration["K"], calibration["R"], calibration["t"]
    rays = np.stack(((u-K[0, 2])/K[0, 0], (v-K[1, 2])/K[1, 1], np.ones_like(u)), axis=-1)
    points = (sampled[:, :, None]*rays-t)@R
    valid = np.isfinite(sampled) & (sampled > 0)
    center = points[1:-1, 1:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = points[1:-1, 2:]-points[1:-1, :-2]
        dy = points[2:, 1:-1]-points[:-2, 1:-1]
        normal = np.cross(dx, dy)
        cosine = np.abs(normal[:, :, 2])/np.linalg.norm(normal, axis=-1)
        height_jumps = np.maximum.reduce([np.abs(points[1:-1, 2:, 2]-center[:, :, 2]),
            np.abs(points[1:-1, :-2, 2]-center[:, :, 2]),
            np.abs(points[2:, 1:-1, 2]-center[:, :, 2]),
            np.abs(points[:-2, 1:-1, 2]-center[:, :, 2])])
    mask = (valid[1:-1, 1:-1] & valid[1:-1, 2:] & valid[1:-1, :-2]
            & valid[2:, 1:-1] & valid[:-2, 1:-1]
            & np.isfinite(cosine) & (cosine >= math.cos(math.radians(config["maximum_normal_tilt_deg"]))))
    mask &= height_jumps <= config["maximum_neighbor_height_jump_m"]
    roi = config["source_roi_world_xy_m"]
    mask &= ((center[:, :, 0] >= roi["x"][0]) & (center[:, :, 0] < roi["x"][1])
             & (center[:, :, 1] >= roi["y"][0]) & (center[:, :, 1] < roi["y"][1]))
    return center[mask], {"sampled_depth_pixels": int(sampled.size),
        "valid_sampled_depth_pixels": int(valid.sum()), "horizontal_roi_points": int(mask.sum())}


def raster_shape(config):
    roi, resolution = config["source_roi_world_xy_m"], config["raster_resolution_m"]
    return (int(round((roi["y"][1]-roi["y"][0])/resolution)),
            int(round((roi["x"][1]-roi["x"][0])/resolution)))


def raster_indices(points, config):
    roi, resolution = config["source_roi_world_xy_m"], config["raster_resolution_m"]
    columns = np.floor((points[:, 0]-roi["x"][0])/resolution).astype(int)
    rows = np.floor((points[:, 1]-roi["y"][0])/resolution).astype(int)
    height, width = raster_shape(config)
    return np.clip(rows, 0, height-1), np.clip(columns, 0, width-1)


def highest_band(points, config):
    if not len(points):
        return None, np.zeros(0, bool), []
    roi = config["source_roi_world_xy_m"]
    roi_area = (roi["x"][1]-roi["x"][0])*(roi["y"][1]-roi["y"][0])
    minimum_area = config["minimum_band_roi_area_fraction"]*roi_area
    bin_size = config["height_bin_m"]
    bins = np.floor(points[:, 2]/bin_size).astype(int)
    rows, columns = raster_indices(points, config)
    width = raster_shape(config)[1]
    cells = rows*width+columns
    attempts = []
    for upper_bin in sorted(set((bins+1).tolist()), reverse=True):
        high = upper_bin*bin_size
        low = high-config["top_band_thickness_m"]
        selected = (points[:, 2] >= low) & (points[:, 2] < high)
        occupied = len(np.unique(cells[selected]))
        area = occupied*config["raster_resolution_m"]**2
        attempts.append({"band_world_m": [low, high], "unique_xy_cells": occupied, "support_area_m2": area})
        if area >= minimum_area:
            return [low, high], selected, attempts
    return None, np.zeros(len(points), bool), attempts


def ridge_orientation(mask, config):
    resolution = config["raster_resolution_m"]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    components, accepted_mask = [], np.zeros_like(mask)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])*resolution**2
        if area < config["minimum_component_area_m2"]:
            continue
        rows, columns = np.nonzero(labels == label)
        points = np.column_stack((columns, rows)).astype(np.float64)*resolution
        center = points.mean(axis=0)
        values, vectors = np.linalg.eigh(np.cov((points-center).T))
        axis = vectors[:, -1]
        ratio = float(math.sqrt(max(0., values[-1])/max(values[0], 1e-15)))
        coordinates = (points-center)@axis
        length = float(np.ptp(coordinates)+resolution)
        accepted = length >= config["minimum_component_length_m"] and ratio >= config["minimum_component_axis_ratio"]
        components.append({"label": label, "area_m2": area, "length_m": length,
            "axis_ratio": ratio, "angle_deg_mod180": float(math.degrees(math.atan2(axis[1], axis[0])) % 180),
            "center_roi_xy_m": center.tolist(), "accepted": accepted})
        if accepted:
            accepted_mask[labels == label] = True
    # A single component cannot pass the standard multi-ridge count gate.
    # Permit only a known-2x4 metric footprint exception; Hough gates below
    # remain mandatory and unchanged. No layer/layout/count prior is supplied.
    singleton_mode = False
    fallback = config.get("compact_singleton_fallback", {})
    if (fallback.get("enabled", False) and len(components) == 1
            and sum(c["accepted"] for c in components) < config["minimum_elongated_components"]):
        component = components[0]
        rows, columns = np.nonzero(labels == component["label"])
        points = np.column_stack((columns, rows)).astype(np.float32)*resolution
        rectangle = cv2.minAreaRect(points)
        box = cv2.boxPoints(rectangle)
        edges = [box[1]-box[0], box[2]-box[1]]
        longest = int(np.argmax([np.linalg.norm(edge) for edge in edges]))
        axis = edges[longest]
        rectangle_angle = float(math.degrees(math.atan2(axis[1], axis[0])) % 180)
        length, width = sorted((float(side)+resolution for side in rectangle[1]), reverse=True)
        disagreement = axial_distance(component["angle_deg_mod180"], rectangle_angle)
        failures = []
        if not fallback["length_bounds_m"][0] <= length <= fallback["length_bounds_m"][1]:
            failures.append("compact_length_outside_2x4_bounds")
        if not fallback["width_bounds_m"][0] <= width <= fallback["width_bounds_m"][1]:
            failures.append("compact_width_outside_2x4_bounds")
        if component["area_m2"] < fallback["minimum_area_m2"]:
            failures.append("compact_surface_area_insufficient")
        if component["axis_ratio"] < fallback["minimum_axis_ratio"]:
            failures.append("compact_pca_axis_ambiguous")
        if disagreement > fallback["maximum_pca_rectangle_disagreement_deg"]:
            failures.append("compact_rectangle_axis_disagrees")
        component["compact_singleton_eligibility"] = {
            "eligible": not failures, "reasons": failures,
            "rectangle_length_m": length, "rectangle_width_m": width,
            "rectangle_angle_deg_mod180": rectangle_angle,
            "pca_rectangle_disagreement_deg": disagreement,
            "hough_still_required": True}
        if not failures:
            singleton_mode = True
            component["accepted"] = True
            component["acceptance_mode"] = "compact_singleton"
            accepted_mask[labels == component["label"]] = True
    elongated = [c for c in components if c["accepted"]]
    pca = axial_consensus([c["angle_deg_mod180"] for c in elongated], [c["area_m2"] for c in elongated])
    pca["mode"] = "compact_singleton" if singleton_mode else "standard_multi_ridge"
    edges = cv2.Canny(accepted_mask.astype(np.uint8)*255, *config["hough_canny_thresholds"])
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, config["hough_vote_threshold"],
        minLineLength=round(config["hough_minimum_length_m"]/resolution),
        maxLineGap=round(config["hough_maximum_gap_m"]/resolution))
    line_records = []
    for line in lines if lines is not None else []:
        x1, y1, x2, y2 = [int(v) for v in line[0]]
        line_records.append({"roi_pixel_endpoints": [[x1, y1], [x2, y2]],
            "angle_deg_mod180": float(math.degrees(math.atan2(y2-y1, x2-x1)) % 180),
            "length_m": math.hypot(x2-x1, y2-y1)*resolution})
    hough = axial_consensus([line["angle_deg_mod180"] for line in line_records], [line["length_m"] for line in line_records])
    reasons = []
    if len(elongated) < (1 if singleton_mode else config["minimum_elongated_components"]):
        reasons.append("insufficient_elongated_surface_components")
    if pca["concentration"] < config["minimum_axial_concentration"]:
        reasons.append("component_directions_ambiguous")
    if len(line_records) < config["minimum_hough_lines"]:
        reasons.append("insufficient_long_mask_edges")
    if hough["concentration"] < config["minimum_axial_concentration"]:
        reasons.append("line_directions_ambiguous")
    disagreement = None
    if pca["angle_deg_mod180"] is not None and hough["angle_deg_mod180"] is not None:
        disagreement = axial_distance(pca["angle_deg_mod180"], hough["angle_deg_mod180"])
        if disagreement > config["maximum_pca_hough_disagreement_deg"]:
            reasons.append("component_and_edge_directions_disagree")
    angle = axial_consensus([pca["angle_deg_mod180"], hough["angle_deg_mod180"]], [1., 1.])["angle_deg_mod180"] if not reasons else None
    return angle, reasons, components, pca, hough, line_records, accepted_mask, disagreement


def analyze(depth, calibration, config, view, condition):
    points, support = horizontal_points(depth, calibration, config)
    band, selected, attempts = highest_band(points, config)
    shape = raster_shape(config)
    mask = np.zeros(shape, bool)
    height_map = np.full(shape, np.nan, np.float32)
    result = {"view": view, "condition": condition, "status": "uncertain", "frame": "world_xy",
        "direction_world_deg_mod180": None, "height_band_world_m": band,
        "estimated_surface_height_world_m": None, "reasons": [], "support": support,
        "band_search": attempts, "components": [], "pca_consensus": None, "hough_consensus": None,
        "raster": {"resolution_m": config["raster_resolution_m"], "roi_world_xy_m": config["source_roi_world_xy_m"],
            "columns_axis": "+worldX", "rows_axis": "+worldY"},
        "depth_semantics": "axial optical Z in meters, not Euclidean range",
        "limitations": ["Highest supported horizontal surface is an image/depth hypothesis, not a semantic brick-layer proof.",
            "Nominal camera calibration; no physical D435i calibration or dynamics claim.",
            "Component PCA and Hough are complementary checks sharing one sensor-derived mask."]}
    if band is None:
        result["reasons"] = ["no_sufficiently_supported_horizontal_height_band"]
        return result, mask, mask.copy(), height_map
    band_points = points[selected]
    rows, columns = raster_indices(band_points, config)
    mask[rows, columns] = True
    finite_heights = np.full(shape, -np.inf, np.float64)
    np.maximum.at(finite_heights, (rows, columns), band_points[:, 2])
    height_map[mask] = finite_heights[mask]
    kernel = np.ones((config["closing_kernel_pixels"],)*2, np.uint8)
    closed = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)
    angle, reasons, components, pca, hough, lines, ridge_mask, disagreement = ridge_orientation(closed, config)
    result.update(status="supported" if not reasons else "uncertain", direction_world_deg_mod180=angle,
        estimated_surface_height_world_m=float(np.median(band_points[:, 2])), reasons=reasons,
        components=components, pca_consensus=pca, hough_consensus=hough, hough_lines=lines,
        pca_hough_disagreement_deg=disagreement,
        arrow_center_world_m=[float(v) for v in np.median(band_points, axis=0)])
    result["support"].update(top_band_points=len(band_points), raw_band_xy_cells=int(mask.sum()),
        closed_band_xy_cells=int(closed.sum()), elongated_ridge_xy_cells=int(ridge_mask.sum()))
    return result, closed, ridge_mask, height_map


def project_world(points, calibration):
    camera = np.asarray(points)@calibration["R"].T+calibration["t"]
    homogeneous = camera@calibration["K"].T
    return homogeneous[:, :2]/homogeneous[:, 2:3]


def display_overlay(rgb, result, calibration, config):
    canvas = rgb.copy()
    if result["status"] == "supported":
        angle = math.radians(result["direction_world_deg_mod180"])
        center = np.asarray(result["arrow_center_world_m"])
        offset = config["overlay_half_arrow_length_m"]*np.array([math.cos(angle), math.sin(angle), 0.])
        pixels = np.rint(project_world([center-offset, center+offset], calibration)).astype(int)
        a, b = tuple(pixels[0]), tuple(pixels[1])
        cv2.arrowedLine(canvas, a, b, (0, 220, 0), 3, tipLength=.12)
        cv2.arrowedLine(canvas, b, a, (0, 220, 0), 3, tipLength=.12)
    text = f"{result['condition']} / {result['status']}"
    if result["direction_world_deg_mod180"] is not None:
        text += f" / world {result['direction_world_deg_mod180']:.2f} deg mod180"
    cv2.putText(canvas, text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 3)
    cv2.putText(canvas, text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 230, 230), 1)
    return canvas


def flat_plane_depth(shape, calibration, height):
    v, u = np.mgrid[:shape[0], :shape[1]]
    K, R, t = calibration["K"], calibration["R"], calibration["t"]
    rays = np.stack(((u-K[0, 2])/K[0, 0], (v-K[1, 2])/K[1, 1], np.ones_like(u)), axis=-1)@R
    origin = -t@R
    with np.errstate(divide="ignore", invalid="ignore"):
        depth = (height-origin[2])/rays[:, :, 2]
    depth[~np.isfinite(depth) | (depth <= 0)] = np.nan
    return depth.astype(np.float32)


def self_test(config):
    consensus = axial_consensus([179., 1.], [1., 1.])
    assert axial_distance(consensus["angle_deg_mod180"], 0) < 1e-8
    assert axial_consensus([0., 90.], [1., 1.])["concentration"] < 1e-8
    mask = np.zeros((64, 64), bool)
    for column in (3, 29, 55):
        mask[8:56, column:column+4] = True
    angle, reasons, *_ = ridge_orientation(mask, config)
    assert not reasons and axial_distance(angle, 90) < 1
    assert ridge_orientation(np.ones((64, 64), bool), config)[1]
    # An isolated highest outlier cannot outrank a supported three-mm band.
    roi = config["source_roi_world_xy_m"]
    x, y = np.meshgrid(np.arange(35), np.arange(20))
    points = np.column_stack((roi["x"][0]+.002+x.ravel()*.001,
        roi["y"][0]+.002+y.ravel()*.001, np.where(x.ravel() % 2, .1009, .0992)))
    points = np.vstack((points, [roi["x"][0]+.1, roi["y"][0]+.1, .4]))
    band, selected, _ = highest_band(points, config)
    assert band is not None and selected.sum() == 700 and band[0] < .0992 < .1009 < band[1]
    calibration = {"K": np.array([[100., 0, 16], [0, 100., 16], [0, 0, 1]]),
                   "R": np.eye(3), "t": np.zeros(3)}
    result, *_ = analyze(np.full((32, 32), np.nan), calibration, config, "tiny", "invalid")
    assert result["status"] == "uncertain" and result["direction_world_deg_mod180"] is None
    print("depth band, per-ridge axis, ambiguity and invalid-data tiny contracts passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    cv2.setNumThreads(2)
    cv2.setRNGSeed(26)
    if args.self_test:
        self_test(config); return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("Sensor image processing must run through the frozen default Pueue queue")
    if args.inputs is None or args.output is None:
        parser.error("--inputs and --output required")
    started = time.monotonic()
    package = json.loads((args.inputs/"calibration.json").read_text())
    cases = []
    for condition in config["conditions"]:
        for view, nominal in package["views"].items():
            case_started = time.monotonic()
            calibration = {"K": np.asarray(package["K"], np.float64),
                "R": np.asarray(nominal["R_world_to_camera"], np.float64),
                "t": np.asarray(nominal["t_world_to_camera_m"], np.float64)}
            depth_path = args.inputs/"depth"/f"{view}.npy"
            depth = np.load(depth_path, allow_pickle=False)
            if depth.ndim != 2:
                raise ValueError("Expected axial depth as one two-dimensional sensor array")
            if condition == "invalid":
                depth = np.full_like(depth, np.nan)
            elif condition == "flat_plane":
                depth = flat_plane_depth(depth.shape, calibration, config["flat_control_world_height_m"])
            result, mask, ridges, height_map = analyze(depth, calibration, config, view, condition)
            # RGB has no path into analyze(); it is display-only input.
            rgb = cv2.imread(str(args.inputs/"images"/f"{view}.png"))
            if rgb is None or rgb.shape[:2] != depth.shape:
                raise ValueError("RGB overlay and depth dimensions do not match")
            folder = args.output/condition/view
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder/"direction.json", result)
            cv2.imwrite(str(folder/"top_band_world_xy.png"), mask.astype(np.uint8)*255)
            cv2.imwrite(str(folder/"elongated_ridges_world_xy.png"), ridges.astype(np.uint8)*255)
            np.save(folder/"top_height_world_m.npy", height_map)
            normalized = np.zeros_like(height_map, np.uint8)
            if result["height_band_world_m"] is not None:
                low, high = result["height_band_world_m"]
                valid = np.isfinite(height_map)
                normalized[valid] = np.clip((height_map[valid]-low)/(high-low)*255, 0, 255).astype(np.uint8)
            visualization = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
            visualization[~np.isfinite(height_map)] = 0
            cv2.imwrite(str(folder/"top_height_visualization.png"), visualization)
            cv2.imwrite(str(folder/"overlay.png"), display_overlay(rgb, result, calibration, config))
            if condition != "real" and result["status"] == "supported":
                raise RuntimeError(f"Negative control unexpectedly supported a direction: {condition}/{view}")
            cases.append({"condition": condition, "view": view, "status": result["status"],
                "direction_world_deg_mod180": result["direction_world_deg_mod180"],
                "seconds": time.monotonic()-case_started})
            print("DEPTH_RIDGE_CASE", json.dumps(cases[-1]), flush=True)
    write_json(args.output/"runtime.json", {"seconds": time.monotonic()-started, "cases": cases,
        "versions": {"opencv": cv2.__version__, "numpy": np.__version__},
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "calibration_sha256": hashlib.sha256((args.inputs/"calibration.json").read_bytes()).hexdigest()})
    write_json(args.output/"run_complete.json", {"completed": True, "cases": len(cases)})


if __name__ == "__main__":
    main()

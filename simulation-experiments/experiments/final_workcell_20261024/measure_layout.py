"""Queued, approximate planar photo measurement; no robot/camera calibration."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapped(points, homography):
    return cv2.perspectiveTransform(np.asarray(points, np.float64)[None], homography)[0]


def measure(anchors, homography):
    gray = mapped(anchors["gray_uncovered_corners_xy"], homography)
    inset = anchors["assumptions"]["tape_covered_stud_rows_each_opposite_y_edge"]*anchors["assumptions"]["stud_pitch_m"]
    outer = gray.copy()
    for top, bottom in ((0, 3), (1, 2)):
        direction = (gray[bottom]-gray[top])/np.linalg.norm(gray[bottom]-gray[top])
        outer[top] -= inset*direction
        outer[bottom] += inset*direction
    ruler = mapped(list(anchors["ruler_tick_centers_xy"].values()), homography)
    names = list(anchors["points_xy"])
    points = dict(zip(names, mapped(list(anchors["points_xy"].values()), homography).tolist()))
    points["gray_plate_center"] = outer.mean(axis=0).tolist()
    source = np.asarray(points["source_footprint_center_approx"])
    return {"points_table_xy_m": points, "gray_uncovered_quad_table_xy_m": gray.tolist(),
            "gray_inferred_outer_quad_table_xy_m": outer.tolist(),
            "gray_uncovered_edge_spans_m_top_right_bottom_left": np.linalg.norm(np.roll(gray, -1, axis=0)-gray, axis=1).tolist(),
            "gray_inferred_outer_edge_spans_m_top_right_bottom_left": np.linalg.norm(np.roll(outer, -1, axis=0)-outer, axis=1).tolist(),
            "ruler_measured_tick_distance_m": float(np.linalg.norm(ruler[1]-ruler[0])),
            "source_distances_m": {name: float(np.linalg.norm(np.asarray(points[name])-source)) for name in
                                   ("gray_plate_center", "robot_base_foot_center_approx", "bowl_rim_center_projected_approx")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--image", type=Path, help="Explicit frozen image, overriding JSON relative path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Photo image processing must use default Pueue")
    anchors = json.loads(args.measurements.read_text())
    image_path = args.image or Path(anchors["image"])
    image = cv2.imread(str(image_path))
    if image is None or list(image.shape[1::-1]) != anchors["image_size_wh"]:
        raise ValueError("Frozen photo missing or dimensions differ")
    quad = np.asarray(anchors["white_uncovered_corners_xy"], np.float32)
    assumptions = anchors["assumptions"]
    side = assumptions["measured_outer_side_m"]["white"]
    inset = assumptions["tape_covered_stud_rows_each_opposite_y_edge"]*assumptions["stud_pitch_m"]
    visible_y = side-2*inset
    if visible_y <= 0:
        raise ValueError("Tape inset exceeds physical plate side")
    target = np.array([[side/2, -visible_y/2], [-side/2, -visible_y/2], [-side/2, visible_y/2], [side/2, visible_y/2]], np.float32)
    white_outer = np.array([[side/2, -side/2], [-side/2, -side/2], [-side/2, side/2], [side/2, side/2]], np.float32)
    delta = np.sign(quad-quad.mean(axis=0))*anchors["pixel_pick_uncertainty"]["plate_corners_and_ruler_ticks_px"]
    homography = cv2.getPerspectiveTransform(quad, target)
    variants = {name: measure(anchors, cv2.getPerspectiveTransform(q.astype(np.float32), target)) for name, q in
                (("nominal", quad), ("expanded_white_quad_3px", quad+delta), ("contracted_white_quad_3px", quad-delta))}
    result = {"schema": "approximate-planar-photo-layout-v2", "frame": anchors["frame"],
              "assumptions": anchors["assumptions"], "limitations": anchors["limitations"],
              "pixel_pick_uncertainty": anchors["pixel_pick_uncertainty"], "variants": variants,
              "nominal_image_to_table_homography": homography.tolist(),
              "white_uncovered_quad_table_xy_m": target.tolist(),
              "white_inferred_outer_quad_table_xy_m": white_outer.tolist(),
              "white_inferred_outer_corners_image_xy": mapped(white_outer, np.linalg.inv(homography)).tolist(),
              "provenance": {"image": str(image_path.resolve()), "image_sha256": digest(image_path),
                             "measurements_sha256": digest(args.measurements), "source_sha256": digest(Path(__file__)),
                             "opencv": cv2.__version__, "numpy": np.__version__}}
    names = variants["nominal"]["points_table_xy_m"]
    result["point_scenario_ranges_m"] = {name: {"min_xy": np.min([v["points_table_xy_m"][name] for v in variants.values()], axis=0).tolist(),
        "max_xy": np.max([v["points_table_xy_m"][name] for v in variants.values()], axis=0).tolist()} for name in names}
    gray_reported = assumptions["measured_outer_side_m"]["gray"]
    result["independent_checks"] = {"gray_user_reported_outer_span_m": gray_reported,
        "gray_reported_span_difference_percent_each_inferred_outer_edge": [(v/gray_reported-1)*100 for v in variants["nominal"]["gray_inferred_outer_edge_spans_m_top_right_bottom_left"]],
        "native_nominal_outer_span_m": {"white": assumptions["white_studs_per_side"]*assumptions["stud_pitch_m"], "gray": assumptions["gray_nominal_studs_per_side_for_comparison_only"]*assumptions["stud_pitch_m"]},
        "native_minus_user_reported_outer_span_m": {"white": assumptions["white_studs_per_side"]*assumptions["stud_pitch_m"]-side, "gray": assumptions["gray_nominal_studs_per_side_for_comparison_only"]*assumptions["stud_pitch_m"]-gray_reported},
        "ruler_expected_tick_distance_m": anchors["assumptions"]["ruler_tick_distance_m"],
        "ruler_difference_percent": (variants["nominal"]["ruler_measured_tick_distance_m"]/anchors["assumptions"]["ruler_tick_distance_m"]-1)*100,
        "interpretation": "Gray full Y spans include inferred 16mm per edge; X edges unmasked. Disagreement retained, not corrected by fitting ruler/gray dimensions. Native pitch/assets unchanged."}
    annotated = image.copy()
    for label, points in (("white_UNCOVERED_250x218mm", quad), ("gray_UNCOVERED", anchors["gray_uncovered_corners_xy"]),
                          ("white_OUTER_inferred", result["white_inferred_outer_corners_image_xy"])):
        points = np.rint(points).astype(np.int32)
        cv2.polylines(annotated, [points], True, (0, 0, 255), 2)
        cv2.putText(annotated, label, tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 255), 1)
    for label, point in {**anchors["points_xy"], **anchors["ruler_tick_centers_xy"]}.items():
        point = tuple(point)
        cv2.circle(annotated, point, 4, (255, 0, 255), -1)
        cv2.putText(annotated, label, (point[0]+5, point[1]-5), cv2.FONT_HERSHEY_SIMPLEX, .35, (255, 0, 255), 1)
    positions = np.asarray(list(names.values()))
    lo, hi = positions.min(axis=0)-.16, positions.max(axis=0)+.16
    scale = 800/max(hi-lo)
    canvas = np.full((900, 1100, 3), 255, np.uint8)
    def pixel(points):
        p = np.asarray(points, float)
        return np.rint(np.stack((50+(p[..., 0]-lo[0])*scale, 850-(p[..., 1]-lo[1])*scale), axis=-1)).astype(np.int32)
    for q in (white_outer, np.asarray(variants["nominal"]["gray_inferred_outer_quad_table_xy_m"])):
        cv2.polylines(canvas, [pixel(q)], True, (120, 120, 120), 2)
    for q in (target, np.asarray(variants["nominal"]["gray_uncovered_quad_table_xy_m"])):
        cv2.polylines(canvas, [pixel(q)], True, (0, 180, 180), 1)
    for name, position in names.items():
        point = tuple(pixel(position))
        cv2.circle(canvas, point, 4, (0, 0, 200), -1)
        label = f"{name} ({position[0]:.3f},{position[1]:.3f})m"
        cv2.putText(canvas, label, (point[0]+6, point[1]-6), cv2.FONT_HERSHEY_SIMPLEX, .37, (0, 0, 0), 1)
    cv2.putText(canvas, "Approximate table XY; +X gray, +Y bowl; no calibrated robot transform", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 1)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"layout_measurements.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    if not cv2.imwrite(str(args.output/"photo09_anchors.png"), annotated) or not cv2.imwrite(str(args.output/"metric_layout.png"), canvas):
        raise RuntimeError("Failed writing audit image")
    print(json.dumps(result["independent_checks"]))


if __name__ == "__main__":
    main()

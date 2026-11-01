"""Small reference evaluation; no inference or simulator state is used here.

Count errors on the manually annotated stack ROI. Lower-layer fragment labels
are deliberately non-exhaustive. This is a correlated-view feasibility check,
not an independent generalization benchmark.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

parser = argparse.ArgumentParser()
parser.add_argument("--annotations", type=Path, required=True)
parser.add_argument("--predictions", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
reference = json.loads(args.annotations.read_text())
args.output.mkdir(parents=True, exist_ok=True)


def box(polygon):
    points = np.asarray(polygon, dtype=float)
    return [float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max())]


def intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def area(a):
    return max(0, a[2]-a[0])*max(0, a[3]-a[1])


def iou(a, b):
    value = intersection(a, b)
    return value/max(area(a)+area(b)-value, 1e-8)


def inside(point, polygon):
    return cv2.pointPolygonTest(np.asarray(polygon, dtype=np.float32), tuple(float(v) for v in point), False) >= 0


def stud_errors(points, references):
    """One-to-one distances within 8 px for a deliberately partial reference set."""
    if not points or not references:
        return []
    distances = np.asarray([[math.dist(p, [r["x"], r["y"]]) for r in references] for p in points])
    rr, cc = linear_sum_assignment((distances > 8)*1000+distances)
    return [float(distances[r, c]) for r, c in zip(rr, cc) if distances[r, c] <= 8]


METHODS = [p.name for p in args.predictions.iterdir() if (p / "raw_bricks").is_dir()]
settings = {
    "scope": "center of raw detection inside manually annotated stack ROI; outside-ROI predictions reported separately",
    "primary_match": "maximum-cardinality one-to-one axis-aligned box IoU >= 0.50, then maximize IoU; merged boxes are ineligible",
    "miss": "confirmed exposed_top reference without primary match",
    "merge": "raw detection covers at least 50% of each of two confirmed exposed_top reference boxes and contains their centers",
    "duplicate": "unmatched non-merge prediction IoU >= 0.50 with an already matched top reference",
    "lower_layer_target": "unmatched non-merge detection center inside a manually marked visible_lower fragment; conservative, non-exhaustive",
    "ambiguous": "reference role ambiguous excluded from recall; otherwise-unmatched detection centered in ambiguous polygon ignored",
    "other_spurious_or_unresolved": "remaining unmatched prediction in stack ROI; may include unannotated lower surfaces, so not all asserted background hallucinations",
    "orientation": "undirected PCA major-axis difference modulo 180 on primary matched instances with available PCA orientation",
    "studs": "deduplicate predicted crop-conditioned stud centers within 3 px, one-to-one match to selected manual visible stud centers within 8 px; no precision on unannotated studs",
    "stud_coverage": "selected manually annotated studs found, conditional on upstream predicted crops being present; misses include missing upstream crops",
    "fullframe_studs": "same selected manual points and 8 px threshold, but independent full-frame raw stud detections; no parent brick proposals or geometry input",
    "top_selection": "raw detector has no exposure/layer class: these are the errors if raw boxes were used directly as target candidates",
    "independence": "views of the same physical arrangement are correlated; no train/test split, significance or generalization estimate",
}
report = {"provenance": {"annotations": str(args.annotations),
                         "annotation_sha256": hashlib.sha256(args.annotations.read_bytes()).hexdigest(),
                         "predictions": str(args.predictions),
                         "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
          "settings": settings, "methods": {}}

for method in METHODS:
    rows = []
    for image in reference["images"]:
        stem = Path(image["file"]).stem
        pred_path = args.predictions / method / "raw_bricks" / f"{stem}.json"
        if not pred_path.is_file():
            continue
        raw = json.loads(pred_path.read_text())["detections"]
        refs = image["instances"]
        tops = [r for r in refs if r["role"] == "exposed_top"]
        amb = [r for r in refs if r["role"] == "ambiguous"]
        lower = [r for r in refs if r["role"] == "visible_lower"]
        gt_boxes = [box(r["polygon"]) for r in tops]
        roi = image.get("stack_roi_polygon", image.get("roi_polygon"))
        if roi is None:
            roi = cv2.convexHull(np.asarray([p for r in refs for p in r["polygon"]], dtype=np.float32)).reshape(-1, 2).tolist()
        evaluated, outside = [], []
        for p in raw:
            b = p["box_xyxy"]
            center = [(b[0]+b[2])/2, (b[1]+b[3])/2]
            (evaluated if inside(center, roi) else outside).append(p)
        merges = {}
        for pi, pred in enumerate(evaluated):
            b = pred["box_xyxy"]
            covered = [gi for gi, g in enumerate(gt_boxes)
                       if intersection(b, g)/max(area(g), 1e-8) >= .5
                       and b[0] <= (g[0]+g[2])/2 <= b[2] and b[1] <= (g[1]+g[3])/2 <= b[3]]
            if len(covered) >= 2:
                merges[pi] = covered
        eligible = [i for i in range(len(evaluated)) if i not in merges]
        matches = []
        if eligible and tops:
            matrix = np.asarray([[iou(evaluated[pi]["box_xyxy"], g) for g in gt_boxes] for pi in eligible])
            # Unit cardinality bonus dominates all IoU tie breakers in this small matrix.
            cost = -1000*(matrix >= .5)-matrix
            pr, gr = linear_sum_assignment(cost)
            matches = [(eligible[p], int(g), float(matrix[p, g])) for p, g in zip(pr, gr) if matrix[p, g] >= .5]
        matched_preds, matched_refs = {p for p, _, _ in matches}, {g for _, g, _ in matches}
        categories = {"merge": list(merges), "duplicate": [], "lower_layer_target": [], "ambiguous_ignored": [], "other_spurious_or_unresolved": []}
        for pi, pred in enumerate(evaluated):
            if pi in matched_preds or pi in merges:
                continue
            b = pred["box_xyxy"]
            center = [(b[0]+b[2])/2, (b[1]+b[3])/2]
            if any(iou(b, gt_boxes[gi]) >= .5 for gi in matched_refs):
                cat = "duplicate"
            elif any(inside(center, r["polygon"]) for r in lower):
                cat = "lower_layer_target"
            elif any(inside(center, r["polygon"]) for r in amb):
                cat = "ambiguous_ignored"
            else:
                cat = "other_spurious_or_unresolved"
            categories[cat].append(pi)
        refinements = json.loads((args.predictions / method / "refinement" / f"{stem}.json").read_text())["detections"]
        refined = {r["parent_detection_id"]: r for r in refinements}
        gate_ids = {r["parent_detection_id"] for r in refinements if r["passes_eight_stud_pca_gate"]}
        angle_errors = []
        for pi, gi, score in matches:
            pred_angle = refined[evaluated[pi]["id"]]["orientation_deg"]
            truth_angle = tops[gi].get("orientation_deg")
            if pred_angle is not None and truth_angle is not None and tops[gi].get("orientation_reference_usable", True):
                delta = abs(float(pred_angle)-float(truth_angle)) % 180
                angle_errors.append(min(delta, 180-delta))
        raw_studs = json.loads((args.predictions / method / "raw_studs" / f"{stem}.json").read_text())["parents"]
        predicted_studs = []
        for parent in raw_studs:
            for stud in sorted(parent["detections"], key=lambda s: -s["confidence"]):
                point = stud["center_image_xy"]
                if not any(math.dist(point, old) < 3 for old in predicted_studs):
                    predicted_studs.append(point)
        manual_studs = [r for r in image.get("studs", []) if not r.get("ambiguous", False)]
        crop_errors = stud_errors(predicted_studs, manual_studs)
        full_path = args.predictions / method / "raw_studs_full" / f"{stem}.json"
        full = json.loads(full_path.read_text()) if full_path.is_file() else {"detections": [], "max_det_cap_reached": False}
        full_points = [r["center_image_xy"] for r in full["detections"]]
        full_errors = stud_errors(full_points, manual_studs)
        row = {"image": image["file"], "correlation_group": image.get("correlation_group"),
               "top_references": len(tops), "ambiguous_instances_excluded": len(amb), "lower_fragments": len(lower),
               "raw_detections_total": len(raw), "outside_stack_roi": len(outside), "evaluated_detections": len(evaluated),
               "matched": len(matches), "missed_exposed": len(tops)-len(matches),
               **{key: len(value) for key, value in categories.items()},
               "orientation_measured": len(angle_errors), "orientation_errors_deg": angle_errors,
               "orientation_errors_over_10deg": sum(e > 10 for e in angle_errors),
               "manual_studs": len(manual_studs), "studs_matched_8px": len(crop_errors), "stud_errors_px": crop_errors,
               "fullframe_studs_total": len(full_points), "fullframe_studs_matched_8px": len(full_errors),
               "fullframe_stud_errors_px": full_errors, "fullframe_stud_cap_reached": full["max_det_cap_reached"],
               "eight_stud_gate_total": len(gate_ids),
               "eight_stud_gate_inside_roi": sum(p["id"] in gate_ids for p in evaluated),
               "eight_stud_gate_outside_roi": sum(p["id"] in gate_ids for p in outside),
               "eight_stud_gate_primary_tp": sum(evaluated[pi]["id"] in gate_ids for pi, _, _ in matches),
               "eight_stud_gate_merged_boxes": sum(evaluated[pi]["id"] in gate_ids for pi in merges),
               "stud_spacing_px_approx": image.get("manual_stud_spacing_px", image.get("stud_spacing_px_approx")),
               "matches": [{"prediction": evaluated[p]["id"], "reference": tops[g]["id"], "iou": v} for p, g, v in matches],
               "prediction_categories": {key: [evaluated[i]["id"] for i in value] for key, value in categories.items()},
               "missed_reference_ids": [r["id"] for i, r in enumerate(tops) if i not in matched_refs]}
        rows.append(row)
    sums = {key: sum(r[key] for r in rows) for key in (
        "top_references", "ambiguous_instances_excluded", "lower_fragments", "raw_detections_total", "outside_stack_roi",
        "evaluated_detections", "matched", "missed_exposed", "merge", "duplicate", "lower_layer_target", "ambiguous_ignored",
        "other_spurious_or_unresolved", "orientation_measured", "orientation_errors_over_10deg", "manual_studs", "studs_matched_8px",
        "fullframe_studs_total", "fullframe_studs_matched_8px", "eight_stud_gate_total", "eight_stud_gate_inside_roi",
        "eight_stud_gate_outside_roi", "eight_stud_gate_primary_tp", "eight_stud_gate_merged_boxes")}
    angles = [e for r in rows for e in r["orientation_errors_deg"]]
    errors = [e for r in rows for e in r["stud_errors_px"]]
    full_errors = [e for r in rows for e in r["fullframe_stud_errors_px"]]
    sums.update({"images": len(rows), "correlation_groups": sorted(set(str(r["correlation_group"]) for r in rows)),
                 "top_recall": sums["matched"]/sums["top_references"] if sums["top_references"] else None,
                 "orientation_median_deg": float(np.median(angles)) if angles else None,
                 "stud_median_error_px": float(np.median(errors)) if errors else None,
                 "stud_max_error_px": max(errors) if errors else None,
                 "fullframe_stud_median_error_px": float(np.median(full_errors)) if full_errors else None,
                 "fullframe_stud_max_error_px": max(full_errors) if full_errors else None,
                 "fullframe_stud_cap_images": sum(r["fullframe_stud_cap_reached"] for r in rows),
                 "eight_stud_gate_recall": sums["eight_stud_gate_primary_tp"]/sums["top_references"] if sums["top_references"] else None})
    report["methods"][method] = {"summary": sums, "images": rows}
(args.output / "evaluation.json").write_text(json.dumps(report, indent=2))
lines = ["method,images,top_refs,matched,missed,merges,duplicates,lower_fragment_targets,other_unmatched,ambiguous_ignored,outside_roi,angle_n,angle_median_deg,stud_refs,crop_stud_matched,crop_stud_median_px,full_stud_matched,full_stud_median_px"]
for method, values in report["methods"].items():
    s = values["summary"]
    lines.append(",".join(str(x) for x in [method, s["images"], s["top_references"], s["matched"], s["missed_exposed"], s["merge"],
        s["duplicate"], s["lower_layer_target"], s["other_spurious_or_unresolved"], s["ambiguous_ignored"], s["outside_stack_roi"],
        s["orientation_measured"], s["orientation_median_deg"], s["manual_studs"], s["studs_matched_8px"], s["stud_median_error_px"],
        s["fullframe_studs_matched_8px"], s["fullframe_stud_median_error_px"]]))
(args.output / "summary.csv").write_text("\n".join(lines)+"\n")
print(json.dumps({m: v["summary"] for m, v in report["methods"].items()}, indent=2))

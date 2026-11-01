"""Independent, fixed-protocol scoring of geometric perception predictions.

This module never changes perception inputs, labels or decision thresholds.
Predictions and evaluation-only references are read from separate directories.
All distances are image pixels; physical layer height is not ground truth here.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment


def envelope(polygon):
    points = np.asarray(polygon, dtype=float)
    return [float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max())]


def intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))


def area(box):
    return max(0, box[2]-box[0])*max(0, box[3]-box[1])


def iou(a, b):
    value = intersection(a, b)
    return value/max(area(a)+area(b)-value, 1e-8)


def inside(point, polygon):
    return cv2.pointPolygonTest(np.asarray(polygon, np.float32), tuple(float(x) for x in point), False) >= 0


def match_boxes(predicted, reference, forbidden=()):
    eligible = [i for i in range(len(predicted)) if i not in forbidden]
    if not eligible or not reference:
        return []
    matrix = np.array([[iou(predicted[i], r) for r in reference] for i in eligible])
    rows, cols = linear_sum_assignment(-1000*(matrix >= .5)-matrix)
    return [(eligible[int(p)], int(r), float(matrix[p, r]))
            for p, r in zip(rows, cols) if matrix[p, r] >= .5]


def point_errors(predicted, reference, max_distance=None):
    if not predicted or not reference:
        return []
    matrix = np.array([[math.dist(p, r) for r in reference] for p in predicted])
    cost = matrix if max_distance is None else (matrix > max_distance)*100000+matrix
    rows, cols = linear_sum_assignment(cost)
    return [float(matrix[p, r]) for p, r in zip(rows, cols)
            if max_distance is None or matrix[p, r] <= max_distance]


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None,
            "max": max(values) if values else None}


def score_image(prediction, reference, missing_slots):
    """Score one frozen observation without changing its references."""
    candidates = prediction["candidates"]
    refs = [r for r in reference["instances"] if r["role"] == "exposed_top"]
    ambiguous = [r for r in reference["instances"] if r["role"] == "ambiguous"]
    lower = [r for r in reference["instances"] if r["role"] == "visible_lower"]
    pos_boxes = [envelope(r["polygon"]) for r in refs]
    boxes = [envelope(c["polygon"]) for c in candidates]
    missing_ids = {r["reference_id"] for r in missing_slots}
    ignored_ambiguities = [r for r in ambiguous if r["id"] not in missing_ids]
    merged = {}
    for p, box in enumerate(boxes):
        covered = [i for i, ref in enumerate(pos_boxes)
                   if intersection(box, ref)/max(area(ref), 1e-8) >= .5
                   and box[0] <= (ref[0]+ref[2])/2 <= box[2]
                   and box[1] <= (ref[1]+ref[3])/2 <= box[3]]
        if len(covered) >= 2:
            merged[p] = covered
    scored_boxes = pos_boxes+[envelope(r["polygon"]) for r in missing_slots]
    matches = match_boxes(boxes, scored_boxes, forbidden=merged)
    positive_matches = [(p, r, value) for p, r, value in matches if r < len(refs)]
    missing_matches = [(p, r-len(refs), value) for p, r, value in matches if r >= len(refs)]
    candidate_for_positive = {r: p for p, r, _ in positive_matches}
    candidate_for_missing = {r: p for p, r, _ in missing_matches}
    pos_decisions = {"present": 0, "missing": 0, "uncertain": 0, "no_match": 0}
    missing_decisions = {"present": 0, "missing": 0, "uncertain": 0, "no_match": 0}
    for i in range(len(refs)):
        p = candidate_for_positive.get(i)
        pos_decisions["no_match" if p is None else candidates[p]["decision"]] += 1
    for i in range(len(missing_slots)):
        p = candidate_for_missing.get(i)
        missing_decisions["no_match" if p is None else candidates[p]["decision"]] += 1
    matched_candidates = {p for p, _, _ in positive_matches}
    matched_reference_ids = {r for _, r, _ in positive_matches}
    duplicates = [p for p, box in enumerate(boxes) if p not in matched_candidates and p not in merged
                  and any(iou(box, pos_boxes[r]) >= .5 for r in matched_reference_ids)]
    present_scored, ambiguous_present_ignored, lower_selections = [], [], []
    for p, candidate in enumerate(candidates):
        if candidate["decision"] != "present":
            continue
        box = boxes[p]
        center = [(box[0]+box[2])/2, (box[1]+box[3])/2]
        if any(inside(center, r["polygon"]) for r in ignored_ambiguities):
            ambiguous_present_ignored.append(p)
        else:
            present_scored.append(p)
        if candidate.get("layer_hypothesis") == "top_compatible":
            if any(inside(center, r["polygon"]) or intersection(box, envelope(r["polygon"]))/max(area(envelope(r["polygon"])), 1e-8) >= .5 for r in lower):
                lower_selections.append(p)
    true_present = sum(candidates[p]["decision"] == "present" for p, _, _ in positive_matches)
    angle_errors, expected_stud_errors, observed_peak_errors = [], [], []
    manual_studs = reference.get("studs", [])
    for p, r, _ in positive_matches:
        candidate, ref = candidates[p], refs[r]
        angle = candidate.get("orientation_deg")
        truth = ref.get("orientation_deg")
        if angle is not None and truth is not None:
            delta = abs(float(angle)-float(truth)) % 180
            angle_errors.append(min(delta, 180-delta))
        selected = [[s["x"], s["y"]] for s in manual_studs if s.get("instance_id") == ref["id"]]
        studs = candidate.get("studs", [])
        projected = [s["expected_xy"] for s in studs if s.get("expected_xy") is not None]
        observed = [s["refined_xy"] for s in studs if s.get("confirmed") and s.get("refined_xy") is not None]
        expected_stud_errors.extend(point_errors(projected, selected))
        observed_peak_errors.extend(point_errors(observed, selected, max_distance=8))
    pos_decisive = pos_decisions["present"]+pos_decisions["missing"]
    missing_decisive = missing_decisions["present"]+missing_decisions["missing"]
    row = {
        "file": reference["file"], "case": prediction.get("evaluation_case", "nominal"),
        "split": prediction.get("evaluation_split"), "correlation_group": reference.get("correlation_group"),
        "positive_reference_count": len(refs), "original_ambiguous_excluded": len(ambiguous),
        "missing_reference_count": len(missing_slots), "lower_fragment_reference_count": len(lower),
        "candidate_count": len(candidates), "positive_decisions": pos_decisions, "missing_decisions": missing_decisions,
        "correct_present": true_present, "missed_individual_faces": len(refs)-true_present,
        "scored_confirmed_present": len(present_scored), "incorrect_confirmed_present": len(present_scored)-true_present,
        "present_instance_precision": true_present/len(present_scored) if present_scored else None,
        "positive_decisive_coverage": pos_decisive/len(refs) if refs else None,
        "positive_correct_present_coverage": true_present/len(refs) if refs else None,
        "missing_decisive_coverage": missing_decisive/len(missing_slots) if missing_slots else None,
        "missing_correct_coverage": missing_decisions["missing"]/len(missing_slots) if missing_slots else None,
        "merged_candidates": len(merged), "merged_confirmed_present": sum(candidates[p]["decision"] == "present" for p in merged),
        "duplicate_candidates": len(duplicates), "duplicate_confirmed_present": sum(candidates[p]["decision"] == "present" for p in duplicates),
        "labeled_lower_fragment_top_selections": len(lower_selections),
        "ambiguous_present_ignored": len(ambiguous_present_ignored),
        "orientation_errors_deg": angle_errors, "projected_stud_errors_px": expected_stud_errors,
        "observed_stud_peak_errors_px": observed_peak_errors, "manual_stud_reference_count": len(manual_studs),
        "registration": prediction.get("registration", {}),
        "matches": [{"candidate": candidates[p]["id"], "reference": refs[r]["id"], "iou": value}
                    for p, r, value in positive_matches],
        "missing_matches": [{"candidate": candidates[p]["id"], "reference": missing_slots[r]["reference_id"], "iou": value}
                            for p, r, value in missing_matches],
        "actual_physical_current_top_accuracy": None,
    }
    return row


def summarize(rows):
    counts = ["positive_reference_count", "original_ambiguous_excluded", "missing_reference_count",
              "lower_fragment_reference_count", "candidate_count", "correct_present", "missed_individual_faces",
              "scored_confirmed_present", "incorrect_confirmed_present", "merged_candidates", "merged_confirmed_present",
              "duplicate_candidates", "duplicate_confirmed_present", "labeled_lower_fragment_top_selections",
              "ambiguous_present_ignored", "manual_stud_reference_count"]
    result = {key: sum(r[key] for r in rows) for key in counts}
    for kind in ("positive_decisions", "missing_decisions"):
        result[kind] = {decision: sum(r[kind][decision] for r in rows)
                        for decision in ("present", "missing", "uncertain", "no_match")}
    p, m = result["positive_decisions"], result["missing_decisions"]
    positive_n, missing_n = result["positive_reference_count"], result["missing_reference_count"]
    result.update({
        "image_observations": len(rows),
        "present_instance_precision": result["correct_present"]/result["scored_confirmed_present"] if result["scored_confirmed_present"] else None,
        "positive_decisive_coverage": (p["present"]+p["missing"])/positive_n if positive_n else None,
        "positive_correct_present_coverage": p["present"]/positive_n if positive_n else None,
        "missing_decisive_coverage": (m["present"]+m["missing"])/missing_n if missing_n else None,
        "missing_correct_coverage": m["missing"]/missing_n if missing_n else None,
        "orientation_deg": stats([v for r in rows for v in r["orientation_errors_deg"]]),
        "projected_stud_error_px": stats([v for r in rows for v in r["projected_stud_errors_px"]]),
        "observed_stud_peak_error_px": stats([v for r in rows for v in r["observed_stud_peak_errors_px"]]),
        "actual_physical_current_top_accuracy": None,
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True, help="Case-specific reference bundle produced by the frozen batch preparer")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = json.loads(args.references.read_text())
    rows, flat = [], []
    for observation in bundle["observations"]:
        predicted = args.predictions / observation["prediction_file"]
        if not predicted.is_file():
            raise FileNotFoundError(f"Missing required prediction: {predicted}")
        prediction = json.loads(predicted.read_text())
        prediction["evaluation_case"] = observation["case"]
        prediction["evaluation_split"] = observation["split"]
        if observation["case"] == "flat_image_sanity":
            count = sum(c["decision"] == "present" for c in prediction["candidates"])
            flat.append({"file": observation["reference"]["file"], "split": observation["split"], "confident_present": count})
        else:
            rows.append(score_image(prediction, observation["reference"], observation["missing_slots"]))
    cases = sorted({r["case"] for r in rows})
    report = {
        "schema": "known-layout-fixed-evaluation-v1", "reference_bundle_sha256": hashlib.sha256(args.references.read_bytes()).hexdigest(),
        "protocol_sha256": bundle["protocol_sha256"], "interpretation": bundle["interpretation"],
        "cases": {case: summarize([r for r in rows if r["case"] == case]) for case in cases},
        "flat_image_sanity": {"observations": flat, "confident_present_total": sum(r["confident_present"] for r in flat)},
        "observations": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"cases": report["cases"], "flat_image_sanity": report["flat_image_sanity"]}, indent=2))


if __name__ == "__main__":
    main()

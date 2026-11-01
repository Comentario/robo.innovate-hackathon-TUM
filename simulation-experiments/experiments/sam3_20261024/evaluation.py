"""Frozen independent SAM 3 box scoring and supplementary mask diagnostics.

No predictions are filtered, refined, deduplicated, or pooled across prompts.
Run image-batch scoring only in the default Pueue queue. --self-test is tiny.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

PROMPTS = {
    "stack": "stack of LEGO bricks",
    "brick": "LEGO brick",
    "brick_2x4": "2x4 LEGO brick",
    "top_surface": "top surface of a LEGO brick",
}


def envelope(polygon):
    a = np.asarray(polygon, float)
    return [float(a[:, 0].min()), float(a[:, 1].min()),
            float(a[:, 0].max()), float(a[:, 1].max())]


def area(a):
    return max(0, a[2]-a[0])*max(0, a[3]-a[1])


def intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0]))*max(0, min(a[3], b[3])-max(a[1], b[1]))


def iou(a, b):
    v = intersection(a, b)
    return v/max(area(a)+area(b)-v, 1e-12)


def inside(point, polygon):
    return cv2.pointPolygonTest(np.asarray(polygon, np.float32), tuple(float(x) for x in point), False) >= 0


def assignment(cost):
    """Same minimum-cost assignment implementation as historical evaluation."""
    rows, columns = linear_sum_assignment(np.asarray(cost, float))
    return list(zip(rows.tolist(), columns.tolist()))


def polygon_mask(polygon, shape):
    result = np.zeros(shape, np.uint8)
    cv2.fillPoly(result, [np.rint(polygon).astype(np.int32)], 1)
    return result.astype(bool)


def mask_overlap(predicted, reference):
    overlap = int(np.count_nonzero(predicted & reference))
    pn, rn = int(predicted.sum()), int(reference.sum())
    return {"intersection_pixels": overlap,
            "polygon_iou": overlap/max(pn+rn-overlap, 1),
            "reference_coverage": overlap/max(rn, 1),
            "prediction_coverage": overlap/max(pn, 1)}


def score_boxes(detections, reference):
    tops = [r for r in reference["instances"] if r["role"] == "exposed_top"]
    ambiguous = [r for r in reference["instances"] if r["role"] == "ambiguous"]
    lower = [r for r in reference["instances"] if r["role"] == "visible_lower"]
    roi = reference["stack_roi_polygon"]
    gt = [envelope(r["polygon"]) for r in tops]
    evaluated, outside = [], []
    for i, d in enumerate(detections):
        b = d["box_xyxy"]
        center = [(b[0]+b[2])/2, (b[1]+b[3])/2]
        (evaluated if inside(center, roi) else outside).append(i)
    merges = {}
    for p in evaluated:
        b = detections[p]["box_xyxy"]
        covered = [g for g, a in enumerate(gt)
                   if intersection(b, a)/max(area(a), 1e-12) >= .5
                   and b[0] <= (a[0]+a[2])/2 <= b[2]
                   and b[1] <= (a[1]+a[3])/2 <= b[3]]
        if len(covered) >= 2:
            merges[p] = covered
    eligible = [p for p in evaluated if p not in merges]
    matches = []
    if eligible and gt:
        matrix = np.array([[iou(detections[p]["box_xyxy"], a) for a in gt] for p in eligible])
        matches = [(eligible[p], g, float(matrix[p, g]))
                   for p, g in assignment(-1000*(matrix >= .5)-matrix) if matrix[p, g] >= .5]
    matched_p, matched_g = {p for p, _, _ in matches}, {g for _, g, _ in matches}
    categories = {"merge": list(merges), "duplicate": [], "lower_layer_target": [],
                  "ambiguous_ignored": [], "other_spurious_or_unresolved": [], "outside_roi": outside}
    for p in evaluated:
        if p in matched_p or p in merges:
            continue
        b = detections[p]["box_xyxy"]
        center = [(b[0]+b[2])/2, (b[1]+b[3])/2]
        if any(iou(b, gt[g]) >= .5 for g in matched_g):
            category = "duplicate"
        elif any(inside(center, r["polygon"]) for r in lower):
            category = "lower_layer_target"
        elif any(inside(center, r["polygon"]) for r in ambiguous):
            category = "ambiguous_ignored"
        else:
            category = "other_spurious_or_unresolved"
        categories[category].append(p)
    roi_box = envelope(roi)
    coarse = [{"detection_id": d["id"], "roi_envelope_iou": iou(d["box_xyxy"], roi_box),
               "roi_envelope_coverage": intersection(d["box_xyxy"], roi_box)/area(roi_box)} for d in detections]
    best = max(coarse, key=lambda x: x["roi_envelope_iou"], default=None)
    highest = coarse[max(range(len(detections)), key=lambda x: detections[x]["score"])] if detections else None
    return {"positive_references": len(tops), "ambiguous_references_excluded": len(ambiguous),
            "lower_fragments": len(lower), "raw_detections": len(detections),
            "matched": len(matches), "missed_individual_faces": len(tops)-len(matches),
            **{k: len(v) for k, v in categories.items()},
            "categories": {k: [detections[p]["id"] for p in v] for k, v in categories.items()},
            "matches": [{"detection_id": detections[p]["id"], "reference_id": tops[g]["id"], "box_iou": value} for p, g, value in matches],
            "merge_references": {detections[p]["id"]: [tops[g]["id"] for g in gs] for p, gs in merges.items()},
            "whole_stack_coarse": {"best_box": best, "highest_score_box": highest,
                                    "any_box_roi_iou_ge_050": bool(best and best["roi_envelope_iou"] >= .5)},
            "physical_current_top_accuracy": None}


def score_masks(detections, masks, reference, box_result):
    shape = (reference["height"], reference["width"])
    tops = [r for r in reference["instances"] if r["role"] == "exposed_top"]
    top_masks = {r["id"]: polygon_mask(r["polygon"], shape) for r in tops}
    lower = {r["id"]: polygon_mask(r["polygon"], shape) for r in reference["instances"] if r["role"] == "visible_lower"}
    roi = polygon_mask(reference["stack_roi_polygon"], shape)
    by_id = {d["id"]: i for i, d in enumerate(detections)}
    pairs = []
    for pair in box_result["matches"]:
        p = by_id[pair["detection_id"]]
        pairs.append({**pair, **mask_overlap(masks[p], top_masks[pair["reference_id"]])})
    rows = []
    for i, d in enumerate(detections):
        covered = [key for key, value in top_masks.items() if np.count_nonzero(masks[i] & value)/max(int(value.sum()), 1) >= .5]
        lower_hits = [key for key, value in lower.items() if np.count_nonzero(masks[i] & value)/max(int(value.sum()), 1) >= .5]
        rows.append({"detection_id": d["id"], "mask_pixels": int(masks[i].sum()),
                     "positive_face_polygons_covered_ge_050": covered,
                     "multiple_face_coverage": len(covered) >= 2,
                     "lower_fragment_polygons_covered_ge_050": lower_hits,
                     "approximate_roi": mask_overlap(masks[i], roi)})
    return {"matched_pair_diagnostics": pairs, "per_detection": rows,
            "multiple_face_masks": sum(r["multiple_face_coverage"] for r in rows),
            "masks_touching_half_lower_fragment": sum(bool(r["lower_fragment_polygons_covered_ge_050"]) for r in rows),
            "interpretation": "Supplementary overlap with coarse historical face polygons/ROI, not exact ground-truth instance segmentation or full-stack segmentation."}


def summarize(rows):
    keys = ["positive_references", "ambiguous_references_excluded", "lower_fragments", "raw_detections", "matched",
            "missed_individual_faces", "merge", "duplicate", "lower_layer_target", "ambiguous_ignored", "other_spurious_or_unresolved", "outside_roi"]
    result = {key: sum(r[key] for r in rows) for key in keys}
    denominator = result["raw_detections"]-result["outside_roi"]-result["ambiguous_ignored"]
    result.update({"annotated_images": len(rows), "individual_face_recall": result["matched"]/max(result["positive_references"], 1),
                   "scored_roi_instance_precision": result["matched"]/denominator if denominator else None,
                   "coarse_stack_localized_views": sum(r["whole_stack_coarse"]["any_box_roi_iou_ge_050"] for r in rows),
                   "multiple_face_masks": sum(r["mask_diagnostics"]["multiple_face_masks"] for r in rows)})
    return result


def self_test():
    from itertools import permutations
    for shape in [(2, 3), (3, 2), (3, 3)]:
        a = np.random.default_rng(7).normal(size=shape)
        pairs = assignment(a)
        actual = sum(a[i, j] for i, j in pairs)
        b = a if shape[0] <= shape[1] else a.T
        expected = min(sum(b[i, p[i]] for i in range(b.shape[0])) for p in permutations(range(b.shape[1]), b.shape[0]))
        assert abs(actual-expected) < 1e-9
    reference = {"stack_roi_polygon": [[0,0],[40,0],[40,20],[0,20]], "instances": [
        {"id": "a", "role": "exposed_top", "polygon": [[1,1],[9,1],[9,9],[1,9]]},
        {"id": "b", "role": "exposed_top", "polygon": [[11,1],[19,1],[19,9],[11,9]]}]}
    r = score_boxes([{"id":"merge", "box_xyxy":[1,1,19,9], "score":1}], reference)
    assert r["merge"] == 1 and r["matched"] == 0 and r["missed_individual_faces"] == 2
    duplicate = score_boxes([{"id":"a", "box_xyxy":[1,1,9,9], "score":1},
                             {"id":"a2", "box_xyxy":[1,1,9,9], "score":.9}], reference)
    assert duplicate["matched"] == 1 and duplicate["duplicate"] == 1
    assert duplicate["missed_individual_faces"] == 1
    print("Tiny assignment, merged-instance and duplicate scoring checks passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch scoring must run through default Pueue")
    reference_bytes = args.reference.read_bytes()
    refs = {r["file"]: r for r in json.loads(reference_bytes)["images"]}
    protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
    if hashlib.sha256(reference_bytes).hexdigest() != protocol["reference_sha256"]:
        raise ValueError("Frozen historical reference hash changed")
    all_rows, scored = [], []
    for prompt_id, prompt in PROMPTS.items():
        for image_number in range(1, 19):
            file = f"img_{image_number}.jpg"
            raw_path = args.predictions/prompt_id/Path(file).stem/"raw.json"
            raw = json.loads(raw_path.read_text())
            if raw["prompt_id"] != prompt_id or raw["prompt"] != prompt:
                raise ValueError(f"Unexpected prompt in {raw_path}")
            if raw["image"] != file or (raw["width"], raw["height"]) != (1280, 720):
                raise ValueError(f"Unexpected image metadata in {raw_path}")
            detections = raw["detections"]
            if len({d["id"] for d in detections}) != len(detections):
                raise ValueError("Detection IDs must be unique per image/prompt")
            masks = []
            for d in detections:
                mask = cv2.imread(str(raw_path.parent/d["mask"]), cv2.IMREAD_GRAYSCALE)
                if mask is None or mask.shape != (720,1280):
                    raise ValueError(f"Missing or non-full-resolution mask: {d}")
                masks.append(mask > 0)
            all_rows.append({"file": file, "prompt_id": prompt_id, "raw_detections": len(detections),
                             "scores": [d["score"] for d in detections], "mask_pixels": [int(m.sum()) for m in masks]})
            if file in refs:
                row = score_boxes(detections, refs[file])
                row.update({"file": file, "prompt_id": prompt_id, "correlation_group": refs[file]["correlation_group"],
                            "mask_diagnostics": score_masks(detections, masks, refs[file], row)})
                scored.append(row)
    report = {"schema": "sam3-fixed-independent-evaluation-v1", "reference_sha256": protocol["reference_sha256"],
              "protocol_sha256": hashlib.sha256(Path(__file__).with_name("protocol.json").read_bytes()).hexdigest(),
              "all18_counts": all_rows, "annotated_observations": scored,
              "by_prompt": {p: summarize([r for r in scored if r["prompt_id"] == p]) for p in PROMPTS},
              "by_prompt_and_group": {p: {g: summarize([r for r in scored if r["prompt_id"] == p and r["correlation_group"] == g]) for g in "ABCD"} for p in PROMPTS}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report["by_prompt"], indent=2))


if __name__ == "__main__":
    main()

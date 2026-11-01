"""Independent frozen evaluation of assisted simulation image-pose fitting."""
import argparse
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np

import base_evaluation as base


VIEWS = ("top", "near_top_x", "near_top_y", "oblique_front", "oblique_side")
CONDITIONS = ("nominal", "perturbed", "blank_nominal")
GATE = .008


def json_scalar(value):
    """Serialize NumPy scalar counters without changing evaluated values."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None,
            "max": max(values) if values else None}


def yaw_error(a, b):
    value = abs(float(a)-float(b)) % math.pi
    return math.degrees(min(value, math.pi-value))


def rotation(q):
    w, x, y, z = np.asarray(q, float)/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def load_truth(directory, protocol):
    names = {"scene_manifest": "manifest.json", "camera_truth": "cameras.json",
             "face_visibility_truth": "annotations.json", "frozen_state": "frozen_physics_state.npy"}
    for key, name in names.items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != protocol["truth_files_sha256"][key]:
            raise ValueError(f"Frozen source truth mismatch: {name}")
    manifest = json.loads((directory/"manifest.json").read_text())
    geometry = manifest["geometry"]
    roots = np.load(directory/"frozen_physics_state.npy")[-300*13:].reshape(300, 13)
    truth, index = [], 0
    for layer in range(10):
        count = geometry["world_axis_counts_by_yaw_quarter_turn"][str(layer % 2)]
        for i in range(count[0]):
            for j in range(count[1]):
                state = roots[index].astype(float)
                width, depth = (4, 2) if layer % 2 == 0 else (2, 4)
                origin = geometry["layer_origins_studs_xy"][layer]
                expected = np.array([geometry["source_xy_m"][0]+(.008*(geometry["border_studs"]+origin[0]+4*i+width/2-16)),
                                     geometry["source_xy_m"][1]+(.008*(geometry["border_studs"]+origin[1]+4*j+depth/2-16)),
                                     .0032+layer*.0096])
                r = rotation(state[3:7])
                yaw = math.atan2(r[1, 0], r[0, 0])
                if np.linalg.norm(state[:3]-expected) > 2e-6 or yaw_error(yaw, layer%2*math.pi/2) > math.degrees(.0001):
                    raise ValueError("Saved root ordering/pose is incompatible with nominal geometry")
                truth.append({"id": f"brick_{layer}_{i}_{j}", "layer": layer,
                              "position_world_m": state[:3].tolist(), "yaw_rad": yaw})
                index += 1
    if index != 300 or len({t["id"] for t in truth}) != 300:
        raise ValueError("Expected exactly300 distinct metric brick identities")
    annotations = {Path(x["file"]).stem: x for x in json.loads((directory/"annotations.json").read_text())["images"]}
    cameras = {x["id"]: x for x in json.loads((directory/"cameras.json").read_text())}
    return truth, annotations, cameras


def reference_for(annotation):
    points = [p for instance in annotation["instances"] for p in instance["polygon"]]
    roi = base.envelope(points)
    result = {**annotation, "stack_roi_polygon": [[roi[0], roi[1]], [roi[2], roi[1]], [roi[2], roi[3]], [roi[0], roi[3]]]}
    if sum(x["role"] == "exposed_top" for x in result["instances"]) != 30:
        raise ValueError("Expected30 visibility-qualified top targets in each source view")
    return result


def pose_valid(pose):
    if pose is None:
        return False
    p = np.asarray(pose.get("position_world_m", []), float)
    return p.shape == (3,) and np.isfinite(p).all() and np.isfinite(pose.get("yaw_rad", float("nan")))


def errors(pose, target):
    delta = np.asarray(pose["position_world_m"], float)-target["position_world_m"]
    return {"translation_mm": float(np.linalg.norm(delta)*1000),
            "xy_mm": float(np.linalg.norm(delta[:2])*1000), "absolute_z_mm": abs(float(delta[2]*1000)),
            "yaw_deg_mod180": yaw_error(pose["yaw_rad"], target["yaw_rad"])}


def error_summary(rows):
    return {key: stats([x[key] for x in rows]) for key in ("translation_mm", "xy_mm", "absolute_z_mm", "yaw_deg_mod180")}


def metric_association(candidates, truth, pose_key="pose_estimate"):
    valid = [i for i, c in enumerate(candidates) if pose_valid(c.get(pose_key))]
    matches = []
    distance = np.empty((len(valid), len(truth)))
    if valid:
        distance = np.array([[np.linalg.norm(np.asarray(candidates[i][pose_key]["position_world_m"])-t["position_world_m"])
                              for t in truth] for i in valid])
        matches = [(valid[i], j, float(distance[i, j]))
                   for i, j in base.assignment(-1000*(distance <= GATE)+distance) if distance[i, j] <= GATE]
    used = {i for i, _, _ in matches}
    matched_truth = {j for _, j, _ in matches}
    duplicates = []
    for row, i in enumerate(valid):
        if i not in used and any(distance[row, j] <= GATE for j in matched_truth):
            duplicates.append(candidates[i]["id"])
    return {"hypotheses": len(candidates), "valid_poses": len(valid), "invalid_or_no_pose": len(candidates)-len(valid),
            "top_matches": sum(truth[j]["layer"] == 9 for _, j, _ in matches),
            "lower_matches": sum(truth[j]["layer"] < 9 for _, j, _ in matches),
            "duplicate_associations": duplicates,
            "unmatched_valid": len(valid)-len(matches),
            "matches": [{"candidate_id": candidates[i]["id"], "truth_id": truth[j]["id"],
                         "truth_layer": truth[j]["layer"], "distance_mm": distance*1000,
                         **errors(candidates[i][pose_key], truth[j])} for i, j, distance in matches]}


def boxes(candidates):
    return [{"id": c["id"], "box_xyxy": base.envelope(c.get("polygon") or c["prior_polygon"]), "score": 0.}
            for c in candidates]


def primary_score(candidates, reference):
    result = base.score_boxes(boxes(candidates), reference)
    result.pop("whole_stack_coarse", None)
    return result


def summarize_primary(rows):
    keys = ("positive_references", "raw_detections", "matched", "missed_individual_faces", "merge", "duplicate",
            "lower_layer_target", "ambiguous_ignored", "other_spurious_or_unresolved", "outside_roi")
    result = {key: sum(row[key] for row in rows) for key in keys}
    denominator = result["raw_detections"]-result["ambiguous_ignored"]-result["outside_roi"]
    result.update({"precision": result["matched"]/denominator if denominator else None,
                   "recall": result["matched"]/result["positive_references"] if result["positive_references"] else None})
    return result


def evaluate_record(record, truth, reference):
    candidates = record["candidates"]
    ids = [c["id"] for c in candidates]
    if len(ids) != 60 or len(set(ids)) != 60 or Counter(c["prior_layer"] for c in candidates) != {8: 30, 9: 30}:
        raise ValueError("Expected60 unique assisted hypotheses:30 in each prior layer8/9")
    if record["pose_origin"] != "brick_body_bottom_center":
        raise ValueError("Pose-origin contract changed")
    for c in candidates:
        if c["decision"] not in ("supported", "uncertain"):
            raise ValueError("Unexpected decision")
        if c["selected_top"] != (c["decision"] == "supported" and c["estimated_layer"] == 9):
            raise ValueError("selected_top semantics changed")
        if not pose_valid(c["prior_pose"]):
            raise ValueError("Every hypothesis must retain a valid prior pose")
    selected = [c for c in candidates if c["selected_top"]]
    supported = [c for c in candidates if c["decision"] == "supported"]
    primary = primary_score(selected, reference)
    top_cohort = [c for c in candidates if c["prior_layer"] == 9]
    cohort = primary_score(top_cohort, reference)
    by_id = {c["id"]: c for c in candidates}
    by_truth = {t["id"]: t for t in truth}
    selected_pose_errors = []
    for match in primary["matches"]:
        candidate = by_id[match["detection_id"]]
        if pose_valid(candidate.get("pose_estimate")):
            selected_pose_errors.append({"candidate_id": candidate["id"], "truth_id": match["reference_id"],
                                         **errors(candidate["pose_estimate"], by_truth[match["reference_id"]])})
    cohort_decisions, cohort_pose_rows = Counter(), []
    for match in cohort["matches"]:
        c = by_id[match["detection_id"]]
        category = "selected_top" if c["selected_top"] else "supported_other_layer" if c["decision"] == "supported" else "uncertain"
        cohort_decisions[category] += 1
        if pose_valid(c.get("pose_estimate")):
            cohort_pose_rows.append({"decision_stratum": category, "candidate_id": c["id"],
                                     **errors(c["pose_estimate"], by_truth[match["reference_id"]])})
    cohort_decisions["no_image_geometry_match"] = 30-cohort["matched"]
    prior = metric_association(candidates, truth, "prior_pose")
    prior_ids = {m["candidate_id"]: m["truth_id"] for m in prior["matches"]}
    paired = []
    for c in candidates:
        target = by_truth[prior_ids[c["id"]]] if c["id"] in prior_ids else None
        update = None
        if pose_valid(c.get("pose_estimate")):
            delta = np.asarray(c["pose_estimate"]["position_world_m"])-c["prior_pose"]["position_world_m"]
            update = {"translation_mm": float(np.linalg.norm(delta)*1000), "absolute_z_mm": abs(float(delta[2]*1000)),
                      "yaw_deg_mod180": yaw_error(c["pose_estimate"]["yaw_rad"], c["prior_pose"]["yaw_rad"])}
        paired.append({"candidate_id": c["id"], "prior_layer": c["prior_layer"], "decision": c["decision"],
                       "selected_top": c["selected_top"], "estimated_layer": c["estimated_layer"],
                       "prior_associated_truth_id": target["id"] if target else None,
                       "prior_error": errors(c["prior_pose"], target) if target else None,
                       "imagefit_error_to_prior_identity": errors(c["pose_estimate"], target) if target and pose_valid(c.get("pose_estimate")) else None,
                       "update_from_prior": update, "fit": c.get("fit"),
                       "stud_observation_records": len(c.get("stud_observations", [])),
                       "uncertainty": c.get("uncertainty"), "reason_flags": c.get("reason_flags", [])})
    return {"primary_selected_top": primary,
            "metric_selected_top": metric_association(selected, truth),
            "metric_all_supported": metric_association(supported, truth),
            "prior_metric_associations": prior,
            "selected_2d_matched_pose_errors_unfiltered_by_3d_gate": selected_pose_errors,
            "top_prior_cohort_decisions_by_image_geometry": dict(cohort_decisions),
            "top_prior_cohort_pose_errors_unfiltered": cohort_pose_rows,
            "paired_prior_imagefit": paired,
            "reporting_from_existing_fields": {
                "reason_flags_nonexclusive": dict(Counter(flag for c in candidates for flag in c.get("reason_flags", []))),
                "prior_cohort_counts": {str(layer): {
                    "hypotheses": sum(c["prior_layer"] == layer for c in candidates),
                    "imagefit_pose_available": int(sum(pose_valid(c.get("pose_estimate")) for c in candidates if c["prior_layer"] == layer)),
                    "supported": sum(c["decision"] == "supported" for c in candidates if c["prior_layer"] == layer),
                    "selected_top": sum(c["selected_top"] for c in candidates if c["prior_layer"] == layer),
                    "uncertain": sum(c["decision"] == "uncertain" for c in candidates if c["prior_layer"] == layer)}
                    for layer in (8, 9)}},
            "counts": {"hypotheses": len(candidates), "supported": len(supported), "selected_top": len(selected),
                       "uncertain": sum(c["decision"] == "uncertain" for c in candidates),
                       "has_imagefit_pose": sum(pose_valid(c.get("pose_estimate")) for c in candidates)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("All image-pose batch scoring must use default Pueue")
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    if hashlib.sha256(Path(__file__).with_name("base_evaluation.py").read_bytes()).hexdigest() != protocol["base_evaluation_sha256"]:
        raise ValueError("Historical box scorer changed")
    truth, annotations, cameras = load_truth(args.truth, protocol)
    observations, blanks = [], []
    for condition in CONDITIONS:
        for view in VIEWS:
            record = json.loads((args.predictions/condition/view/"predictions.json").read_text())
            if record["condition"] != condition or Path(record["image"]).stem != view:
                raise ValueError("Condition/view mismatch")
            result = evaluate_record(record, truth, reference_for(annotations[view]))
            if condition == "blank_nominal":
                blanks.append({"view": view, "counts": result["counts"],
                               "paired_prior_imagefit": result["paired_prior_imagefit"],
                               "reporting_from_existing_fields": result["reporting_from_existing_fields"],
                               "interpretation": "No-image-evidence counterfactual only; no pose accuracy or physical absence metric."})
            else:
                observations.append({"condition": condition, "view": view, **result})
    summaries = {}
    for condition in CONDITIONS[:2]:
        rows = [r for r in observations if r["condition"] == condition]
        metric = [r["metric_selected_top"] for r in rows]
        paired = [p for r in rows for p in r["paired_prior_imagefit"]]
        summaries[condition] = {
            "primary_selected_top": summarize_primary([r["primary_selected_top"] for r in rows]),
            "metric_selected_top": {"selected": sum(r["hypotheses"] for r in metric),
                "top_matches": sum(r["top_matches"] for r in metric), "lower_matches": sum(r["lower_matches"] for r in metric),
                "duplicate_associations": sum(len(r["duplicate_associations"]) for r in metric),
                "unmatched_valid": sum(r["unmatched_valid"] for r in metric), "invalid_or_no_pose": sum(r["invalid_or_no_pose"] for r in metric)},
            "selected_2d_matched_pose_errors_unfiltered": error_summary([x for r in rows for x in r["selected_2d_matched_pose_errors_unfiltered_by_3d_gate"]]),
            "top_prior_cohort_decisions": dict(sum((Counter(r["top_prior_cohort_decisions_by_image_geometry"]) for r in rows), Counter())),
            "reason_flags_nonexclusive": dict(sum((Counter(r["reporting_from_existing_fields"]["reason_flags_nonexclusive"]) for r in rows), Counter())),
            "prior_cohort_counts": {str(layer): dict(sum((Counter(r["reporting_from_existing_fields"]["prior_cohort_counts"][str(layer)]) for r in rows), Counter())) for layer in (8, 9)},
            "prior_errors_by_known_layer": {str(layer): error_summary([p["prior_error"] for p in paired if p["prior_layer"] == layer and p["prior_error"]]) for layer in (8, 9)},
            "imagefit_errors_to_own_prior_identity_by_layer": {str(layer): error_summary([p["imagefit_error_to_prior_identity"] for p in paired if p["prior_layer"] == layer and p["imagefit_error_to_prior_identity"]]) for layer in (8, 9)},
            "update_magnitude_mm": stats([p["update_from_prior"]["translation_mm"] for p in paired if p["update_from_prior"]]),
            "update_yaw_deg": stats([p["update_from_prior"]["yaw_deg_mod180"] for p in paired if p["update_from_prior"]])}
        metric_summary = summaries[condition]["metric_selected_top"]
        metric_summary["top_precision"] = metric_summary["top_matches"]/metric_summary["selected"] if metric_summary["selected"] else None
        metric_summary["top_recall"] = metric_summary["top_matches"]/150
    report = {"schema": "sim-pose-fixed-independent-evaluation-v1", "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "truth_identity_count": len(truth), "conditions": summaries, "observations": observations,
              "blank_sanity": {"observations": blanks, "supported": sum(r["counts"]["supported"] for r in blanks),
                               "selected_top": sum(r["counts"]["selected_top"] for r in blanks)},
              "interpretation": "Assisted known-layout two-layer4DOF imagefit; prior baselines are not detection. Fixed roll/pitch and known layer priors do not establish free6D or automatic top-layer localization. Metric8mm association is not an insertion tolerance. Five correlated views of one frozen scene; no physical access/real-camera equivalence claim."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2, default=json_scalar)+"\n")
    print(json.dumps({"conditions": summaries, "blank_supported": report["blank_sanity"]["supported"]}, indent=2, default=json_scalar))


if __name__ == "__main__":
    main()

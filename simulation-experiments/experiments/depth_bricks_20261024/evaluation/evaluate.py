"""Independent footprint scoring of depth-assisted brick hypotheses."""
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
CONDITIONS = ("real", "invalid", "flat_plane")


def scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported JSON type {type(value).__name__}")


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None,
            "max": max(values) if values else None}


def load_truth(directory, protocol):
    for filename, expected in protocol["truth_sha256"].items():
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen source truth changed: {filename}")
    manifest = json.loads((directory/"manifest.json").read_text())
    geometry = manifest["geometry"]
    if manifest["brick_count"] != 300:
        raise ValueError("Expected corrected300-brick source")
    states = np.load(directory/"frozen_physics_state.npy")[-300*13:].reshape(300, 13)
    poses, index = {}, 0
    for layer in range(10):
        nx, ny = geometry["world_axis_counts_by_yaw_quarter_turn"][str(layer % 2)]
        for i in range(nx):
            for j in range(ny):
                state = states[index].astype(float)
                w, x, y, z = state[3:7]/np.linalg.norm(state[3:7])
                yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
                poses[f"brick_{layer}_{i}_{j}"] = {"xy": state[:2].tolist(), "yaw": yaw, "layer": layer}
                index += 1
    if index != 300:
        raise ValueError("Saved layout/root ordering is not300 bricks")
    annotations = {Path(v["file"]).stem: v for v in json.loads((directory/"annotations.json").read_text())["images"]}
    for view, reference in annotations.items():
        if sum(b["role"] == "exposed_top" for b in reference["instances"]) != 30:
            raise ValueError(f"Expected30 top-target references in {view}")
        bounds = base.envelope([p for b in reference["instances"] for p in b["polygon"]])
        reference["stack_roi_polygon"] = [[bounds[0], bounds[1]], [bounds[2], bounds[1]],
                                          [bounds[2], bounds[3]], [bounds[0], bounds[3]]]
    return poses, annotations


def score_stage(candidates, reference, poses):
    detections = [{"id": c["id"], "box_xyxy": c["box_xyxy"], "score": 0.} for c in candidates]
    score = base.score_boxes(detections, reference)
    score.pop("whole_stack_coarse", None)
    by_id = {c["id"]: c for c in candidates}
    errors, no_plane_pose = [], []
    for match in score["matches"]:
        candidate, target = by_id[match["detection_id"]], poses[match["reference_id"]]
        xy, yaw = candidate.get("center_world_xy_m"), candidate.get("yaw_world_rad")
        if xy is None or yaw is None or np.asarray(xy).shape != (2,) or not np.isfinite(xy).all() or not np.isfinite(yaw):
            no_plane_pose.append(candidate["id"])
            continue
        delta = abs(float(yaw)-target["yaw"]) % math.pi
        errors.append({"candidate_id": candidate["id"], "truth_id": match["reference_id"],
                       "xy_error_mm": float(np.linalg.norm(np.asarray(xy)-target["xy"])*1000),
                       "yaw_error_deg_mod180": math.degrees(min(delta, math.pi-delta)),
                       "decision": candidate["decision"]})
    score["matched_plane_errors"] = errors
    score["matched_without_plane_pose"] = no_plane_pose
    return score


def summary(rows):
    keys = ("positive_references", "raw_detections", "matched", "missed_individual_faces", "merge", "duplicate",
            "lower_layer_target", "ambiguous_ignored", "other_spurious_or_unresolved", "outside_roi")
    result = {key: sum(row[key] for row in rows) for key in keys}
    denominator = result["raw_detections"]-result["outside_roi"]-result["ambiguous_ignored"]
    result["precision"] = result["matched"]/denominator if denominator else None
    result["recall"] = result["matched"]/result["positive_references"] if result["positive_references"] else None
    errors = [e for row in rows for e in row["matched_plane_errors"]]
    result["matched_plane_xy_error_mm"] = stats([e["xy_error_mm"] for e in errors])
    result["matched_shared_ridge_yaw_error_deg_mod180"] = stats([e["yaw_error_deg_mod180"] for e in errors])
    result["matched_without_plane_pose"] = sum(len(row["matched_without_plane_pose"]) for row in rows)
    return result


def evaluate_record(record, reference, poses):
    candidates = record["candidates"]
    if len({c["id"] for c in candidates}) != len(candidates):
        raise ValueError("Candidate IDs must be unique in one observation")
    if any(c["decision"] not in ("present", "uncertain") for c in candidates):
        raise ValueError("No missing-decision semantics are registered here")
    raw = score_stage(candidates, reference, poses)
    present = score_stage([c for c in candidates if c["decision"] == "present"], reference, poses)
    by_id = {c["id"]: c for c in candidates}
    raw_decisions = Counter(by_id[m["detection_id"]]["decision"] for m in raw["matches"])
    raw_decisions["no_match"] = 30-raw["matched"]
    raw_refs, present_refs = ({m["reference_id"] for m in score["matches"]} for score in (raw, present))
    return {"raw_geometry": raw, "image_supported_present": present,
            "raw_geometry_reference_decisions": {key: raw_decisions[key] for key in ("present", "uncertain", "no_match")},
            "raw_references_not_confirmed_present": sorted(raw_refs-present_refs),
            "present_references_not_raw_assigned": sorted(present_refs-raw_refs),
            "counts": {"ridge_hypotheses": len(record["ridges"]), "candidates": len(candidates),
                       "present": sum(c["decision"] == "present" for c in candidates),
                       "uncertain": sum(c["decision"] == "uncertain" for c in candidates)},
            "reason_flags_nonexclusive": dict(Counter(flag for c in candidates for flag in c.get("reason_flags", [])))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch scoring must use default Pueue")
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    if hashlib.sha256(Path(__file__).with_name("base_evaluation.py").read_bytes()).hexdigest() != protocol["base_evaluation_sha256"]:
        raise ValueError("Historical scoring helper changed")
    poses, references = load_truth(args.truth, protocol)
    observations, controls = [], []
    for condition in CONDITIONS:
        for view in VIEWS:
            record = json.loads((args.predictions/condition/view/"detections.json").read_text())
            if record["view"] != view or record["condition"] != condition:
                raise ValueError("Condition/view mismatch")
            if condition == "real":
                observations.append({"view": view, **evaluate_record(record, references[view], poses)})
            else:
                candidates = record["candidates"]
                controls.append({"condition": condition, "view": view, "raw_candidates": len(candidates),
                                 "present_claims": sum(c["decision"] == "present" for c in candidates),
                                 "uncertain": sum(c["decision"] == "uncertain" for c in candidates),
                                 "interpretation": "Sensor-failure/no-ridge control, not physical brick absence."})
    report = {"schema": "depth-assisted-brick-fixed-evaluation-v1",
              "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "raw_geometry": summary([o["raw_geometry"] for o in observations]),
              "image_supported_present": summary([o["image_supported_present"] for o in observations]),
              "raw_geometry_reference_decisions": dict(sum((Counter(o["raw_geometry_reference_decisions"]) for o in observations), Counter())),
              "reason_flags_nonexclusive": dict(sum((Counter(o["reason_flags_nonexclusive"]) for o in observations), Counter())),
              "observations": observations, "controls": controls,
              "control_summary": {condition: {"cases": 5, "raw_candidates": sum(c["raw_candidates"] for c in controls if c["condition"] == condition),
                  "present_claims": sum(c["present_claims"] for c in controls if c["condition"] == condition)} for condition in CONDITIONS[1:]},
              "same_source_rgb_pose_context": {"accepted_top": 0, "top_targets": 150,
                  "limitation": "Different sensor inputs/method; historical real-photo ridge results are not a direct comparison."},
              "interpretation": "Raw depth/ridge partition hypotheses are not confirmed detections. Conditional XY/yaw errors assume shared depth surface plane and ridge direction; no metricZ, free6D, graspability, missing-brick or insertion claim. Five correlated simulated views only."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2, default=scalar)+"\n")
    print(json.dumps({key: report[key] for key in ("raw_geometry", "image_supported_present", "control_summary")}, indent=2, default=scalar))


if __name__ == "__main__":
    main()

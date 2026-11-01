"""Independent Stage1 integration scoring; simulator truth is evaluator-only."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

import partial_evaluation as previous
from references import build_reference


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapted(raw, payload, frame):
    if payload["frame_id"] != frame["id"] or payload["coordinate_frame"] != "table":
        raise ValueError("Public frame/table contract mismatch")
    original = {candidate["id"]: candidate for candidate in raw["candidates"]}
    public = {candidate["candidate_id"]: candidate for candidate in payload["candidates"]}
    if len(original) != len(raw["candidates"]) or len(public) != len(payload["candidates"]) or set(original) != set(public):
        raise ValueError("Adapter changed candidate identity/count")
    fields = {"decision": "decision", "image_polygon": "polygon", "box_xyxy": "box_xyxy",
              "table_xy_m": "center_world_xy_m", "estimated_body_top_from_selected_band_m": "surface_height_world_m",
              "yaw_table_rad": "yaw_world_rad"}
    for identity, candidate in public.items():
        if any(candidate[key] != original[identity][value] for key, value in fields.items()):
            raise ValueError("Adapter changed a decision or metric/image observation")
    return original, public


def eligibility(raw, row, reference, limits):
    candidates = {candidate["id"]: candidate for candidate in raw["candidates"]}
    truth = {instance["id"]: instance for instance in reference["instances"]}
    checks = []
    for match in row["present"]["matches"]:
        candidate, target = candidates[match["detection_id"]], truth[match["reference_id"]]
        xy = np.asarray(candidate.get("center_world_xy_m"), float)
        z, yaw = candidate.get("surface_height_world_m"), candidate.get("yaw_world_rad")
        finite = xy.shape == (2,) and np.isfinite(xy).all() and z is not None and yaw is not None and np.isfinite([z, yaw]).all()
        xy_error = float(np.linalg.norm(xy-target["center_world_xy_m"])) if finite else None
        angle = abs(yaw-target["yaw_world_rad"]) % math.pi if finite else None
        yaw_error = math.degrees(min(angle, math.pi-angle)) if finite else None
        z_error = min(abs(z-reference["body_top_world_m"]), abs(z-reference["stud_top_world_m"])) if finite else None
        accepted = bool(finite and xy_error <= limits["xy_error_m_max"] and yaw_error <= limits["undirected_yaw_error_deg_max"] and z_error <= limits["surface_distance_to_body_or_stud_top_m_max"])
        checks.append({"candidate_id": candidate["id"], "reference_id": target["id"], "eligible": accepted,
                       "xy_error_mm": xy_error*1000 if finite else None, "shared_yaw_error_deg": yaw_error,
                       "surface_to_body_or_stud_top_mm": z_error*1000 if finite else None})
    return {"checks": checks, "eligible_reference_ids": [check["reference_id"] for check in checks if check["eligible"]],
            "noneligible_or_unverified_present": row["present"]["raw_detections"]-sum(check["eligible"] for check in checks),
            "unscorable_present_categories": {key: row["present"][key] for key in ("ambiguous_ignored", "outside_roi")},
            "xy_error_mm_all_matches": previous.stats([check["xy_error_mm"] for check in checks if check["xy_error_mm"] is not None]),
            "shared_yaw_error_deg_all_matches": previous.stats([check["shared_yaw_error_deg"] for check in checks if check["shared_yaw_error_deg"] is not None])}


def mock_score(record, public_present, spec):
    fixtures, guards = record.get("fixtures", []), record.get("guard_checks", [])
    checks = []
    for identity, expected in spec["fixtures"].items():
        entries = [entry for entry in fixtures if entry["fixture_id"] == identity]
        passed = False
        if len(entries) == 1:
            entry = entries[0]; label = entry["input_classification"]; result = entry["result"]
            passed = ((entry["frame_id"], entry["candidate_id"]) in public_present
                      and label["frame_id"] == entry["frame_id"] and label["candidate_id"] == entry["candidate_id"]
                      and all(result[key] == value for key, value in expected.items()))
        checks.append({"fixture_id": identity, "passed": bool(passed)})
    for identity in spec["guards"]:
        entries = [entry for entry in guards if entry["name"] == identity]
        passed = len(entries) == 1 and entries[0]["passed"] and entries[0]["result"]["status"] == "abstain"
        checks.append({"guard": identity, "passed": bool(passed)})
    return {"checks": checks, "passed": all(check["passed"] for check in checks),
            "actual_Challenge1_integration": False, "input": record,
            "interpretation": "Explicit mocked join/routing only; zero observed PRESENT blocks fixtures. Synthetic unit fixtures are not measured classification performance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("truth", "predictions", "frames", "geometry", "benchmark", "protocol", "mock-results", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--split", choices=("development", "reserved"), required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Evaluation/reference image batches require default Pueue")
    protocol = read(args.protocol); benchmark = read(args.benchmark); geometry = read(args.geometry)
    if digest(args.benchmark) != protocol["benchmark_sha256"] or digest(args.geometry) != protocol["geometry_sha256"]:
        raise ValueError("Frozen benchmark or geometry changed")
    for name, expected in protocol["frozen_helper_sha256"].items():
        if digest(Path(__file__).with_name(name)) != expected:
            raise ValueError("Frozen evaluation helper changed")
    cases = {case["id"]: case for case in benchmark["cases"]}
    frames = read(args.frames)
    for frame in frames:
        if "state_id" in frame and "case_id" in frame and frame["state_id"] != frame["case_id"]:
            raise ValueError("Private state/case mapping inconsistent")
        frame["case_id"] = frame.get("case_id", frame.get("state_id"))
    selected_cases = protocol[args.split+"_cases"]
    selected = [frame for frame in frames if frame["case_id"] in selected_cases]
    expected = {(case, view, None) for case in selected_cases for view in protocol["views"]}
    controls = {control["id"]: control for control in protocol["controls"]}
    if args.split == "development":
        expected |= {(control["case_id"], control["view"], control["id"]) for control in controls.values()}
    if len({frame["id"] for frame in frames}) != len(frames) or len(selected) != len(expected) or {(frame["case_id"], frame["view"], frame.get("control_id")) for frame in selected} != expected:
        raise ValueError("Frozen split/private frame mapping incomplete or duplicated")
    rows, negatives, references, public_present, cameras = [], [], {}, set(), {}
    for frame in selected:
        capture = args.truth/frame["case_id"]
        manifest = read(capture/"manifest.json")
        if manifest["post_connection_physics_steps"] != 0 or not manifest["all_capture_states_exactly_equal"]:
            raise ValueError("Stage1 capture is not the specified static snapshot")
        depth = None
        if frame.get("control_id"):
            path = Path(frame["depth_input_path"])
            depth = np.load(path if path.is_absolute() else args.frames.parent/path, allow_pickle=False)
        reference = build_reference(capture, frame["view"], geometry, cases[frame["case_id"]], depth)
        values = [reference[key] for key in ("actual_camera_eye_world_m", "actual_camera_rotation_world_to_optical", "actual_camera_intrinsics")]
        if frame["view"] in cameras and any(np.max(np.abs(np.asarray(x)-y)) > 1e-6 for x, y in zip(values, cameras[frame["view"]])):
            raise ValueError("Actual evaluation cameras changed across cases")
        cameras[frame["view"]] = values; references[frame["id"]] = reference
        folder = args.predictions/frame["id"]
        raw, payload = read(folder/"r3.json"), read(folder/"candidates.json")
        original, public = adapted(raw, payload, frame)
        public_present |= {(frame["id"], identity) for identity, candidate in public.items() if candidate["decision"] == "present"}
        metadata = {"frame_id": frame["id"], "case_id": frame["case_id"], "view": frame["view"],
                    "control_id": frame.get("control_id"), "current_layer": reference["current_layer"],
                    "visibility_counts": reference["visibility_counts"], "unknown_removed_counts": dict(Counter(entry["classification"] for entry in reference["unknown_removed"])),
                    "observable_missing_references": len(reference["missing_references"])}
        if frame.get("control_id") in controls and controls[frame["control_id"]]["operation"] == "all_depth_NaN":
            negatives.append({**metadata, "false_supported_claims": sum(candidate["decision"] in ("present", "missing") for candidate in original.values())})
            continue
        row = {**metadata, **previous.score_frame(raw, reference)}
        row["metric_eligibility"] = eligibility(raw, row, reference, protocol["matching"]["metric_eligibility"])
        rows.append(row)
    primary = [row for row in rows if row["control_id"] is None]
    patch = [row for row in rows if row["control_id"] is not None]
    per_state = {case: {"eligible_present": sum(len(row["metric_eligibility"]["eligible_reference_ids"]) for row in primary if row["case_id"] == case)} for case in selected_cases}
    for value in per_state.values():
        value["at_least_one_eligible_present"] = value["eligible_present"] >= 1
    confidence_errors = sum(row["metric_eligibility"]["noneligible_or_unverified_present"]+row["joint"]["wrong_missing_on_present"]+row["joint"]["wrong_height_missing_on_absence"]+len(row["joint"]["unverified_missing"]) for row in rows)
    control_pass = all(row["false_supported_claims"] == 0 for row in negatives) and all(row["counts"].get("missing", 0) == 0 for row in patch)
    mock = mock_score(read(args.mock_results), public_present, protocol["mock_handoff"])
    report = {"schema": "stage1-independent-integration-smoke-results-v1", "split": args.split,
              "summary": previous.summarize(primary), "observations": rows, "all_NaN_controls": negatives,
              "NaN_patch": previous.summarize(patch) if patch else None, "per_state_eligibility": per_state,
              "mock_handoff": mock, "gate": {"scope": "INTEGRATION SMOKE ONLY", "all_states_have_candidate": all(value["at_least_one_eligible_present"] for value in per_state.values()),
                  "confidence_errors_including_unverified": confidence_errors, "controls_pass": control_pass, "mock_handoff_pass": mock["passed"]},
              "protocol_sha256": digest(args.protocol), "benchmark_sha256": digest(args.benchmark), "geometry_sha256": digest(args.geometry),
              "source_sha256": digest(Path(__file__)), "references_sha256": previous.canonical_hash(references), "limitations": protocol["limitations"]}
    report["gate"]["passed"] = report["gate"]["all_states_have_candidate"] and confidence_errors == 0 and control_pass and mock["passed"]
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("evaluation.json", report), ("references.json", references)):
        (args.output/name).write_text(json.dumps(value, indent=2, default=previous.scalar, allow_nan=False)+"\n")
    print(json.dumps({"split": args.split, "gate": report["gate"], "states": per_state}, default=previous.scalar))


if __name__ == "__main__":
    main()

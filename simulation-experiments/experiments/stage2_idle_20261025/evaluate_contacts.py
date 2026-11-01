"""Queued independent contact-stream/equivalence audit; no solver replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_difference(before, after):
    if before.shape != after.shape or before.shape != (301, 13) or not np.isfinite([before, after]).all():
        raise ValueError("Expected finite301x13 source states")
    dot = np.abs(np.sum(before[:, 3:7]*after[:, 3:7], axis=1)/(np.linalg.norm(before[:, 3:7], axis=1)*np.linalg.norm(after[:, 3:7], axis=1)))
    return {"source_position_m_max": float(np.linalg.norm(before[:, :3]-after[:, :3], axis=1).max()),
            "source_orientation_rad_max": float((2*np.arccos(np.clip(dot, 0, 1))).max()),
            "source_linear_velocity_m_s_max": float(np.linalg.norm(before[:, 7:10]-after[:, 7:10], axis=1).max()),
            "source_angular_velocity_rad_s_max": float(np.linalg.norm(before[:, 10:13]-after[:, 10:13], axis=1).max())}


def flatten_strings(value):
    if isinstance(value, str):
        return [value]
    return [item for part in value for item in flatten_strings(part)]


def summarize_arrays(data):
    n = np.asarray(data["normal_impulses_Ns"]).reshape(-1)
    normals = np.asarray(data["normal_vectors_world"]).reshape(-1, 3)
    tangent = np.asarray(data["friction_impulses_world_Ns"]).reshape(-1, 3)
    normal_points = np.asarray(data["normal_points_world_m"]).reshape(-1, 3)
    friction_points = np.asarray(data["friction_points_world_m"]).reshape(-1, 3)
    if len(n) != len(normals) or len(n) != len(normal_points) or len(tangent) != len(friction_points):
        raise ValueError("Contact point/vector lengths differ")
    finite = all(np.isfinite(value).all() for value in data.values())
    if not finite:
        return {"finite": False, "normal_entries": len(n), "friction_entries": len(tangent)}
    normal_vectors = n[:, None]*normals
    normal_sum, tangent_sum = normal_vectors.sum(axis=0), tangent.sum(axis=0)
    com = np.asarray(data["com_after_step_world_m"])
    net = np.asarray(data["all_body_net_normal_impulse_world_Ns"]).reshape(-1, 3).sum(axis=0)
    filtered = np.asarray(data["filtered_normal_impulse_matrix_world_Ns"]).reshape(-1, 3).sum(axis=0)
    return {"finite": True, "normal_entries": len(n), "friction_entries": len(tangent),
            "reported_normal_scalar_abs_sum_Ns": float(np.abs(n).sum()),
            "reported_friction_vector_norm_sum_Ns": float(np.linalg.norm(tangent, axis=1).sum()),
            "candidate_normal_sum_Ns_sign_unverified": normal_sum.tolist(),
            "reported_friction_sum_Ns": tangent_sum.tolist(),
            "reported_subset_candidate_normal_moment_about_post_COM_Nms": np.cross(normal_points-com, normal_vectors).sum(axis=0).tolist(),
            "reported_subset_friction_moment_about_post_COM_Nms": np.cross(friction_points-com, tangent).sum(axis=0).tolist(),
            "API_net_normal_impulse_Ns": net.tolist(), "API_filtered_normal_sum_Ns": filtered.tolist(),
            "candidate_normal_minus_API_net_norm_Ns": float(np.linalg.norm(normal_sum-net)),
            "filtered_minus_API_net_norm_Ns": float(np.linalg.norm(filtered-net)),
            "interpretation": "Reported subset only; normal sign, completeness and substep timing are not established by an arithmetic sum. Not a complete body wrench or contact-free proof."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("observation", "baseline", "protocol", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Contact-array evaluation requires default Pueue")
    protocol = read(args.protocol); tolerances = protocol["equivalence_tolerances"]
    for name, expected in protocol["baseline"]["frozen_files_sha256"].items():
        if sha(args.baseline/name) != expected:
            raise ValueError("Baseline pin changed: "+name)
    baseline, observed = [read(path/"diagnostic_report.json") for path in (args.baseline, args.observation)]
    traces = [lines(path/"diagnostic_trace.jsonl") for path in (args.baseline, args.observation)]
    metadata = read(args.observation/"contact_observations/metadata.json")
    contacts = lines(args.observation/"contact_observations/trace.jsonl")
    checks = {"source_ids_order_equal": observed["source_ids"] == baseline["source_ids"],
              "physical_thresholds_equal": observed["thresholds_after"] == baseline["thresholds_after"],
              "default_numerical_epsilon": observed["numerical_epsilon"]["effective_requested"] == .0001,
              "steps_equal": observed["steps_executed"] == baseline["steps_executed"] == 7,
              "budget_respected": 1 <= observed["steps_executed"] <= protocol["budget"]["maximum_postassembly_steps"],
              "same_first_break_events": observed["first_failure"] is not None and observed["first_failure"]["broken_connections"] == baseline["first_failure"]["broken_connections"],
              "same_terminal_component_counts": observed["first_failure"] is not None and all(observed["first_failure"][key] == baseline["first_failure"][key] for key in ("source_parts", "native_connections")),
              "observation_setting_recorded_false": metadata["observation_setting"]["after"] is False,
              "no_reporter_or_solver_authoring_claimed": metadata["reporter_authoring"] is False and metadata["stabilization_sleep_solver_changes"] is False}
    checks["native_trace_sequences_complete"] = all(
        [row["step"] for row in trace] == list(range(report["steps_executed"]+1))
        for trace, report in zip(traces, (baseline, observed)))
    differences = {}
    for stage in ("initial", "last"):
        delta = state_difference(np.load(args.baseline/f"diagnostic_states_{stage}.npy", allow_pickle=False), np.load(args.observation/f"diagnostic_states_{stage}.npy", allow_pickle=False))
        differences[stage] = delta
        checks[stage+"_states_within_tolerance"] = all(value <= tolerances[key] for key, value in delta.items())
    base_steps = {row["step"]: row for row in traces[0]}
    per_step = []
    for row in traces[1]:
        old = base_steps.get(row["step"])
        if old is None:
            checks["per_step_baseline_comparison"] = False
            continue
        joints = [np.asarray(value, float) if value is not None else None for value in
                  (row["joint_positions"], old["joint_positions"], row["joint_velocities"], old["joint_velocities"])]
        if any(value is None or value.shape != (9,) or not np.isfinite(value).all() for value in joints):
            per_step.append({"step": row["step"], "differences": None, "passed": False, "reason": "joint_state_missing_or_nonfinite"})
            continue
        delta = {"time_s": abs(row["physics_time_s"]-old["physics_time_s"]),
                 "q_native": float(np.max(np.abs(joints[0]-joints[1]))),
                 "qd_native": float(np.max(np.abs(joints[2]-joints[3])))}
        allowed = {"time_s": tolerances["simulation_time_s_max"], "q_native": tolerances["joint_position_native_units_max"], "qd_native": tolerances["joint_velocity_native_units_per_s_max"]}
        for field, limit in (("max_position_drift_m", "source_position_m_max"), ("max_orientation_drift_rad", "source_orientation_rad_max"),
                             ("max_linear_speed_m_s", "source_linear_velocity_m_s_max"), ("max_angular_speed_rad_s", "source_angular_velocity_rad_s_max")):
            delta[field] = abs(row[field]-old[field]); allowed[field] = tolerances[limit]
        passed = all(value <= allowed[key] for key, value in delta.items()) and all(row[key] == old[key] for key in ("source_parts", "native_connections", "broken_connections"))
        per_step.append({"step": row["step"], "differences": delta, "passed": passed})
    checks["per_step_baseline_comparison"] = checks.get("per_step_baseline_comparison", True) and len(traces[0]) == len(traces[1]) and all(row["passed"] for row in per_step)
    checks["contact_steps_complete"] = [row["step"] for row in contacts] == list(range(1, observed["steps_executed"]+1))
    observed_steps = {row["step"]: row for row in traces[1]}
    checks["contact_bodies_complete"] = all(set(row["bodies"]) == set(protocol["instrumentation"]["watched_bodies"]) for row in contacts)
    checks["contact_native_clocks_aligned"] = all(
        row["step"] in observed_steps and row.get("physics_time_after_s") is not None
        and abs(row["physics_time_after_s"]-observed_steps[row["step"]]["physics_time_s"]) <= tolerances["simulation_time_s_max"]
        and abs(row["physics_time_s"]-observed_steps[row["step"]]["physics_time_s"]) <= tolerances["simulation_time_s_max"]
        for row in contacts)
    requested = set(metadata["requested_all_scene_actor_filters"]+metadata["requested_standalone_static_filters"])
    coverage = {}; body_rows = []; warnings = set()
    for name, view in metadata["resolved_views"].items():
        resolved = set(flatten_strings(view["filter_paths"]))
        coverage[name] = {"requested_filter_paths": len(requested), "resolved_filter_paths": len(resolved), "unresolved_requested_paths": sorted(requested-resolved),
                          "allocated_capacity": view["max_contact_data_count"]}
        if requested-resolved:
            warnings.add("contact_partner_mapping_or_coverage_unknown")
        if view["max_contact_data_count"] != protocol["budget"]["normal_contact_entry_capacity"]:
            warnings.add("unexpected_contact_capacity")
    for row in contacts:
        timing = {"step": row["step"], "before": row.get("physics_time_before_s"), "after": row.get("physics_time_after_s"), "dt": row["physics_dt_s"]}
        aligned = timing["before"] is not None and timing["after"] is not None and abs(timing["after"]-timing["before"]-timing["dt"]) <= tolerances["simulation_time_s_max"]
        if not aligned:
            warnings.add("time_alignment_unknown")
        for name, summary in row["bodies"].items():
            path = args.observation/summary["file"]
            with np.load(path, allow_pickle=False) as stored:
                values = summarize_arrays({key: stored[key] for key in stored.files})
            values.update(body=name, step=row["step"], timing=timing, trace_status=summary["status"], source_npz_sha256=sha(path),
                          normal_dt_scaling_max_error_Ns=summary["normal_dt_scaling_max_error_Ns"], friction_dt_scaling_max_error_Ns=summary["friction_dt_scaling_max_error_Ns"])
            if not values["finite"] or summary["status"] != "recorded_coverage_and_sign_unverified":
                warnings.add("invalid_or_capacity_limited_stream")
            body_rows.append(values)
    positive = metadata.get("positive_reporting_control")
    positive_verified = isinstance(positive, dict) and positive.get("established") is True and bool(positive.get("independent_basis"))
    if not positive_verified:
        warnings.add("no_positive_reporting_control")
    warnings.update(("normal_sign_unverified", "friction_completeness_unverified", "substep_time_alignment_unverified"))
    equivalent = all(checks.values())
    result = {"schema": "bounded-contact-observation-evaluation-v1", "diagnostic_completed": True,
              "idle_validated": False, "capture_validated": False, "manipulation_validated": False,
              "baseline_equivalent_within_frozen_bounds": equivalent, "checks": checks, "state_differences": differences, "per_step_equivalence": per_step,
              "contact_filter_coverage": coverage, "reported_body_steps": body_rows,
              "active_normal_entries": sum(row["normal_entries"] for row in body_rows), "active_friction_entries": sum(row["friction_entries"] for row in body_rows),
              "positive_reporting_control_verified": positive_verified, "contact_completeness": "unknown", "unknown_categories": sorted(warnings),
              "native_JH_comparison": {"performed": False, "reason": "Completeness/sign/substep alignment not independently validated; no native matrices replayed or full-wrench causal attribution."},
              "provenance": {"protocol_sha256": sha(args.protocol), "source_sha256": sha(Path(__file__)), "baseline_report_sha256": sha(args.baseline/"diagnostic_report.json"),
                             "observed_report_sha256": sha(args.observation/"diagnostic_report.json"), "contact_metadata_sha256": sha(args.observation/"contact_observations/metadata.json")},
              "conclusion": "Reporting instrumentation reproduces the baseline within declared checks; contact completeness/load origin remains unknown." if equivalent else "Instrumentation equivalence failed or is unverified; contact stream cannot explain the original baseline causally."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"contact_evaluation.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    (args.output/"REPORT.md").write_text("# Bounded contact observation\n\n"+result["conclusion"]+"\n\nReported normal/friction entries: "+str(result["active_normal_entries"])+" / "+str(result["active_friction_entries"])+".\n\nAll-zero output is not evidence of zero physical load. Idle, grasp and extraction remain unvalidated.\n")
    print(json.dumps({"baseline_equivalent": equivalent, "normal_entries": result["active_normal_entries"], "friction_entries": result["active_friction_entries"], "unknown": result["unknown_categories"]}))


if __name__ == "__main__":
    main()

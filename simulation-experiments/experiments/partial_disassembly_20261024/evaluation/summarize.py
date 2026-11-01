"""Reporting only: aggregate explicitly supplied, already-scored evaluations.

Run in the default Pueue queue. This script never loads references, sensor
images/depth, predictions, or captures, and never searches for reserved results.
"""
import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from collections import Counter
from pathlib import Path


DECISIONS = ("present", "missing", "uncertain", "no_match")
BOX_COUNTS = ("positive_references", "raw_detections", "matched",
              "missed_individual_faces", "merge", "duplicate", "lower_layer_target",
              "ambiguous_ignored", "other_spurious_or_unresolved", "outside_roi")
CHAIN_KEYS = ("uncovered_reference_ridges", "split_reference_ridges",
              "mixed_reference_ridge_parentchains")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def stats(values):
    """Same linear percentile convention as the frozen scorer's NumPy default."""
    values = sorted(values)
    if not values:
        return {"count": 0, "median": None, "p90": None, "max": None}
    def percentile(fraction):
        index = (len(values) - 1) * fraction
        lower = math.floor(index)
        upper = math.ceil(index)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)
    return {"count": len(values), "median": percentile(.5),
            "p90": percentile(.9), "max": values[-1]}


def aggregate(rows):
    """Arithmetic over saved associations only; no matching or classification."""
    output = {"frames": len(rows)}
    for stage in ("raw_geometry", "present"):
        total = {key: sum(row[stage][key] for row in rows) for key in BOX_COUNTS}
        denominator = total["raw_detections"] - total["outside_roi"] - total["ambiguous_ignored"]
        task = sum(len(row[stage]["height_consistent_reference_ids"]) for row in rows)
        total.update(scored_precision_denominator=denominator,
                     image_precision=ratio(total["matched"], denominator),
                     image_recall=ratio(total["matched"], total["positive_references"]),
                     height_consistent_matches=task,
                     height_consistent_precision=ratio(task, denominator),
                     height_consistent_recall=ratio(task, total["positive_references"]),
                     selected_lower_layer=sum(len(row[stage]["selected_lower_layer_ids"]) for row in rows),
                     height_inconsistent_claims=sum(len(row[stage]["height_inconsistent_ids"]) for row in rows),
                     lower_flags_with_uncovered_projection=sum(
                         item["includes_vertically_uncovered_lower"] for row in rows
                         for item in row[stage]["lower_footprint_details"]))
        for metric in ("xy_error_mm", "shared_yaw_error_deg"):
            total[metric] = stats([item[metric] for row in rows
                                   for item in row[stage]["matched_plane_errors"]])
        output[stage] = total
    for kind in ("positive_decisions", "missing_decisions"):
        output[kind] = {decision: sum(row["joint"][kind][decision] for row in rows)
                        for decision in DECISIONS}
    positive = output["positive_decisions"]
    missing = output["missing_decisions"]
    known_calls = sum(row["joint"]["known_missing_calls"] for row in rows)
    correct_missing = sum(row["joint"]["correct_missing"] for row in rows)
    output.update(
        known_missing_calls=known_calls, correct_missing=correct_missing,
        known_missing_precision=ratio(correct_missing, known_calls),
        observable_missing_references=sum(missing.values()),
        correct_missing_recall=ratio(correct_missing, sum(missing.values())),
        positive_decisive_coverage=ratio(positive["present"] + positive["missing"], sum(positive.values())),
        missing_decisive_coverage=ratio(missing["present"] + missing["missing"], sum(missing.values())),
        positive_matched_uncertain=positive["uncertain"], positive_no_match=positive["no_match"],
        missing_matched_uncertain=missing["uncertain"], missing_no_match=missing["no_match"],
        wrong_missing_on_present=sum(row["joint"]["wrong_missing_on_present"] for row in rows),
        wrong_height_missing_on_absence=sum(row["joint"]["wrong_height_missing_on_absence"] for row in rows),
        present_on_absence_references=sum(len(row["joint"]["present_on_absence_reference"]) for row in rows),
        unverified_missing_calls=sum(len(row["joint"]["unverified_missing"]) for row in rows),
        phase_error_mm=stats([item["phase_error_mm"] for row in rows
                              for item in row["joint"]["matches"] if "phase_error_mm" in item]))
    decisions = sum((Counter(row["counts"]) for row in rows), Counter())
    output["candidate_decisions"] = {decision: decisions[decision] for decision in DECISIONS[:3]}
    output["band_frames"] = {classification: sum(
        row["band_diagnostic"]["classification"] == classification for row in rows)
        for classification in ("correct_current_layer", "unsupported", "supported_wrong_layer_or_height")}
    output["height_consistent_band_frames_including_unsupported"] = sum(
        row["band_diagnostic"]["height_consistent"] for row in rows)
    output["chain_stats"] = {"reference_ridges": sum(row["chain_stats"]["reference_ridges"] for row in rows),
                             **{key: sum(len(row["chain_stats"][key]) for row in rows) for key in CHAIN_KEYS}}
    output["reason_flags_nonexclusive"] = dict(sum(
        (Counter(row["reason_flags_nonexclusive"]) for row in rows), Counter()))
    output["unknown_removed_counts"] = dict(sum(
        (Counter(row["unknown_removed_counts"]) for row in rows), Counter()))
    output["visibility_counts"] = dict(sum((Counter(row["visibility_counts"]) for row in rows), Counter()))
    gaps = [gap for row in rows for gap in row["gap_anchor_diagnostics"]]
    output["gap_anchor_diagnostics"] = {
        "bracketed_diagnostic_slots": len(gaps),
        "both_anchor_locations_matched": sum(bool(gap["left_match"] and gap["right_match"]) for gap in gaps),
        "both_anchor_decisions_present": sum(
            bool(gap["left_match"] and gap["right_match"]
                 and gap["left_match"]["decision"] == gap["right_match"]["decision"] == "present")
            for gap in gaps),
        "classification_counts": dict(Counter(gap.get("classification") for gap in gaps)),
        "interpretation": "Saved location associations; inferred geometry is not an observed physical seam."}
    return output


def key(row):
    return row["case_id"], row["view"], row.get("control_id")


def flatten(value, prefix=""):
    result = {}
    for name, item in value.items():
        name = prefix + str(name)
        if isinstance(item, dict):
            result.update(flatten(item, name + "."))
        else:
            result[name] = json.dumps(item, separators=(",", ":")) if isinstance(item, list) else item
    return result


def write_csv(path, records):
    records = [flatten(record) for record in records]
    fields = list(dict.fromkeys(field for record in records for field in record))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def geometry_signature(case):
    return json.dumps({name: case[name] for name in
                       ("remove_top_ridge_brick", "keep_only_top_ridge_brick")}, sort_keys=True)


def comparisons(evaluation, field, rows):
    selected = {key(row) for row in rows}
    records = [row for row in evaluation.get(field, []) if key(row) in selected]
    return {"recovered": sum(len(row["recovered_reference_ids"]) for row in records),
            "lost": sum(len(row["lost_reference_ids"]) for row in records)}


def report_one(version, path, evaluation, cases):
    observations = evaluation["observations"]
    primary = [row for row in observations if row["control_id"] is None]
    meta = {"version": version, "split": evaluation["split"]}
    grouped, frames, artifacts = [], [], []
    groups = [("overall", "all", primary)]
    for dimension in ("view", "palette", "case_id"):
        value_of = lambda row: cases[row["case_id"]]["palette"] if dimension == "palette" else row[dimension]
        for value in sorted({value_of(row) for row in primary}):
            groups.append((dimension, value, [row for row in primary if value_of(row) == value]))
    for dimension, value, rows in groups:
        grouped.append({**meta, "group_dimension": dimension, "group_value": value,
                        **aggregate(rows), "vs_parent": comparisons(evaluation, "previous_comparison", rows),
                        "vs_B0": comparisons(evaluation, "baseline_comparison", rows)})
    for row in observations:
        frames.append({**meta, "frame_id": row["frame_id"], "case_id": row["case_id"],
                       "view": row["view"], "palette": cases[row["case_id"]]["palette"],
                       "control_id": row["control_id"], "current_layer": row["current_layer"],
                       **aggregate([row]), "band_diagnostic": row["band_diagnostic"],
                       "task_correct_reference_ids": row["task_correct_reference_ids"],
                       "vs_parent": comparisons(evaluation, "previous_comparison", [row]),
                       "vs_B0": comparisons(evaluation, "baseline_comparison", [row])})
    for row in observations + evaluation["sensor_controls"]:
        directory = path.parent.parent / "predictions" / row["frame_id"]
        paths = {name: str((directory / name).resolve()) for name in
                 ("overlay.png", "top_band_world_xy.png", "ridge_mask_world_xy.png")
                 if (directory / name).is_file()}
        artifacts.append({**meta, "frame_id": row["frame_id"], "case_id": row["case_id"],
                          "view": row["view"], "control_id": row["control_id"],
                          "snapshot": str(path.parents[2].resolve()), "saved_artifacts": paths,
                          "failure_example": bool(row.get("present", {}).get("missed_individual_faces", 0)
                                                  or row.get("false_supported_claims", 0)
                                                  or ("band_diagnostic" in row and row["band_diagnostic"]["classification"] != "correct_current_layer"))})
    color_pairs = []
    for first, second in itertools.combinations(primary, 2):
        a, b = cases[first["case_id"]], cases[second["case_id"]]
        if first["view"] != second["view"] or a["palette"] == b["palette"] or geometry_signature(a) != geometry_signature(b):
            continue
        sa, sb = aggregate([first]), aggregate([second])
        color_pairs.append({**meta, "view": first["view"], "case_a": a["id"], "case_b": b["id"],
                            "palette_a": a["palette"], "palette_b": b["palette"],
                            "task_tp_a": sa["present"]["height_consistent_matches"],
                            "task_tp_b": sb["present"]["height_consistent_matches"],
                            "task_tp_b_minus_a": sb["present"]["height_consistent_matches"] - sa["present"]["height_consistent_matches"],
                            "correct_missing_a": sa["correct_missing"], "correct_missing_b": sb["correct_missing"],
                            "lower_claims_a": sa["present"]["selected_lower_layer"],
                            "lower_claims_b": sb["present"]["selected_lower_layer"],
                            "interpretation": "Same removal geometry/view; correlated static renders, not independent generalization evidence."})
    return {"groups": grouped, "frames": frames, "artifacts": artifacts, "color_pairs": color_pairs,
            "controls": [{**meta, **row} for row in evaluation["sensor_controls"]],
            "transitions": [{**meta, **row} for row in evaluation["state_pair_transitions"]],
            "recoveries": [{**meta, "comparison": name, **row} for name in
                           ("previous_comparison", "baseline_comparison") for row in evaluation.get(name, [])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", action="append", required=True, metavar="VERSION=FILE")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch reporting must use default Pueue")
    benchmark = json.loads(args.benchmark.read_text())
    cases = {case["id"]: case for case in benchmark["cases"]}
    report = {"schema": "partial-disassembly-report-tables-v1", "provenance": [],
              "notes": ["Reporting only: saved associations and counts, no rescoring.",
                        "Known-reference missing precision excludes unverified missing calls, reported separately.",
                        "Matched uncertain and no_match are separate; no output is never credited as absence.",
                        "Raw hypotheses are not confirmed bricks. Pose/phase/chain proxies are conditional.",
                        "Separate views and palette variants are correlated; combined/temporal modes were not measured."]}
    seen, reference_hashes, protocol_hashes = set(), {}, set()
    for argument in args.evaluation:
        version, separator, filename = argument.partition("=")
        if not separator or not version:
            parser.error("--evaluation requires VERSION=FILE")
        path = Path(filename)
        evaluation = json.loads(path.read_text())
        identity = version, evaluation["split"]
        if identity in seen:
            raise ValueError(f"Duplicate version/split: {identity}")
        seen.add(identity)
        if evaluation["benchmark_sha256"] != sha256(args.benchmark):
            raise ValueError("Scored benchmark hash differs from supplied benchmark")
        split = evaluation["split"]
        if split in reference_hashes and reference_hashes[split] != evaluation["references_sha256"]:
            raise ValueError("References differ across versions within a split")
        reference_hashes[split] = evaluation["references_sha256"]
        protocol_hashes.add(evaluation["protocol_sha256"])
        if len(protocol_hashes) != 1:
            raise ValueError("Scoring protocol differs across supplied evaluations")
        report["provenance"].append({"version": version, "split": split,
            "evaluation": str(path.resolve()), "evaluation_sha256": sha256(path),
            "references_sha256": evaluation["references_sha256"],
            "protocol_sha256": evaluation["protocol_sha256"], "benchmark_sha256": evaluation["benchmark_sha256"]})
        for name, records in report_one(version, path, evaluation, cases).items():
            report.setdefault(name, []).extend(records)
    args.output.mkdir(parents=True, exist_ok=True)
    report["reporter_sha256"] = sha256(Path(__file__))
    (args.output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for name in ("groups", "frames", "color_pairs", "controls", "transitions", "recoveries", "artifacts", "provenance"):
        write_csv(args.output / (name + ".csv"), report[name])
    print(json.dumps({"versions_splits": len(seen), "frame_rows": len(report["frames"]),
                      "summary": str(args.output / "summary.json")}))


if __name__ == "__main__":
    main()

"""Independent fixed evaluation of saved-mask dimension/seam postprocessing.

References are evaluation-only. Batch mask reads/scoring require default Pueue.
"""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

import base_evaluation as base


def read_record(path, file):
    record = json.loads(path.read_text())
    if record["image"] != file or record["prompt_id"] != "brick" or record["prompt"] != "LEGO brick":
        raise ValueError(f"Unexpected source image/prompt: {path}")
    detections = record["detections"]
    if len({d["id"] for d in detections}) != len(detections):
        raise ValueError(f"Nonunique detection IDs: {path}")
    masks = []
    for detection in detections:
        mask = cv2.imread(str(path.parent/detection["mask"]), cv2.IMREAD_GRAYSCALE)
        if mask is None or mask.shape != (720, 1280):
            raise ValueError(f"Missing/wrong-resolution mask: {path} {detection['id']}")
        masks.append(mask > 0)
    return record, masks


def outcome_map(score):
    result = {pair["detection_id"]: {"category": "matched", "reference_id": pair["reference_id"],
                                      "box_iou": pair["box_iou"]} for pair in score["matches"]}
    for category, ids in score["categories"].items():
        result.update({i: {"category": category} for i in ids})
    return result


def compare_parents(raw, final, raw_score, final_score):
    raw_outcomes, final_outcomes = outcome_map(raw_score), outcome_map(final_score)
    grouped = {}
    for child in final["detections"]:
        parent = child["parent_id"]
        grouped.setdefault(parent, []).append(child)
    raw_ids = {d["id"] for d in raw["detections"]}
    if set(grouped)-raw_ids:
        raise ValueError("Final detections refer to unknown saved raw parents")
    rows = []
    for parent in raw["detections"]:
        children = grouped.get(parent["id"], [])
        split_children = [d for d in children if d["operation"] == "split_child"]
        original = raw_outcomes[parent["id"]]
        old_refs = {original["reference_id"]} if original["category"] == "matched" else set()
        new_refs = {final_outcomes[d["id"]]["reference_id"] for d in children
                    if final_outcomes[d["id"]]["category"] == "matched"}
        rows.append({"parent_id": parent["id"], "raw_outcome": original,
                     "final_children": [{"id": d["id"], "operation": d["operation"],
                                          **final_outcomes[d["id"]]} for d in children],
                     "split_children": len(split_children),
                     "split_child_outcomes": dict(Counter(final_outcomes[d["id"]]["category"] for d in split_children)),
                     "gained_reference_ids": sorted(new_refs-old_refs), "lost_reference_ids": sorted(old_refs-new_refs),
                     "interpretation": "Per-parent attribution under independent stage matching; no credit merely for removal."})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch evaluation must run through default Pueue")
    directory = Path(__file__).parent
    protocol_bytes = (directory/"protocol.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    reference_bytes = args.reference.read_bytes()
    if hashlib.sha256(reference_bytes).hexdigest() != protocol["reference_sha256"]:
        raise ValueError("Frozen historical references changed")
    if hashlib.sha256((directory/"base_evaluation.py").read_bytes()).hexdigest() != protocol["base_evaluation_sha256"]:
        raise ValueError("Byte-identical historical scoring copy changed")
    references = {r["file"]: r for r in json.loads(reference_bytes)["images"]}
    scored, counts, audits, parent_rows = [], [], [], []
    for number in range(1, 19):
        stem, file = f"img_{number}", f"img_{number}.jpg"
        paths = {"raw": args.raw_root/stem/"raw.json",
                 "retained_only": args.processed_root/stem/"retained_only/raw.json",
                 "final": args.processed_root/stem/"final/raw.json"}
        stage_scores, records = {}, {}
        for stage, path in paths.items():
            record, masks = read_record(path, file)
            records[stage] = record
            if stage != "raw":
                for detection in record["detections"]:
                    if detection["operation"] not in {"retained", "split_child"}:
                        raise ValueError("Unrecognized processing operation")
            counts.append({"image": file, "stage": stage, "detections": len(record["detections"]),
                           "operations": dict(Counter(d.get("operation", "raw") for d in record["detections"]))})
            if file in references:
                score = base.score_boxes(record["detections"], references[file])
                score.update({"file": file, "stage": stage, "correlation_group": references[file]["correlation_group"],
                              "mask_diagnostics": base.score_masks(record["detections"], masks, references[file], score)})
                scored.append(score)
                stage_scores[stage] = score
        audits.append({"image": file, "diagnostics": json.loads((args.processed_root/stem/"diagnostics.json").read_text())})
        if file in references:
            matched_refs = {stage: {m["reference_id"] for m in score["matches"]}
                            for stage, score in stage_scores.items()}
            parent_rows.append({"image": file, "parents": compare_parents(records["raw"], records["final"],
                                                                          stage_scores["raw"], stage_scores["final"]),
                                "global_stage_reference_changes": {
                                    stage: {"gained_reference_ids": sorted(matched_refs[stage]-matched_refs["raw"]),
                                            "lost_reference_ids": sorted(matched_refs["raw"]-matched_refs[stage])}
                                    for stage in ("retained_only", "final")}})
    by_stage = {s: base.summarize([r for r in scored if r["stage"] == s]) for s in paths}
    historical = {"raw_detections": 353, "matched": 124, "missed_individual_faces": 42,
                  "merge": 26, "duplicate": 0, "lower_layer_target": 19, "ambiguous_ignored": 12,
                  "outside_roi": 1, "other_spurious_or_unresolved": 171}
    if any(by_stage["raw"][key] != value for key, value in historical.items()):
        raise ValueError("Historical baseline reproduction mismatch; do not compare a changed raw source")
    if sum(r["detections"] for r in counts if r["stage"] == "raw") != 1062:
        raise ValueError("Historical all18 raw count mismatch")
    split_counts = Counter()
    for image in parent_rows:
        for parent in image["parents"]:
            split_counts.update(parent["split_child_outcomes"])
    report = {"schema": "sam3-dimension-seam-fixed-evaluation-v1",
              "reference_sha256": protocol["reference_sha256"],
              "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "by_stage": by_stage,
              "by_stage_and_group": {s: {g: base.summarize([r for r in scored if r["stage"] == s and r["correlation_group"] == g])
                                          for g in "ABCD"} for s in paths},
              "all18_counts": counts, "annotated_observations": scored,
              "split_parent_child_outcomes": parent_rows, "split_child_outcome_totals": dict(split_counts),
              "implementation_diagnostics_unchanged": audits,
              "interpretation": "Three fixed stages of saved LEGO brick masks. Historical scorer unchanged. Filter/seam diagnostics are implementation declarations; ground truth is scoring-only. No physical top-layer/accessibility/metric pose inference."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"by_stage": by_stage, "split_child_outcome_totals": dict(split_counts)}, indent=2))


if __name__ == "__main__":
    main()

"""Frozen independent scoring of RGB ridge-chain slot declarations.

References and historical baseline scores are postprocessing-only inputs.
No new labels, perception refinement or image processing occurs here.
"""
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import base_evaluation as base


DECISIONS = ("present", "missing", "uncertain", "no_match")


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None,
            "max": max(values) if values else None}


def as_detection(slot):
    # Historical scorer's highest-score coarse-ROI diagnostic needs a scalar.
    # No confidence is invented: an absent scalar is zero and that diagnostic
    # is omitted from this experiment's reporting. Primary matching ignores it.
    return {"id": slot["id"], "box_xyxy": slot["box_xyxy"],
            "score": float(slot.get("score", 0.0))}


def flatten(record):
    slots, chain_for_slot, boundary_for_slot = [], {}, {}
    for chain in record["chains"]:
        boundaries = {b["id"]: b for b in chain["boundaries"]}
        for slot in chain["slots"]:
            if slot["id"] in chain_for_slot:
                raise ValueError("Slot IDs must be unique across an image")
            if slot["decision"] not in DECISIONS[:3]:
                raise ValueError("Unexpected slot decision")
            slots.append(slot)
            chain_for_slot[slot["id"]] = chain["id"]
            boundary_for_slot[slot["id"]] = [boundaries[b] for b in slot["boundary_ids"]]
    return slots, chain_for_slot, boundary_for_slot


def tri_state(slots, reference, missing):
    """Joint one-to-one slot matching prevents positive/absence slot reuse."""
    positive = [r for r in reference["instances"] if r["role"] == "exposed_top"]
    targets = positive + missing
    boxes = [s["box_xyxy"] for s in slots]
    truth_boxes = [base.envelope(r["polygon"]) for r in targets]
    present_boxes = truth_boxes[:len(positive)]
    merged = set()
    for p, box in enumerate(boxes):
        covered = [r for r, ref in enumerate(present_boxes)
                   if base.intersection(box, ref)/max(base.area(ref), 1e-12) >= .5
                   and box[0] <= (ref[0]+ref[2])/2 <= box[2]
                   and box[1] <= (ref[1]+ref[3])/2 <= box[3]]
        if len(covered) >= 2:
            merged.add(p)
    eligible = [p for p in range(len(slots)) if p not in merged]
    matches = []
    if eligible and targets:
        matrix = np.array([[base.iou(boxes[p], b) for b in truth_boxes] for p in eligible])
        matches = [(eligible[p], r, float(matrix[p, r])) for p, r in base.assignment(-1000*(matrix >= .5)-matrix)
                   if matrix[p, r] >= .5]
    by_ref = {r: p for p, r, _ in matches}
    positive_counts, missing_counts = Counter(), Counter()
    for r in range(len(positive)):
        positive_counts[slots[by_ref[r]]["decision"] if r in by_ref else "no_match"] += 1
    for r in range(len(positive), len(targets)):
        missing_counts[slots[by_ref[r]]["decision"] if r in by_ref else "no_match"] += 1
    matched_slots = {p for p, _, _ in matches}
    return {"positive_references": len(positive), "missing_references": len(missing),
            "positive_decisions": {k: positive_counts[k] for k in DECISIONS},
            "missing_decisions": {k: missing_counts[k] for k in DECISIONS},
            "merged_slots_ineligible": [slots[p]["id"] for p in sorted(merged)],
            "unverified_missing_claims": [s["id"] for p, s in enumerate(slots)
                                          if s["decision"] == "missing" and p not in matched_slots],
            "matches": [{"slot_id": slots[p]["id"],
                         "reference_id": targets[r]["id"] if r < len(positive) else targets[r]["reference_id"],
                         "reference_kind": "positive" if r < len(positive) else "missing",
                         "decision": slots[p]["decision"], "iou": score} for p, r, score in matches]}


def end_edges(polygon):
    points = np.asarray(polygon, float)
    if points.shape != (4, 2):
        raise ValueError("Boundary proxy requires four-corner slot polygons")
    lengths = [float(np.linalg.norm(points[(i+1) % 4]-points[i])) for i in range(4)]
    indices = sorted(range(4), key=lambda i: lengths[i])[:2]
    return [np.array([points[i], points[(i+1) % 4]]) for i in indices]


def midpoint(line):
    return np.asarray(line, float).mean(axis=0)


def angle_error(a, b):
    va, vb = np.asarray(a[1])-a[0], np.asarray(b[1])-b[0]
    return float(np.degrees(np.arccos(np.clip(abs(np.dot(va, vb))/max(np.linalg.norm(va)*np.linalg.norm(vb), 1e-12), 0, 1))))


def boundary_phase_proxy(slots, chains, boundaries, reference, state_score):
    by_id = {s["id"]: s for s in slots}
    refs = {r["id"]: r for r in reference["instances"] if r["role"] == "exposed_top"}
    strip_ids = sorted({i.split("r")[0] for i in refs})
    strips = {s: set() for s in strip_ids}
    chain_strips = defaultdict(set)
    records, ends = [], []
    for match in state_score["matches"]:
        if match["reference_kind"] != "positive":
            continue
        slot = by_id[match["slot_id"]]
        ref = refs[match["reference_id"]]
        truth_ends = end_edges(ref["polygon"])
        truth_mid = np.array([midpoint(e) for e in truth_ends])
        axis = truth_mid[1]-truth_mid[0]
        length = float(np.linalg.norm(axis))
        axis /= max(length, 1e-12)
        center_error = np.asarray(slot["polygon"], float).mean(axis=0)-np.asarray(ref["polygon"], float).mean(axis=0)
        records.append({"slot_id": slot["id"], "reference_id": ref["id"], "decision": slot["decision"],
                        "center_long_axis_offset_px": abs(float(center_error@axis)),
                        "phase_offset_reference_lengths": abs(float(center_error@axis))/max(length, 1e-12)})
        predicted = boundaries[slot["id"]]
        if len(predicted) != 2:
            raise ValueError("Each slot must declare its two boundary IDs")
        matrix = np.array([[np.linalg.norm(midpoint(p["line_xy"])-m) for m in truth_mid] for p in predicted])
        for p, t in base.assignment(matrix):
            line = predicted[p]
            if line["provenance"] not in ("observed", "inferred"):
                raise ValueError("Unrecognized boundary provenance")
            delta = midpoint(line["line_xy"])-truth_mid[t]
            ends.append({"slot_id": slot["id"], "reference_id": ref["id"], "decision": slot["decision"],
                         "provenance": line["provenance"], "midpoint_error_px": float(np.linalg.norm(delta)),
                         "long_axis_offset_px": abs(float(delta@axis)),
                         "angle_error_deg": angle_error(np.array(line["line_xy"]), truth_ends[t])})
        strip = ref["id"].split("r")[0]
        strips[strip].add(chains[slot["id"]])
        chain_strips[chains[slot["id"]]].add(strip)
    return {"matched_slot_phase": records, "matched_face_ends": ends,
            "reference_strip_chain_ids": {k: sorted(v) for k, v in strips.items()},
            "uncovered_reference_strips": [k for k, v in strips.items() if not v],
            "fragmented_reference_strips": [k for k, v in strips.items() if len(v) > 1],
            "predicted_chain_reference_strips": {k: sorted(v) for k, v in chain_strips.items()},
            "mixed_reference_strip_chains": [k for k, v in chain_strips.items() if len(v) > 1],
            "interpretation": "Conditional image-plane alignment to existing face polygons; repeated shared ends counted per face, not unique physical seams. Provenance is an algorithm declaration, not independent observed-seam truth."}


def summarize_primary(rows):
    keys = ["positive_references", "ambiguous_references_excluded", "lower_fragments", "raw_detections", "matched",
            "missed_individual_faces", "merge", "duplicate", "lower_layer_target", "ambiguous_ignored", "other_spurious_or_unresolved", "outside_roi"]
    result = {k: sum(r[k] for r in rows) for k in keys}
    denominator = result["raw_detections"]-result["outside_roi"]-result["ambiguous_ignored"]
    result.update({"annotated_images": len(rows), "individual_face_recall": result["matched"]/max(result["positive_references"], 1),
                   "scored_roi_instance_precision": result["matched"]/denominator if denominator else None})
    return result


def summarize_state(rows):
    p = {k: sum(r["positive_decisions"][k] for r in rows) for k in DECISIONS}
    m = {k: sum(r["missing_decisions"][k] for r in rows) for k in DECISIONS}
    pn, mn = sum(p.values()), sum(m.values())
    missing_denominator = m["missing"]+p["missing"]
    return {"positive_decisions": p, "missing_decisions": m,
            "positive_decisive_coverage": (p["present"]+p["missing"])/pn if pn else None,
            "positive_correct_present_coverage": p["present"]/pn if pn else None,
            "absence_decisive_coverage": (m["present"]+m["missing"])/mn if mn else None,
            "absence_correct_missing_coverage": m["missing"]/mn if mn else None,
            "known_reference_missing_precision": m["missing"]/missing_denominator if missing_denominator else None,
            "unverified_missing_claims": sum(len(r["unverified_missing_claims"]) for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--missing-reference", type=Path, required=True)
    parser.add_argument("--sam-evaluation", type=Path, required=True)
    parser.add_argument("--size-evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch evaluation must run through default Pueue")
    protocol_path = Path(__file__).with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text())
    for key, path in [("reference", args.reference), ("missing_reference", args.missing_reference),
                      ("sam_evaluation", args.sam_evaluation), ("size_evaluation", args.size_evaluation),
                      ("base_evaluation", Path(__file__).with_name("base_evaluation.py"))]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != protocol[key+"_sha256"]:
            raise ValueError(f"Frozen {key} hash mismatch")
    references = {r["file"]: r for r in json.loads(args.reference.read_text())["images"]}
    absence = json.loads(args.missing_reference.read_text())["instances"]
    sam = json.loads(args.sam_evaluation.read_text())
    size = json.loads(args.size_evaluation.read_text())
    baselines = {"sam_raw": [r for r in sam["annotated_observations"] if r["prompt_id"] == "brick"],
                 "dimensions_only": [r for r in size["annotated_observations"] if r["stage"] == "retained_only"],
                 "dimensions_split": [r for r in size["annotated_observations"] if r["stage"] == "final"]}
    if [sum(r["matched"] for r in rows) for rows in baselines.values()] != [124, 113, 117]:
        raise ValueError("Historical baseline identity mismatch")
    all18, scored, state_rows, proxies, changes = [], [], [], [], []
    for number in range(1, 19):
        file, stem = f"img_{number}.jpg", f"img_{number}"
        record = json.loads((args.predictions/stem/"chains.json").read_text())
        if record["image"] != file or (record["width"], record["height"]) != (1280, 720):
            raise ValueError("Wrong image or resolution")
        slots, chains, boundaries = flatten(record)
        all18.append({"file": file, "chains": len(record["chains"]), "slots": len(slots),
                      "decisions": dict(Counter(s["decision"] for s in slots)),
                      "phase_status": dict(Counter(c["phase"]["status"] for c in record["chains"])),
                      "boundary_provenance": dict(Counter(b["provenance"] for c in record["chains"] for b in c["boundaries"]))})
        if file not in references:
            continue
        reference = references[file]
        present = [as_detection(s) for s in slots if s["decision"] == "present"]
        primary = base.score_boxes(present, reference)
        primary.pop("whole_stack_coarse", None)
        primary.update({"file": file, "correlation_group": reference["correlation_group"]})
        scored.append(primary)
        state = tri_state(slots, reference, [r for r in absence if r["file"] == file])
        state.update({"file": file, "correlation_group": reference["correlation_group"]})
        state_rows.append(state)
        proxy = boundary_phase_proxy(slots, chains, boundaries, reference, state)
        proxies.append({"file": file, **proxy})
        current = {m["reference_id"] for m in primary["matches"]}
        changes.append({"file": file, "baselines": {name: {
            "recovered_reference_ids": sorted(current-{m["reference_id"] for r in rows if r["file"] == file for m in r["matches"]}),
            "lost_reference_ids": sorted({m["reference_id"] for r in rows if r["file"] == file for m in r["matches"]}-current)}
            for name, rows in baselines.items()}})
    boundary_rows = [b for p in proxies for b in p["matched_face_ends"]]
    phase_rows = [s for p in proxies for s in p["matched_slot_phase"]]
    report = {"schema": "rgb-ridge-chain-fixed-evaluation-v1", "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
              "all18_counts": all18, "primary_present": summarize_primary(scored),
              "historical_baseline_absence": {name: {"missing_calls": 0, "correct_absence_calls": 0,
                  "interpretation": "Only present detections; absent output is not a missing declaration."} for name in baselines},
              "three_way_slots": summarize_state(state_rows), "annotated_present_observations": scored,
              "annotated_three_way_observations": state_rows, "global_reference_changes": changes,
              "conditional_boundary_phase_proxies": proxies,
              "proxy_summary": {"slot_phase_reference_lengths": stats([r["phase_offset_reference_lengths"] for r in phase_rows]),
                                "boundary_by_provenance": {p: {key: stats([r[key] for r in boundary_rows if r["provenance"] == p])
                                    for key in ("midpoint_error_px", "long_axis_offset_px", "angle_error_deg")} for p in ("observed", "inferred")}},
              "by_group": {g: {"primary_present": summarize_primary([r for r in scored if r["correlation_group"] == g]),
                                "three_way_slots": summarize_state([r for r in state_rows if r["correlation_group"] == g])} for g in "ABCD"}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"primary_present": report["primary_present"], "three_way_slots": report["three_way_slots"]}, indent=2))


if __name__ == "__main__":
    main()

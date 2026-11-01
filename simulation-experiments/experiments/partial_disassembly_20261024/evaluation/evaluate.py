"""Frozen partial-disassembly scoring, including evaluation-only references."""
import argparse
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np

import base_evaluation as base
from references import build_reference


DECISIONS = ("present", "missing", "uncertain", "no_match")


def scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values,90)) if values else None, "max": max(values) if values else None}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=scalar).encode()).hexdigest()


def height_consistent(candidate, reference):
    z = candidate.get("surface_height_world_m")
    return bool(z is not None and np.isfinite(z) and min(abs(z-reference["body_top_world_m"]),abs(z-reference["stud_top_world_m"])) <= .003)


def height_layer(candidate, reference):
    z = candidate.get("surface_height_world_m")
    if z is None or not np.isfinite(z):
        return None
    distance, layer = min((min(abs(z-h["body_top_world_m"]),abs(z-h["stud_top_world_m"])),int(layer))
                          for layer,h in reference["layer_heights"].items())
    return layer if distance <= .003 else None


def candidate_box(candidate):
    return candidate.get("box_xyxy") or base.envelope(candidate["polygon"])


def score_stage(candidates, reference):
    detections = [{"id":c["id"],"box_xyxy":candidate_box(c),"score":0.} for c in candidates]
    score = base.score_boxes(detections, reference)
    score.pop("whole_stack_coarse",None)
    by_id = {c["id"]:c for c in candidates}
    refs = {r["id"]:r for r in reference["instances"]}
    correct, pose = [], []
    for match in score["matches"]:
        candidate, truth = by_id[match["detection_id"]],refs[match["reference_id"]]
        if height_consistent(candidate,reference):
            correct.append(truth["id"])
        xy,yaw = candidate.get("center_world_xy_m"),candidate.get("yaw_world_rad")
        if xy is not None and yaw is not None and np.asarray(xy).shape==(2,) and np.isfinite(xy).all() and np.isfinite(yaw):
            delta = abs(float(yaw)-truth["yaw_world_rad"])%math.pi
            pose.append({"candidate_id":candidate["id"],"reference_id":truth["id"],
                "xy_error_mm":float(np.linalg.norm(np.asarray(xy)-truth["center_world_xy_m"])*1000),
                "shared_yaw_error_deg":math.degrees(min(delta,math.pi-delta))})
    lower_details=[]
    for candidate_id in score["categories"]["lower_layer_target"]:
        box=candidate_box(by_id[candidate_id]);center=[(box[0]+box[2])/2,(box[1]+box[3])/2]
        hits=[r for r in reference["instances"] if r["role"]=="visible_lower" and base.inside(center,r["polygon"])]
        lower_details.append({"candidate_id":candidate_id,"lower_reference_ids":[r["id"] for r in hits],
                              "includes_vertically_uncovered_lower":any(r["vertical_projection_uncovered"] for r in hits)})
    score.update(height_consistent_reference_ids=sorted(correct),matched_plane_errors=pose,
        height_inconsistent_ids=sorted(i for i in by_id if not height_consistent(by_id[i],reference)),
        selected_lower_layer_ids=sorted(i for i in by_id if height_layer(by_id[i],reference) is not None and height_layer(by_id[i],reference)<reference["current_layer"]),
        lower_footprint_details=lower_details)
    return score


def joint_decisions(candidates, reference):
    positives = [r for r in reference["instances"] if r["role"]=="exposed_top"]
    targets = positives+reference["missing_references"]
    boxes = [candidate_box(c) for c in candidates]
    gt = [base.envelope(r["polygon"]) for r in targets]
    merged = set()
    for p,box in enumerate(boxes):
        covered=[r for r,g in enumerate(gt[:len(positives)]) if base.intersection(box,g)/max(base.area(g),1e-12)>=.5
                 and box[0]<=(g[0]+g[2])/2<=box[2] and box[1]<=(g[1]+g[3])/2<=box[3]]
        if len(covered)>=2:merged.add(p)
    eligible=[i for i in range(len(candidates)) if i not in merged]
    matches=[]
    if eligible and targets:
        matrix=np.array([[base.iou(boxes[p],g) for g in gt] for p in eligible])
        matches=[(eligible[p],r,float(matrix[p,r])) for p,r in base.assignment(-1000*(matrix>=.5)-matrix) if matrix[p,r]>=.5]
    by_ref={r:p for p,r,_ in matches};matched={p for p,_,_ in matches}
    counts=[]
    for subset in (range(len(positives)),range(len(positives),len(targets))):
        value=Counter(candidates[by_ref[r]]["decision"] if r in by_ref else "no_match" for r in subset)
        counts.append({d:value[d] for d in DECISIONS})
    rows=[]
    for p,r,iou in matches:
        c,t=candidates[p],targets[r]
        row={"candidate_id":c["id"],"reference_id":t["id"],"reference_kind":"positive" if r<len(positives) else "missing",
             "decision":c["decision"],"iou":iou,"height_consistent":height_consistent(c,reference),"ridge_key":t["ridge_key"],"long_index":t["long_index"],"parent_ridge_id":c.get("parent_ridge_id")}
        xy=c.get("center_world_xy_m")
        if xy is not None and np.asarray(xy).shape==(2,) and np.isfinite(xy).all():
            axis=np.array([math.cos(t["yaw_world_rad"]),math.sin(t["yaw_world_rad"])])
            longitudinal=float((np.asarray(xy)-t["center_world_xy_m"])@axis)
            row.update(longitudinal_error_mm=abs(longitudinal)*1000,phase_error_mm=abs((longitudinal+.016)%.032-.016)*1000)
        rows.append(row)
    known_missing=[r for r in rows if r["decision"]=="missing"]
    correct_missing=[r for r in known_missing if r["reference_kind"]=="missing" and r["height_consistent"]]
    unverified=[]
    for p,c in enumerate(candidates):
        if c["decision"]!="missing" or p in matched:continue
        overlaps=[(base.iou(boxes[p],base.envelope(t["polygon"])),t) for t in reference["unknown_removed"]]
        best=max(overlaps,key=lambda x:x[0],default=None)
        unverified.append({"candidate_id":c["id"],"classification":best[1]["classification"] if best and best[0]>=.5 else "no_scorable_current_layer_reference",
                           "reference_id":best[1]["id"] if best and best[0]>=.5 else None})
    return {"positive_decisions":counts[0],"missing_decisions":counts[1],"matches":rows,
            "known_missing_calls":len(known_missing),"correct_missing":len(correct_missing),
            "wrong_missing_on_present":sum(r["reference_kind"]=="positive" for r in known_missing),
            "wrong_height_missing_on_absence":sum(r["reference_kind"]=="missing" and not r["height_consistent"] for r in known_missing),
            "present_on_absence_reference":[r for r in rows if r["reference_kind"]=="missing" and r["decision"]=="present"],
            "unverified_missing":unverified}


def score_frame(record, reference):
    candidates=record["candidates"]
    if len({c["id"] for c in candidates})!=len(candidates) or any(c["decision"] not in DECISIONS[:3] for c in candidates):
        raise ValueError("Candidate IDs/decision contract invalid")
    raw=score_stage(candidates,reference)
    present=score_stage([c for c in candidates if c["decision"]=="present"],reference)
    joint=joint_decisions(candidates,reference)
    coverage={r["ridge_key"]:set() for r in reference["instances"] if r["role"]=="exposed_top"}
    for row in joint["matches"]:
        if row["reference_kind"]=="positive" and row["parent_ridge_id"] is not None:coverage[row["ridge_key"]].add(row["parent_ridge_id"])
    parent_ridges={}
    for ridge,parents in coverage.items():
        for parent in parents:parent_ridges.setdefault(parent,set()).add(ridge)
    chain_stats={"reference_ridges":len(coverage),"uncovered_reference_ridges":[k for k,v in coverage.items() if not v],
        "split_reference_ridges":[k for k,v in coverage.items() if len(v)>1],
        "mixed_reference_ridge_parentchains":[k for k,v in parent_ridges.items() if len(v)>1],
        "interpretation":"Conditional on positive slot matches, not a full original-chain count or an automatic error for a valid split component."}
    matched={r["reference_id"]:r for r in joint["matches"]}
    gaps=[{"removed_reference_id":r["id"],"classification":r.get("classification"),
           "left_anchor":r["left_anchor"],"right_anchor":r["right_anchor"],
           "left_match":matched.get(r["left_anchor"]),"right_match":matched.get(r["right_anchor"]),
           "slot_match":matched.get(r["id"])}
          for r in reference["missing_references"]+reference["unknown_removed"] if r["left_anchor"] and r["right_anchor"]]
    depth=record.get("depth_direction",{})
    angle=depth.get("direction_world_deg_mod180")
    actual=math.degrees(reference["current_yaw_world_rad"])%180
    band_status=record.get("direction_status",depth.get("status"))
    band_correct=height_consistent({"surface_height_world_m":depth.get("estimated_surface_height_world_m")},reference)
    return {"raw_geometry":raw,"present":present,"joint":joint,
            "counts":dict(Counter(c["decision"] for c in candidates)),
            "task_correct_reference_ids":present["height_consistent_reference_ids"],
            "reference_ridge_parent_ids":{k:sorted(v) for k,v in coverage.items()},
            "chain_stats":chain_stats,
            "gap_anchor_diagnostics":gaps,
            "band_diagnostic":{"status":band_status,"surface_height_world_m":depth.get("estimated_surface_height_world_m"),
                "height_consistent":band_correct,
                "classification":"unsupported" if band_status!="supported" else "correct_current_layer" if band_correct else "supported_wrong_layer_or_height",
                "estimated_layer_by_height":height_layer({"surface_height_world_m":depth.get("estimated_surface_height_world_m")},reference),
                "yaw_error_deg":min(abs(angle-actual)%180,180-abs(angle-actual)%180) if angle is not None else None},
            "reason_flags_nonexclusive":dict(Counter(flag for c in candidates for flag in c.get("reason_flags",[])))}


def summarize(rows):
    result={}
    for stage in ("raw_geometry","present"):
        keys=("positive_references","raw_detections","matched","missed_individual_faces","merge","duplicate","lower_layer_target","ambiguous_ignored","other_spurious_or_unresolved","outside_roi")
        total={k:sum(r[stage][k] for r in rows) for k in keys}
        denominator=total["raw_detections"]-total["outside_roi"]-total["ambiguous_ignored"]
        task=sum(len(r[stage]["height_consistent_reference_ids"]) for r in rows)
        total.update(image_precision=total["matched"]/denominator if denominator else None,image_recall=total["matched"]/total["positive_references"] if total["positive_references"] else None,
            height_consistent_matches=task,height_consistent_precision=task/denominator if denominator else None,height_consistent_recall=task/total["positive_references"] if total["positive_references"] else None,
            selected_lower_layer=sum(len(r[stage]["selected_lower_layer_ids"]) for r in rows),
            height_inconsistent_claims=sum(len(r[stage]["height_inconsistent_ids"]) for r in rows),
            lower_flags_with_uncovered_projection=sum(x["includes_vertically_uncovered_lower"] for r in rows for x in r[stage]["lower_footprint_details"]),
            xy_error_mm=stats([p["xy_error_mm"] for r in rows for p in r[stage]["matched_plane_errors"]]),
            shared_yaw_error_deg=stats([p["shared_yaw_error_deg"] for r in rows for p in r[stage]["matched_plane_errors"]]))
        result[stage]=total
    for kind in ("positive_decisions","missing_decisions"):
        result[kind]={d:sum(r["joint"][kind][d] for r in rows) for d in DECISIONS}
    known=sum(r["joint"]["known_missing_calls"] for r in rows);correct=sum(r["joint"]["correct_missing"] for r in rows)
    positive_n=sum(result["positive_decisions"].values());missing_n=sum(result["missing_decisions"].values())
    result.update(known_missing_calls=known,correct_missing=correct,known_missing_precision=correct/known if known else None,
        observable_missing_references=missing_n,correct_missing_recall=correct/missing_n if missing_n else None,
        positive_decisive_coverage=(result["positive_decisions"]["present"]+result["positive_decisions"]["missing"])/positive_n if positive_n else None,
        missing_decisive_coverage=(result["missing_decisions"]["present"]+result["missing_decisions"]["missing"])/missing_n if missing_n else None,
        wrong_missing_on_present=sum(r["joint"]["wrong_missing_on_present"] for r in rows),
        wrong_height_missing_on_absence=sum(r["joint"]["wrong_height_missing_on_absence"] for r in rows),
        present_on_absence_references=sum(len(r["joint"]["present_on_absence_reference"]) for r in rows),
        unverified_missing_calls=sum(len(r["joint"]["unverified_missing"]) for r in rows),
        phase_error_mm=stats([m["phase_error_mm"] for r in rows for m in r["joint"]["matches"] if "phase_error_mm" in m]))
    result["band_frames"]={key:sum(r["band_diagnostic"]["classification"]==key for r in rows)
        for key in ("correct_current_layer","unsupported","supported_wrong_layer_or_height")}
    result["chain_stats"]={"reference_ridges":sum(r["chain_stats"]["reference_ridges"] for r in rows),
        **{key:sum(len(r["chain_stats"][key]) for r in rows)
           for key in ("uncovered_reference_ridges","split_reference_ridges","mixed_reference_ridge_parentchains")}}
    return result


def path_from_frame(value, frames_path):
    p=Path(value)
    return p if p.is_absolute() else frames_path.parent/p


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("captures","predictions","frames","benchmark","geometry","protocol","output"):p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--split",choices=("development","reserved"),required=True)
    p.add_argument("--previous-evaluation",type=Path)
    args=p.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB")!="1":raise RuntimeError("Reference building and scoring must use default Pueue")
    protocol=json.loads(args.protocol.read_text());benchmark=json.loads(args.benchmark.read_text());geometry=json.loads(args.geometry.read_text())
    if hashlib.sha256(args.benchmark.read_bytes()).hexdigest()!=protocol["benchmark_sha256"]:raise ValueError("Frozen benchmark changed")
    if hashlib.sha256(args.geometry.read_bytes()).hexdigest()!=benchmark["frozen_sources_sha256"][benchmark["geometry_source"]]:raise ValueError("Frozen design geometry changed")
    cases={c["id"]:c for c in benchmark["cases"]};controls={c["id"]:c for c in benchmark["development_controls"]}
    frames=json.loads(args.frames.read_text())
    if len({f["id"] for f in frames})!=len(frames):raise ValueError("Frame IDs not unique")
    selected=[f for f in frames if cases[f["case_id"]]["split"]==args.split]
    expected={(c["id"],view,None) for c in cases.values() if c["split"]==args.split for view in benchmark["views"]}
    if args.split=="development":expected|={(c["source"].split("/")[0],c["source"].split("/")[1],c["id"]) for c in controls.values()}
    if len(selected)!=len(expected) or {(f["case_id"],f["view"],f["control_id"]) for f in selected}!=expected:raise ValueError("Split frame manifest incomplete or unexpected")
    observations=[];control_rows=[];references={};camera_poses={}
    for frame in selected:
        case=cases[frame["case_id"]];control=controls.get(frame["control_id"])
        input_depth=np.load(path_from_frame(frame["depth_input_path"],args.frames),allow_pickle=False)
        reference=build_reference(args.captures/case["id"],frame["view"],geometry,case,input_depth)
        camera_values={"eye":np.array(reference["actual_camera_eye_world_m"]),
                       "rotation":np.array(reference["actual_camera_rotation_world_to_optical"]),
                       "intrinsics":np.array(reference["actual_camera_intrinsics"])}
        if frame["view"] in camera_poses and any(np.max(np.abs(value-camera_poses[frame["view"]][key]))>1e-6 for key,value in camera_values.items()):
            raise ValueError("Camera position/rotation/intrinsics changed between cases")
        camera_poses[frame["view"]]=camera_values
        references[frame["id"]]=reference
        record=json.loads((args.predictions/frame["id"]/"detections.json").read_text())
        metadata={"frame_id":frame["id"],"case_id":case["id"],"view":frame["view"],"control_id":frame["control_id"],"reference_sha256":canonical_hash(reference),
            "current_layer":reference["current_layer"],"visibility_counts":reference["visibility_counts"],"observable_missing_references":len(reference["missing_references"]),
            "unknown_removed_counts":dict(Counter(r["classification"] for r in reference["unknown_removed"]))}
        if control and control["operation"] in ("all_depth_NaN","flat_world_plane"):
            confidence=[c for c in record["candidates"] if c["decision"] in ("present","missing")]
            control_rows.append({**metadata,"false_supported_claims":len(confidence),"decisions":dict(Counter(c["decision"] for c in confidence))})
        else:
            observations.append({**metadata,**score_frame(record,reference)})
    primary=[r for r in observations if r["control_id"] is None];patch=[r for r in observations if r["control_id"] is not None]
    report={"schema":"partial-disassembly-fixed-evaluation-v1","split":args.split,"protocol_sha256":hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        "benchmark_sha256":protocol["benchmark_sha256"],"summary":summarize(primary),"observations":observations,"sensor_controls":control_rows,
        "no_return_patch":summarize(patch) if patch else None,"references_sha256":canonical_hash(references)}
    def observation_key(row):
        return json.dumps([row["case_id"],row["view"],row["control_id"]],separators=(",",":"))
    baseline_sets={observation_key(r):r["task_correct_reference_ids"] for r in observations}
    if args.previous_evaluation:
        previous=json.loads(args.previous_evaluation.read_text())
        if previous["split"]!=args.split or previous["references_sha256"]!=report["references_sha256"]:raise ValueError("Previous evaluation references/split differ")
        prior={(r["case_id"],r["view"],r["control_id"]):r for r in previous["observations"]}
        baseline_sets=previous.get("baseline_task_correct_sets",{observation_key(r):r["task_correct_reference_ids"] for r in previous["observations"]})
        report["previous_comparison"]=[{"case_id":r["case_id"],"view":r["view"],"control_id":r["control_id"],
            "recovered_reference_ids":sorted(set(r["task_correct_reference_ids"])-set(prior[r["case_id"],r["view"],r["control_id"]]["task_correct_reference_ids"])),
            "lost_reference_ids":sorted(set(prior[r["case_id"],r["view"],r["control_id"]]["task_correct_reference_ids"])-set(r["task_correct_reference_ids"]))} for r in observations]
    report["baseline_task_correct_sets"]=baseline_sets
    report["baseline_comparison"]=[{"case_id":r["case_id"],"view":r["view"],"control_id":r["control_id"],
        "recovered_reference_ids":sorted(set(r["task_correct_reference_ids"])-set(baseline_sets[observation_key(r)])),
        "lost_reference_ids":sorted(set(baseline_sets[observation_key(r)])-set(r["task_correct_reference_ids"]))} for r in observations]
    by_case_view={(r["case_id"],r["view"]):r for r in primary}
    transitions=[]
    for row in primary:
        palette=cases[row["case_id"]]["palette"];source={"mixed":"I_mix","single_tan":"I_tan"}.get(palette)
        before=by_case_view.get((source,row["view"]))
        if before is None or row["case_id"]==source:continue
        old_ref=references[before["frame_id"]];new_ref=references[row["frame_id"]]
        shared={r["id"] for r in old_ref["instances"] if r["role"]=="exposed_top"}&{r["id"] for r in new_ref["instances"] if r["role"]=="exposed_top"}
        old_confirmed=set(before["task_correct_reference_ids"])&shared;new_confirmed=set(row["task_correct_reference_ids"])&shared
        transitions.append({"intact_case":source,"case_id":row["case_id"],"view":row["view"],"shared_visible_target_ids":sorted(shared),
            "recovered_survivor_confirmations":sorted(new_confirmed-old_confirmed),"lost_survivor_confirmations":sorted(old_confirmed-new_confirmed),
            "physical_target_layer_from":before["current_layer"],"physical_target_layer_to":row["current_layer"],
            "interpretation":"Paired stateless observations, not temporal tracking; missing-call correctness is scored separately."})
    report["state_pair_transitions"]=transitions
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"references.json").write_text(json.dumps(references,indent=2,sort_keys=True,default=scalar)+"\n")
    (args.output/"evaluation.json").write_text(json.dumps(report,indent=2,default=scalar)+"\n")
    print(json.dumps({"split":args.split,"summary":report["summary"],"sensor_controls":control_rows},indent=2,default=scalar))


if __name__=="__main__":main()

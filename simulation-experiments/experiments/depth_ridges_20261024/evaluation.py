"""Minimal independent highest-layer direction evaluation; no depth processing."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np


VIEWS = ("top", "near_top_x", "near_top_y", "oblique_front", "oblique_side")
CONDITIONS = ("real", "invalid", "flat_plane")


def angle_error(estimate, reference):
    delta = abs(float(estimate)-float(reference)) % 180
    return min(delta, 180-delta)


def stats(values):
    return {"count": len(values), "median": float(np.median(values)) if values else None,
            "max": max(values) if values else None}


def scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def truth_reference(directory, protocol):
    for filename, expected in protocol["truth_sha256"].items():
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen truth changed: {filename}")
    manifest = json.loads((directory/"manifest.json").read_text())
    if manifest["brick_count"] != 300:
        raise ValueError("Expected corrected300-brick source scene")
    state = np.load(directory/"frozen_physics_state.npy")[-300*13:].reshape(300, 13).astype(float)
    if not np.isfinite(state).all():
        raise ValueError("Invalid saved brick states")
    highest = state[state[:, 2] >= state[:, 2].max()-2e-6]
    if len(highest) != 30:
        raise ValueError("Expected30 actual roots in highest visible layer")
    q = highest[:, 3:7]
    q /= np.linalg.norm(q, axis=1)[:, None]
    w, x, y, z = q.T
    yaw = np.arctan2(2*(w*z+x*y), 1-2*(y*y+z*z))
    mean_yaw = math.atan2(float(np.sin(2*yaw).mean()), float(np.cos(2*yaw).mean()))/2
    angle = math.degrees(mean_yaw) % 180
    dispersion = max(angle_error(math.degrees(a), angle) for a in yaw)
    if dispersion > .01:
        raise ValueError("Actual highest layer is not one parallel-ridge direction")
    normal_z = 1-2*(x*x+y*y)
    body_top = highest[:, 2]+.0096*normal_z
    stud_top = highest[:, 2]+.0113*normal_z
    return {"frame": "world_xy", "direction_deg_mod180": angle,
            "highest_layer_bricks": len(highest), "direction_spread_deg": dispersion,
            "body_top_height_world_m": float(np.median(body_top)),
            "stud_top_height_world_m": float(np.median(stud_top)),
            "body_top_height_range_m": [float(body_top.min()), float(body_top.max())],
            "stud_top_height_range_m": [float(stud_top.min()), float(stud_top.max())]}


def score_record(record, reference, control=False):
    if record["frame"] != "world_xy" or record["status"] not in ("supported", "uncertain"):
        raise ValueError("Direction frame/status contract changed")
    angle = record["direction_world_deg_mod180"]
    if angle is not None and not np.isfinite(angle):
        raise ValueError("Invalid direction estimate")
    if record["status"] == "supported" and angle is None:
        raise ValueError("Supported result must supply a direction")
    band = record.get("height_band_world_m")
    if band is not None and (len(band) != 2 or not np.isfinite(band).all() or band[0] > band[1]):
        raise ValueError("Invalid world-height band")
    height = record.get("estimated_surface_height_world_m")
    if height is not None and not np.isfinite(height):
        raise ValueError("Invalid surface height")
    row = {"view": record["view"], "condition": record["condition"], "status": record["status"],
           "direction_world_deg_mod180": angle, "height_band_world_m": band,
           "estimated_surface_height_world_m": height, "reasons": record.get("reasons", []),
           "support": record.get("support", {})}
    if control:
        row["false_supported_direction"] = record["status"] == "supported"
        row["interpretation"] = "No-ridge control; no physical absence or pose metric."
    else:
        row["angular_error_deg_mod180"] = angle_error(angle, reference["direction_deg_mod180"]) if angle is not None else None
        row["body_top_in_candidate_band"] = bool(band[0] <= reference["body_top_height_world_m"] <= band[1]) if band is not None else None
        row["stud_top_in_candidate_band"] = bool(band[0] <= reference["stud_top_height_world_m"] <= band[1]) if band is not None else None
        row["surface_minus_body_top_mm"] = (height-reference["body_top_height_world_m"])*1000 if height is not None else None
        row["surface_minus_stud_top_mm"] = (height-reference["stud_top_height_world_m"])*1000 if height is not None else None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Batch scoring must run in default Pueue")
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    reference = truth_reference(args.truth, protocol)
    rows = []
    for condition in CONDITIONS:
        for view in VIEWS:
            record = json.loads((args.predictions/condition/view/"direction.json").read_text())
            if record["view"] != view or record["condition"] != condition:
                raise ValueError("Condition/view mismatch")
            rows.append(score_record(record, reference, control=condition != "real"))
    real = [r for r in rows if r["condition"] == "real"]
    report = {"schema": "depth-ridge-direction-fixed-evaluation-v1",
              "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "reference": reference, "observations": rows,
              "real_summary": {"views": len(real), "supported": sum(r["status"] == "supported" for r in real),
                  "uncertain": sum(r["status"] == "uncertain" for r in real),
                  "no_angle": sum(r["direction_world_deg_mod180"] is None for r in real),
                  "all_finite_angle_errors_deg": stats([r["angular_error_deg_mod180"] for r in real if r["angular_error_deg_mod180"] is not None]),
                  "supported_angle_errors_deg": stats([r["angular_error_deg_mod180"] for r in real if r["status"] == "supported"])},
              "controls": {condition: {"cases": 5, "false_supported_directions": sum(r["false_supported_direction"] for r in rows if r["condition"] == condition)}
                           for condition in CONDITIONS[1:]},
              "interpretation": "Highest visible layer direction and height-band diagnostics only. Five correlated views of one static synthetic scene; not instance poses, selection accessibility, grasping or stacking accuracy."}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"evaluation.json").write_text(json.dumps(report, indent=2, default=scalar)+"\n")
    print(json.dumps({"real_summary": report["real_summary"], "controls": report["controls"]}, indent=2, default=scalar))


if __name__ == "__main__":
    main()

"""Evaluation-only probes at frozen DEVELOPMENT manual stud references.

This diagnostic intentionally uses scoring truth to measure the current feature
response at known points. It is never imported or called by production
perception, changes no labels/settings, and must never include held-out images.
"""
import argparse
import json
import math
import os
from pathlib import Path

if os.environ.get("ROBO_PUEUE_JOB") != "1":
    raise SystemExit("Queue this diagnostic through the default Pueue group.")

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
from perception.algorithm import Evidence, project

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
cv2.setNumThreads(2)
snapshot = args.snapshot
reference = json.loads((snapshot/"evaluation_input/reference.json").read_text())
registrations = json.loads((snapshot/"evaluation_input/registrations.json").read_text())
assert all(r["split"] == "development" and r["correlation_group"] != "D" for r in registrations["images"])
config = json.loads((snapshot/"effective_config.json").read_text())
refs = {r["file"]: r for r in reference["images"]}
rows = []

for registration in registrations["images"]:
    name = registration["file"]
    image = cv2.imread(str(snapshot/"evaluation_input/images"/name))
    prediction = json.loads((snapshot/"predictions"/f"{Path(name).stem}__nominal.json").read_text())
    candidates = {c["id"]: c for c in prediction["candidates"]}
    pitch = config["pixels_per_stud"]
    extent_u, extent_v = 22*pitch, 20*pitch
    corners = np.array([[0, 0], [extent_u, 0], [extent_u, extent_v], [0, extent_v]], np.float32)
    homography = cv2.getPerspectiveTransform(corners, np.asarray(registration["canonical_quad_xy"], np.float32))
    pad = round(pitch*.75)
    shift = np.array([[1, 0, pad], [0, 1, pad], [0, 0, 1]], np.float64)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rectified = cv2.warpPerspective(gray, shift@np.linalg.inv(homography), (extent_u+2*pad, extent_v+2*pad), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    evidence = Evidence(rectified, config)
    # Correspondence is independent evaluation bookkeeping within a known face,
    # not a per-instance coordinate supplied to the perception implementation.
    by_instance = {}
    for stud in refs[name]["studs"]:
        by_instance.setdefault(stud["instance_id"], []).append(stud)
    for instance, selected in by_instance.items():
        expected = [s["expected_xy"] for s in candidates[instance]["studs"]]
        truth = [[s["x"], s["y"]] for s in selected]
        distance = np.array([[math.dist(a, b) for b in truth] for a in expected])
        ii, jj = linear_sum_assignment(distance)
        for i, j in zip(ii, jj):
            true_point = project([truth[j]], np.linalg.inv(homography))[0]+pad
            projected = project([expected[i]], np.linalg.inv(homography))[0]+pad
            fixed = evidence.stud(true_point, search=False)
            searched = evidence.stud(true_point, search=True)
            grid = evidence.stud(projected, search=True)
            margin = math.ceil(pitch*.60)
            x, y = np.rint(true_point).astype(int)
            noise = float(evidence.mag[y-margin:y+margin+1, x-margin:x+margin+1].mean())
            radial = []
            for fraction in config["stud_radius_fractions"]:
                samples = true_point[None]+pitch*fraction*evidence.rays
                gx = cv2.remap(evidence.gx, samples[:, 0:1].astype(np.float32), samples[:, 1:2].astype(np.float32), cv2.INTER_LINEAR).ravel()
                gy = cv2.remap(evidence.gy, samples[:, 0:1].astype(np.float32), samples[:, 1:2].astype(np.float32), cv2.INTER_LINEAR).ravel()
                value = np.abs(gx*evidence.rays[:, 0]+gy*evidence.rays[:, 1])
                radial.append({"radius_studs": fraction, "radial_gradient_mean": float(value.mean()),
                               "local_gradient_mean": noise, "mean_over_noise_plus_two": float(value.mean()/(noise+2)),
                               "angular_coverage": float((value > max(noise*.5, 2)).mean())})
            rows.append({"image": name, "instance": instance, "manual_image_xy": truth[j], "projected_image_xy": expected[i],
                         "initial_residual_image_px": float(distance[i, j]), "offset_rectified_px": (true_point-projected).tolist(),
                         "fixed_true_center_score": fixed["score"], "searched_true_center_score": searched["score"],
                         "searched_projected_grid_score": grid["score"], "observability": fixed["observability"], "radial_details": radial})

def summary(selected):
    result = {"count": len(selected)}
    for key in ["fixed_true_center_score", "searched_true_center_score", "searched_projected_grid_score", "initial_residual_image_px", "observability"]:
        values = [r[key] for r in selected]
        result[key] = {"median": float(np.median(values)), "p90": float(np.percentile(values, 90)), "max": max(values),
                       "count_ge_current_confirmation_threshold": sum(v >= config["stud_confirm_score"] for v in values) if "score" in key else None}
    return result

report = {"scope": "Evaluation-only DEVELOPMENT truth probes, never perception inputs; no held-out group D data.",
          "configuration_unchanged": True, "stud_confirmation_threshold": config["stud_confirm_score"],
          "search_radius_rectified_px": round(pitch*config["stud_search_fraction"]), "all": summary(rows),
          "images": {name: summary([r for r in rows if r["image"] == name]) for name in sorted({r["image"] for r in rows})}, "points": rows}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+"\n")
print("DIAGNOSTIC_COMPLETE", json.dumps(report["all"]), flush=True)

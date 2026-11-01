"""Prepare frozen evaluation cases, predict without labels, then score.

Image processing is deliberately bounded by the protocol and runs only in the
default shared Pueue queue. This is not a synthetic-data generation pipeline.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

if os.environ.get("ROBO_PUEUE_JOB") != "1":
    raise SystemExit("Submit evaluations through submit_evaluation.py/Pueue.")

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", type=Path, required=True)
args = parser.parse_args()
cv2.setNumThreads(2)
protocol_path = ROOT/"perception/evaluation/protocol.json"
protocol = json.loads(protocol_path.read_text())
registrations = json.loads((ROOT/"evaluation_input/registrations.json").read_text())
reference = json.loads((ROOT/"evaluation_input/reference.json").read_text())
missing = json.loads((ROOT/"evaluation_input/missing_reference.json").read_text())
reference_by_name = {r["file"]: r for r in reference["images"]}
input_dir = ROOT/"prepared_inputs"
(input_dir/"images").mkdir(parents=True, exist_ok=True)
score_dir = ROOT/"scoring_only"
score_dir.mkdir(exist_ok=True)
observations, score_observations = [], []


def transform_points(points, matrix):
    return cv2.transform(np.asarray(points, np.float32).reshape(1, -1, 2), matrix).reshape(-1, 2).astype(float).tolist()


for registration in registrations["images"]:
    name = registration["file"]
    original = cv2.imread(str(ROOT/"evaluation_input/images"/name))
    if original is None:
        raise ValueError(f"Cannot read source {name}")
    height, width = original.shape[:2]
    for case in protocol["fixed_sensitivity_cases"]:
        case_name = case["name"]
        image = original.copy()
        reg = deepcopy(registration)
        ref = deepcopy(reference_by_name[name])
        absences = deepcopy([r for r in missing["instances"] if r["file"] == name])
        if case_name.startswith("brightness_"):
            factor = .7 if case_name == "brightness_070" else 1.3
            image = np.clip(image.astype(np.float32)*factor, 0, 255).astype(np.uint8)
        elif case_name.startswith("rotation_"):
            degrees = -5 if case_name == "rotation_m05" else 5
            matrix = cv2.getRotationMatrix2D((width/2, height/2), degrees, 1)
            image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
            reg["canonical_quad_xy"] = transform_points(reg["canonical_quad_xy"], matrix)
            if "stack_roi_polygon" in ref:
                ref["stack_roi_polygon"] = transform_points(ref["stack_roi_polygon"], matrix)
            for instance in ref["instances"]:
                instance["polygon"] = transform_points(instance["polygon"], matrix)
                if instance.get("orientation_deg") is not None:
                    instance["orientation_deg"] = (instance["orientation_deg"]-degrees) % 180
            for stud in ref.get("studs", []):
                stud["x"], stud["y"] = transform_points([[stud["x"], stud["y"]]], matrix)[0]
            for instance in absences:
                instance["polygon"] = transform_points(instance["polygon"], matrix)
        elif case_name.startswith("initial_"):
            direction = -4 if "_m04" in case_name else 4
            axis = 0 if case_name.startswith("initial_x") else 1
            for point in reg["canonical_quad_xy"]:
                point[axis] += direction
        elif case_name == "flat_image_sanity":
            image[:] = np.rint(original.mean(axis=(0, 1))).astype(np.uint8)
        elif case_name != "nominal":
            raise ValueError(f"Unexpected non-frozen case: {case_name}")
        stem = f"{Path(name).stem}__{case_name}"
        image_name = f"images/{stem}.png"
        cv2.imwrite(str(input_dir/image_name), image)
        observations.append({"image_file": image_name, "registration": reg, "case": case_name, "prediction_file": f"{stem}.json"})
        score_observations.append({"prediction_file": f"{stem}.json", "reference": ref, "missing_slots": absences,
                                   "case": case_name, "split": reg["split"]})
(input_dir/"inputs.json").write_text(json.dumps({"observations": observations}, indent=2)+"\n")
(score_dir/"references.json").write_text(json.dumps({
    "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
    "interpretation": "Frozen image-plane visual-face evidence with manual global registration, nominal intrinsics and unknown physical top height; no physical occupancy/robot pose claim.",
    "observations": score_observations}, indent=2)+"\n")
subprocess.run([sys.executable, str(ROOT/"perception/evaluation/predict_cases.py"), "--inputs", str(input_dir/"inputs.json"),
                "--config", str(args.config), "--output", str(ROOT/"predictions")], check=True)
subprocess.run([sys.executable, str(ROOT/"perception/evaluation/evaluate.py"), "--predictions", str(ROOT/"predictions"),
                "--references", str(score_dir/"references.json"), "--output", str(ROOT/"evaluation")], check=True)
(ROOT/"run_complete.json").write_text(json.dumps({"complete": True, "observations": len(observations)}))
print("EVALUATION_COMPLETE", len(observations), flush=True)

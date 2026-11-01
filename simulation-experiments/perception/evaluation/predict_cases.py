"""Prediction-only subprocess: reads images, coarse registration and config.

No evaluation labels, historical detector predictions or simulator truth are
loaded. Invoked by the queued evaluator after its frozen cases are prepared.
"""
import argparse
import json
import os
from pathlib import Path

if os.environ.get("ROBO_PUEUE_JOB") != "1":
    raise SystemExit("Run batch perception through submit_evaluation.py/Pueue.")

import cv2
from perception.algorithm import analyze, overlay

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--inputs", type=Path, required=True)
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
cv2.setNumThreads(2)
config = json.loads(args.config.read_text())
inputs = json.loads(args.inputs.read_text())
args.output.mkdir(parents=True, exist_ok=True)
(args.output/"overlays").mkdir(exist_ok=True)
for item in inputs["observations"]:
    image = cv2.imread(str(args.inputs.parent/item["image_file"]))
    if image is None:
        raise ValueError(f"Cannot load case image {item['image_file']}")
    result = analyze(image, item["registration"], config)
    result["file"] = item["registration"]["file"]
    result["evaluation_case"] = item["case"]
    (args.output/item["prediction_file"]).write_text(json.dumps(result, indent=2)+"\n")
    rendered = overlay(image, result)
    cv2.imwrite(str(args.output/"overlays"/f"{Path(item['prediction_file']).stem}.jpg"), rendered)
    counts = {d: sum(c["decision"] == d for c in result["candidates"]) for d in ["present", "missing", "uncertain"]}
    print("PREDICTED", item["prediction_file"], json.dumps(counts), flush=True)
(args.output/"prediction_complete.json").write_text(json.dumps({"observations": len(inputs["observations"])}))

"""Pinned pretrained inference, shared unchanged by real and simulated images.

Run only through submit_inference.py in the default Pueue queue. Raw YOLO
boxes are retained separately from the optional image-space PCA summaries.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time

if os.environ.get("ROBO_PUEUE_JOB") != "1":
    raise SystemExit("Submit inference with submit_inference.py; hardware work uses Pueue.")

parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", type=Path, required=True)
parser.add_argument("--weights-dir", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--domain", choices=("real", "sim"), required=True)
args = parser.parse_args()

import cv2
import numpy as np
import torch
from ultralytics import YOLO

torch.set_num_threads(2)
torch.manual_seed(26)
np.random.seed(26)
PAIRS = {
    "studwise_january": ("Brick_Model_best20250123_192838t.pt", "Stud_Model_best20250124_170824.pt"),
    "studwise_march": ("bricks_model_kaggle50epoch_10032025.pt", "studs_model_kaggle50epoch_10032025.pt"),
}
COMMON = dict(conf=0.25, iou=0.5, device=0, half=False, augment=False, max_det=300, verbose=False)
STUD = {**COMMON, "max_det": 1000}
inputs = sorted(p for p in args.input_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
if not inputs:
    raise ValueError("No input images")
args.output_dir.mkdir(parents=True, exist_ok=True)
versions = {}
for package in ("ultralytics", "ultralytics-thop", "torch", "torchvision", "numpy", "opencv-python", "Pillow"):
    versions[package] = importlib.metadata.version(package)
run = {
    "domain": args.domain,
    "versions": versions,
    "cuda": torch.version.cuda,
    "gpu": torch.cuda.get_device_name(0),
    "settings": {**COMMON, "brick_imgsz": 1280, "stud_crop_imgsz": 640, "stud_fullframe_imgsz": 1280,
                 "stud_max_det": 1000, "rect": True},
    "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    "notes": [
        "RGB JPEG/PNG are decoded by OpenCV to BGR; Ultralytics handles normalization and letterboxing.",
        "Stud inference is conditional on raw predicted brick crops, truncated/clipped to integer image bounds.",
        "A separate independent full-frame stud baseline uses imgsz1280 and max_det1000, with no brick proposals.",
        "No simulator truth, image-domain-specific preprocessing, shade labels or metric poses enter inference.",
        "PCA estimates only an undirected image-space angle; eight-stud count is not proof of a single brick or exposure.",
    ],
    "methods": {},
}

for method, (brick_name, stud_name) in PAIRS.items():
    out = args.output_dir / method
    for folder in ("raw_bricks", "raw_studs", "raw_studs_full", "refinement", "overlays"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    brick_path, stud_path = args.weights_dir / brick_name, args.weights_dir / stud_name
    brick_model, stud_model = YOLO(str(brick_path)), YOLO(str(stud_path))
    run["methods"][method] = {
        "brick_weights": brick_name, "stud_weights": stud_name,
        "brick_sha256": hashlib.sha256(brick_path.read_bytes()).hexdigest(),
        "stud_sha256": hashlib.sha256(stud_path.read_bytes()).hexdigest(),
        "brick_classes": brick_model.names, "stud_classes": stud_model.names,
        "images": [],
    }
    for image_path in inputs:
        started = time.monotonic()
        source = cv2.imread(str(image_path))
        if source is None:
            raise ValueError(f"Unable to decode {image_path}")
        height, width = source.shape[:2]
        result = brick_model.predict(source=source, imgsz=1280, rect=True, **COMMON)[0]
        full_result = stud_model.predict(source=source, imgsz=1280, rect=True, **STUD)[0]
        full_studs = []
        full_overlay = source.copy()
        for row in full_result.boxes.data.cpu().numpy():
            sx1, sy1, sx2, sy2, score, cls = row.tolist()
            center = [(sx1+sx2)/2, (sy1+sy2)/2]
            full_studs.append({"box_image_xyxy": [sx1, sy1, sx2, sy2], "center_image_xy": center,
                               "confidence": score, "class_id": int(cls), "class_name": stud_model.names[int(cls)]})
            cv2.circle(full_overlay, tuple(round(v) for v in center), 3, (0, 255, 255), 1)
        (out / "raw_studs_full" / f"{image_path.stem}.json").write_text(json.dumps({
            "image": image_path.name, "domain": args.domain, "width": width, "height": height,
            "detections": full_studs, "max_det_cap_reached": len(full_studs) >= 1000}, indent=2))
        cv2.imwrite(str(out / "overlays" / f"{image_path.stem}_studs_full.jpg"), full_overlay)
        records = []
        for index, row in enumerate(result.boxes.data.cpu().numpy()):
            x1, y1, x2, y2, confidence, cls = row.tolist()
            records.append({"id": f"d{index:03d}", "box_xyxy": [x1, y1, x2, y2],
                            "confidence": confidence, "class_id": int(cls), "class_name": brick_model.names[int(cls)]})
        raw = {"image": image_path.name, "domain": args.domain, "width": width, "height": height,
               "method": method, "detections": records}
        (out / "raw_bricks" / f"{image_path.stem}.json").write_text(json.dumps(raw, indent=2))
        stud_records, refinements = [], []
        brick_overlay = source.copy()
        stud_overlay = source.copy()
        refined_overlay = source.copy()
        for record in records:
            x1, y1, x2, y2 = record["box_xyxy"]
            ix1, iy1 = max(0, int(x1)), max(0, int(y1))
            ix2, iy2 = min(width, int(x2)), min(height, int(y2))
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            crop = source[iy1:iy2, ix1:ix2]
            studs = stud_model.predict(source=crop, imgsz=640, rect=True, **STUD)[0]
            found = []
            for row in studs.boxes.data.cpu().numpy():
                sx1, sy1, sx2, sy2, score, cls = row.tolist()
                box = [sx1+ix1, sy1+iy1, sx2+ix1, sy2+iy1]
                center = [(box[0]+box[2])/2, (box[1]+box[3])/2]
                found.append({"box_crop_xyxy": [sx1, sy1, sx2, sy2], "box_image_xyxy": box,
                              "center_image_xy": center, "confidence": score, "class_id": int(cls),
                              "class_name": stud_model.names[int(cls)]})
                cv2.circle(stud_overlay, tuple(round(v) for v in center), 3, (0, 255, 255), 1)
            stud_records.append({"parent_detection_id": record["id"], "crop_image_xyxy": [ix1, iy1, ix2, iy2],
                                 "detections": found})
            angle, ratio = None, None
            centers = np.asarray([s["center_image_xy"] for s in found], dtype=np.float64)
            if len(centers) >= 4:
                eigval, eigvec = np.linalg.eigh(np.cov(centers.T))
                direction = eigvec[:, -1]
                ratio = float(eigval[-1] / max(eigval[0], 1e-8))
                if ratio >= 2.0:
                    angle = math.degrees(math.atan2(direction[1], direction[0])) % 180
            passes = len(found) == 8 and angle is not None
            refinements.append({"parent_detection_id": record["id"], "stud_count": len(found),
                                "orientation_deg": angle, "pca_eigenvalue_ratio": ratio,
                                "passes_eight_stud_pca_gate": passes,
                                "interpretation": "image-space heuristic only; not exposure, accessibility or metric pose"})
            label = f"{record['id']} {record['confidence']:.2f}"
            cv2.rectangle(brick_overlay, (ix1, iy1), (ix2, iy2), (0, 255, 0), 2)
            cv2.putText(brick_overlay, label, (ix1, max(14, iy1-4)), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 110, 0), 1)
            color = (0, 190, 0) if passes else (0, 0, 220)
            cv2.rectangle(refined_overlay, (ix1, iy1), (ix2, iy2), color, 1)
            cv2.putText(refined_overlay, f"{record['id']} n={len(found)}", (ix1, max(14, iy1-4)), cv2.FONT_HERSHEY_SIMPLEX, .42, color, 1)
            if angle is not None:
                center = centers.mean(axis=0)
                rad = math.radians(angle)
                delta = 20*np.array([math.cos(rad), math.sin(rad)])
                cv2.line(refined_overlay, tuple(np.rint(center-delta).astype(int)), tuple(np.rint(center+delta).astype(int)), (255, 0, 255), 2)
        (out / "raw_studs" / f"{image_path.stem}.json").write_text(json.dumps({"image": image_path.name, "parents": stud_records}, indent=2))
        (out / "refinement" / f"{image_path.stem}.json").write_text(json.dumps({"image": image_path.name, "detections": refinements}, indent=2))
        for name, overlay in (("bricks", brick_overlay), ("studs", stud_overlay), ("refined", refined_overlay)):
            cv2.imwrite(str(out / "overlays" / f"{image_path.stem}_{name}.jpg"), overlay)
        summary = {"image": image_path.name, "raw_bricks": len(records),
                   "raw_studs_fullframe": len(full_studs),
                   "raw_studs_in_predicted_crops": sum(len(p["detections"]) for p in stud_records),
                   "eight_stud_pca_gate": sum(r["passes_eight_stud_pca_gate"] for r in refinements),
                   "seconds": time.monotonic()-started}
        run["methods"][method]["images"].append(summary)
        print("IMAGE_DONE", method, json.dumps(summary), flush=True)
    del brick_model, stud_model
    torch.cuda.empty_cache()
(args.output_dir / "inference_run.json").write_text(json.dumps(run, indent=2))
(args.output_dir / "run_complete.json").write_text(json.dumps({"complete": True, "images": len(inputs), "methods": list(PAIRS)}))
print("INFERENCE_COMPLETE", args.output_dir, flush=True)

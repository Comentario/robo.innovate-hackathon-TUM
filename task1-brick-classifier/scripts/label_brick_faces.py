"""Brick masks for the one-brick-per-photo packages (Brick_Faces_Dataset/brick_faces_*).

Each photo shows a single brick (top view). Grounding DINO proposes boxes; the one
with a brick-like aspect ratio and size closest to the image center is kept and
MobileSAM segments it (outer outline, so the holes of perforated faces belong to
the brick). The current YOLO detector is not used: it fails on the wooden table.

Output in outputs2/brick_faces_labels/<package>/:
  labels.json   per photo: brick_id, label, face, face_type, box and polygon
  review.jpg    every photo with its mask outline, to check by eye
Usage: label_brick_faces.py [packages ...]   (default: every brick_faces_* folder)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import SAM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.live_brick_classifier as live
from scripts.run_mobile_sam import MODEL_PATH

DATASET = PROJECT_ROOT / "Brick_Faces_Dataset"
OUTPUT = PROJECT_ROOT / "outputs2" / "brick_faces_labels"
ASPECT = (2.0, 6.0)
AREA_SHARE = (0.005, 0.2)


def pick_box(boxes: list[dict], shape) -> dict | None:
    h, w = shape[:2]
    candidates = []
    for b in boxes:
        long_side, short_side = max(b["width"], b["height"]), max(1, min(b["width"], b["height"]))
        share = b["width"] * b["height"] / (w * h)
        if ASPECT[0] <= long_side / short_side <= ASPECT[1] and AREA_SHARE[0] <= share <= AREA_SHARE[1]:
            cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            candidates.append((np.hypot(cx - w / 2, cy - h / 2), b))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


def segment(sam, frame: np.ndarray, box: dict) -> np.ndarray | None:
    corners = [box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]]
    result = sam(frame, bboxes=[corners], verbose=False)[0]
    if result.masks is None:
        return None
    mask = result.masks.data[0].cpu().numpy().astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max(contours, key=cv2.contourArea) if contours else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("packages", nargs="*", type=Path)
    args = parser.parse_args()
    packages = args.packages or sorted(p for p in DATASET.glob("brick_faces_*") if p.is_dir())

    placeholder = live.Reference([{"photo": "x", "position": 1, "label": "good", "L_med": 0.0, "C_med": 0.0}],
                                 "raw", "placeholder")
    detector = live.BrickClassifier(placeholder, detector="grounding_dino")
    sam = SAM(str(MODEL_PATH))

    for package in packages:
        out = OUTPUT / package.name
        out.mkdir(parents=True, exist_ok=True)
        rows = list(csv.DictReader((package / "manifest.csv").open(encoding="utf-8")))
        records, tiles = [], []
        for row in rows:
            frame = cv2.imread(str(package / row["file"]))
            box = pick_box(detector.detect_boxes(frame), frame.shape)
            contour = segment(sam, frame, box) if box else None
            record = {**row, "status": "ok" if contour is not None else "no brick found"}
            tile = frame.copy()
            if contour is not None:
                polygon = cv2.approxPolyDP(contour, 2.0, True).reshape(-1, 2)
                x, y, bw, bh = cv2.boundingRect(contour)
                record.update({"bbox_px": {"x": x, "y": y, "width": bw, "height": bh}, "polygon": polygon.tolist()})
                cv2.drawContours(tile, [contour], -1, (0, 255, 0), 5)
            records.append(record)
            tile = cv2.resize(tile, (480, 270))
            text = f"{row['brick_id']} {row['label']} face{row['face']} {record['status']}"
            cv2.putText(tile, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 4)
            cv2.putText(tile, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
            tiles.append(tile)
        tiles += [np.full_like(tiles[0], 255)] * (-len(tiles) % 4)
        cv2.imwrite(str(out / "review.jpg"), np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
        (out / "labels.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
        missing = [f"{r['brick_id']} face{r['face']}" for r in records if r["status"] != "ok"]
        print(f"{package.name}: {len(records) - len(missing)}/{len(records)} masked; missing: {missing}")


if __name__ == "__main__":
    main()

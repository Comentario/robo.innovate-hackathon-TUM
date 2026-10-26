"""Crop every brick of the top-view photos so the hand-written marks can be read.

Top-view photos (Top_View_Dataset/<session>/IMG_xxx.jpg) carry no label in the
file name; good bricks have a hand-written "G" on some faces. This script runs the
YOLO brick detector, straightens each brick crop (long side horizontal, full
resolution) and writes contact sheets with one id per brick (IMG_xxx#k, k in
reading order: top to bottom, left to right).

Output in outputs2/top_view/:
  marks/sheet_NN.jpg   crops with their ids, to read the G marks
  bricks.json          id, photo, box, mask polygon and detector confidence
  labels.csv           template: id, label (fill g / b / ?), note
Usage: top_view_marks.py [--session Top_View_Dataset/20261025_211845] [--weights best.pt]
"""

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION = PROJECT_ROOT / "Top_View_Dataset" / "20261025_211845"
WEIGHTS = PROJECT_ROOT / "outputs2" / "yolo_runs" / "brick_seg_v2" / "weights" / "best.pt"
OUTPUT = PROJECT_ROOT / "outputs2" / "top_view"
CONFIDENCE = 0.5
CROP_WIDTH = 620
PER_SHEET = 16
COLUMNS = 2


def straight_crop(image: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    (cx, cy), (w, h), angle = cv2.minAreaRect(polygon.astype(np.float32))
    if w < h:
        w, h, angle = h, w, angle + 90
    w, h = int(w) + 20, int(h) + 20
    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    matrix[:, 2] += (w / 2 - cx, h / 2 - cy)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def tile(crop: np.ndarray, title: str) -> np.ndarray:
    scale = CROP_WIDTH / crop.shape[1]
    crop = cv2.resize(crop, (CROP_WIDTH, max(1, int(crop.shape[0] * scale))))
    crop = crop[:260] if crop.shape[0] > 260 else np.vstack([crop, np.full((260 - crop.shape[0], CROP_WIDTH, 3), 255, np.uint8)])
    head = np.full((34, CROP_WIDTH, 3), 255, np.uint8)
    cv2.putText(head, title, (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
    return np.vstack([head, crop, np.full((8, CROP_WIDTH, 3), 255, np.uint8)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, default=SESSION)
    parser.add_argument("--weights", type=Path, default=WEIGHTS)
    args = parser.parse_args()
    (OUTPUT / "marks").mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.weights))

    bricks, tiles = [], []
    for path in sorted(args.session.glob("IMG_*.jpg")):
        image = cv2.imread(str(path))
        result = model.predict(image, conf=CONFIDENCE, retina_masks=True, verbose=False)[0]
        if result.masks is None:
            continue
        polygons = result.masks.xy
        centers = [p.mean(axis=0) for p in polygons]
        # Reading order: rows of similar height first, then left to right.
        order = sorted(range(len(polygons)), key=lambda i: (round(centers[i][1] / 150), centers[i][0]))
        for k, i in enumerate(order, 1):
            brick_id = f"{path.stem}#{k}"
            x1, y1, x2, y2 = result.boxes.xyxy[i].cpu().numpy().round().astype(int).tolist()
            bricks.append({"id": brick_id, "photo": path.name, "position": k,
                           "bbox_px": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                           "polygon": polygons[i].round(1).tolist(), "confidence": round(float(result.boxes.conf[i]), 3)})
            tiles.append(tile(straight_crop(image, polygons[i]), brick_id))

    for n, start in enumerate(range(0, len(tiles), PER_SHEET), 1):
        chunk = tiles[start:start + PER_SHEET]
        chunk += [np.full_like(chunk[0], 255)] * (-len(chunk) % COLUMNS)
        rows = [np.hstack(chunk[i:i + COLUMNS]) for i in range(0, len(chunk), COLUMNS)]
        cv2.imwrite(str(OUTPUT / "marks" / f"sheet_{n:02d}.jpg"), np.vstack(rows))

    (OUTPUT / "bricks.json").write_text(json.dumps(bricks), encoding="utf-8")
    labels = OUTPUT / "labels.csv"
    if not labels.exists():
        with labels.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "label", "note"])
            writer.writerows([[b["id"], "", ""] for b in bricks])
    print(f"{len(bricks)} bricks in {len({b['photo'] for b in bricks})} photos; sheets in {OUTPUT / 'marks'}")


if __name__ == "__main__":
    main()

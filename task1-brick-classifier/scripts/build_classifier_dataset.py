"""Brick crops for the good/bad neural-network classifier (top view).

Every labeled brick is cut out along its mask, straightened (long side
horizontal), the background painted neutral grey (so the network sees the brick,
not the table or carpet) and padded to a square without distortion.

Sources:
  top_night   Top_View_Dataset photos labeled in outputs2/top_view/labels.csv
              (YOLO masks; no brick id, several bricks per photo)
  wood        Brick_Faces_Dataset/brick_faces_wood_*   (masks from label_brick_faces.py)
  carpet      Brick_Faces_Dataset/brick_faces_carpet_*
In wood and carpet, brick_id is the physical brick within that package (ids are
not matched between packages).

Output: outputs2/classifier_crops/images/*.png and index.csv
  (file, label, source, group, brick_id, face, face_type)
Usage: build_classifier_dataset.py [--size 224]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.top_view_marks import OUTPUT as TOP_OUTPUT
from scripts.top_view_marks import SESSION as TOP_SESSION

FACES_DATASET = PROJECT_ROOT / "Brick_Faces_Dataset"
FACES_LABELS = PROJECT_ROOT / "outputs2" / "brick_faces_labels"
OUTPUT = PROJECT_ROOT / "outputs2" / "classifier_crops"
GREY = 114


def brick_crop(image: np.ndarray, polygon: np.ndarray, size: int) -> np.ndarray:
    """Straightened brick with grey background, padded to a size x size square."""
    # Work on the brick's surroundings only (same result, much faster on full frames).
    x, y, w, h = cv2.boundingRect(polygon.astype(np.int32))
    margin = max(w, h) // 2 + 8
    x0, y0 = max(0, x - margin), max(0, y - margin)
    image = image[y0:y + h + margin, x0:x + w + margin]
    polygon = polygon - (x0, y0)
    mask = np.zeros(image.shape[:2], np.uint8)
    cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
    # Same pixels as masking with a boolean index, ~30x faster on large crops.
    masked = np.full_like(image, GREY)
    cv2.copyTo(image, mask, masked)
    (cx, cy), (w, h), angle = cv2.minAreaRect(polygon.astype(np.float32))
    if w < h:
        w, h, angle = h, w, angle + 90
    w, h = int(w) + 8, int(h) + 8
    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    matrix[:, 2] += (w / 2 - cx, h / 2 - cy)
    crop = cv2.warpAffine(masked, matrix, (w, h), flags=cv2.INTER_AREA, borderValue=(GREY,) * 3)
    scale = size / max(w, h)
    crop = cv2.resize(crop, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    canvas = np.full((size, size, 3), GREY, np.uint8)
    y0, x0 = (size - crop.shape[0]) // 2, (size - crop.shape[1]) // 2
    canvas[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--size", type=int, default=224)
    args = parser.parse_args()
    images = OUTPUT / "images"
    images.mkdir(parents=True, exist_ok=True)
    rows = []

    labels = {r["id"]: r["label"].strip() for r in csv.DictReader((TOP_OUTPUT / "labels.csv").open(encoding="utf-8-sig"))}
    bricks = json.loads((TOP_OUTPUT / "bricks.json").read_text(encoding="utf-8"))
    frames = {}
    for b in bricks:
        label = {"g": "good", "b": "bad"}.get(labels.get(b["id"], "?"))
        if label is None:
            continue
        frame = frames.setdefault(b["photo"], cv2.imread(str(TOP_SESSION / b["photo"])))
        name = f"top_night_{b['id'].replace('#', '_')}.png"
        cv2.imwrite(str(images / name), brick_crop(frame, np.array(b["polygon"]), args.size))
        rows.append({"file": name, "label": label, "source": "top_night", "group": f"top_night_{b['photo'][:-4]}",
                     "brick_id": "", "face": "", "face_type": ""})

    for package in sorted(p for p in FACES_DATASET.glob("brick_faces_*") if p.is_dir()):
        source = package.name.split("_")[2]
        records = json.loads((FACES_LABELS / package.name / "labels.json").read_text(encoding="utf-8"))
        for r in records:
            if r["status"] != "ok":
                continue
            frame = cv2.imread(str(package / r["file"]))
            name = f"{source}_{r['brick_id']}_face{r['face']}.png"
            cv2.imwrite(str(images / name), brick_crop(frame, np.array(r["polygon"]), args.size))
            rows.append({"file": name, "label": r["label"], "source": source, "group": f"{source}_{r['brick_id']}",
                         "brick_id": r["brick_id"], "face": r["face"], "face_type": r["face_type"]})

    with (OUTPUT / "index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for source in sorted({r["source"] for r in rows}):
        part = [r for r in rows if r["source"] == source]
        print(f"{source:10s} {len(part):4d} crops  good {sum(r['label'] == 'good' for r in part):3d}  "
              f"bad {sum(r['label'] == 'bad' for r in part):3d}")
    print(f"output: {OUTPUT}")


if __name__ == "__main__":
    main()

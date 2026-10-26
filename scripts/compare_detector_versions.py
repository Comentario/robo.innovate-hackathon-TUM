"""Compare two brick detectors (default v2 vs v3) on labeled and unlabeled photo sets.

Labeled: the val split of outputs2/yolo_dataset_v3, per source (standing, top,
wood, carpet): found / missed / extra bricks and mask IoU, as in
compare_brick_detector.py.
Unlabeled stress sets (never used for training):
  wood_overexposed  Brick_Faces_Dataset/20261026_121357 (one brick per photo, too bright)
  live_today        outputs2/live/20261026_*/frames (bricks on the wooden table)
  empty             empty-table photos (should give no detection; v3 trained on them)
For one-brick photos "right" means exactly one detection; sheets show both models.

Output: outputs2/yolo_runs/<new>/versions_comparison/ (summary.json, sheets)
Usage: compare_detector_versions.py [--old brick_seg_v2] [--new brick_seg_v3] [--conf 0.5]
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.compare_brick_detector import RUNS, draw, match, polygons_to_masks, predict_masks, save_sheet

DATASET = PROJECT_ROOT / "outputs2" / "yolo_dataset_v3"
STRESS = {
    "wood_overexposed": sorted((PROJECT_ROOT / "Brick_Faces_Dataset" / "20261026_121357").glob("brick_*/face_*.jpg")),
    "live_today": sorted((PROJECT_ROOT / "outputs2" / "live").glob("20261026_*/frames/*.jpg")),
    "empty": sorted((PROJECT_ROOT / "Brick_Faces_Dataset").glob("*/background/*.jpg")),
}
EXPECTED = {"wood_overexposed": 1, "empty": 0}


def read_polygons(label: Path, shape) -> list[np.ndarray]:
    h, w = shape[:2]
    polygons = []
    for line in label.read_text(encoding="utf-8").splitlines():
        values = [float(v) for v in line.split()[1:]]
        if values:
            polygons.append(np.array(values).reshape(-1, 2) * (w, h))
    return polygons


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", default="brick_seg_v2")
    parser.add_argument("--new", default="brick_seg_v3")
    parser.add_argument("--conf", type=float, default=0.5)
    args = parser.parse_args()
    models = {name: YOLO(str(RUNS / name / "weights" / "best.pt")) for name in (args.old, args.new)}
    out = RUNS / args.new / "versions_comparison"
    out.mkdir(parents=True, exist_ok=True)
    summary = {}

    by_source: dict[str, dict] = {}
    for image_path in sorted((DATASET / "images" / "val").iterdir()):
        source = image_path.stem.split("_")[0]
        image = cv2.imread(str(image_path))
        labels = polygons_to_masks(read_polygons(DATASET / "labels" / "val" / f"{image_path.stem}.txt", image.shape),
                                   image.shape)
        for name, model in models.items():
            preds, _ = predict_masks(model, image, args.conf)
            ious, missed, extra = match(labels, preds)
            s = by_source.setdefault(source, {}).setdefault(name, {"photos": 0, "bricks": 0, "found": 0, "missed": 0,
                                                                    "extra": 0, "ious": []})
            s["photos"] += 1
            s["bricks"] += len(labels)
            s["found"] += len(ious)
            s["missed"] += missed
            s["extra"] += extra
            s["ious"] += ious
    for source, per_model in by_source.items():
        for s in per_model.values():
            s["mean_iou"] = round(float(np.mean(s.pop("ious"))), 3) if s["found"] else None
    summary["labeled_val"] = by_source

    for set_name, paths in STRESS.items():
        rows, counts = [], {name: [] for name in models}
        for path in paths:
            image = cv2.imread(str(path))
            tiles = []
            for name, model in models.items():
                preds, scores = predict_masks(model, image, args.conf)
                counts[name].append(len(preds))
                tiles.append(draw(image, preds, f"{name}: {len(preds)}  {path.parent.parent.name}/{path.name}", scores))
            rows.append(np.hstack(tiles))
        save_sheet(rows, out / f"{set_name}.jpg")
        expected = EXPECTED.get(set_name)
        summary[set_name] = {name: {"photos": len(c), "detections": int(sum(c)),
                                    "photos_with_count": {str(k): c.count(k) for k in sorted(set(c))},
                                    **({"right": sum(v == expected for v in c)} if expected is not None else {})}
                             for name, c in counts.items()}

    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"output: {out}")


if __name__ == "__main__":
    main()

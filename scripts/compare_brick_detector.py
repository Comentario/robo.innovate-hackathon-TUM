"""Compare the trained YOLO brick detector with the pipeline labels, and time it.

For every validation photo: count agreement and mask IoU between YOLO and the
pipeline label (Grounding DINO + MobileSAM, reviewed). Side-by-side images:
left = pipeline label, right = YOLO prediction.

Extra "stress" photos the model never saw are also drawn (excluded photos and
lying bricks from Second_Dataset_Bricks) to show where it may fail.

Output: outputs2/yolo_runs/<run>/comparison/
Output: outputs2/yolo_runs/<run>/comparison_<view>/ for --view top.
Usage: compare_brick_detector.py [--run brick_seg] [--conf 0.5] [--view standing|top] [--no-stress]
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.build_yolo_dataset as dataset
from scripts.build_yolo_dataset import labeled_bricks, photo_id

RUNS = PROJECT_ROOT / "outputs2" / "yolo_runs"
COLORS = [(214, 120, 42), (52, 104, 235), (122, 175, 27), (0, 161, 237),
          (164, 123, 232), (0, 131, 0), (214, 80, 98), (40, 40, 200), (200, 200, 0)]
TILE = (640, 360)


def polygons_to_masks(polygons: list, shape) -> list[np.ndarray]:
    masks = []
    for poly in polygons:
        mask = np.zeros(shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.array(poly, np.int32)], 1)
        masks.append(mask.astype(bool))
    return masks


def predict_masks(model, image, conf) -> tuple[list[np.ndarray], list[float]]:
    result = model.predict(image, conf=conf, verbose=False, retina_masks=True)[0]
    if result.masks is None:
        return [], []
    masks = [m.astype(bool) for m in result.masks.data.cpu().numpy()]
    return masks, result.boxes.conf.cpu().numpy().tolist()


def match(labels: list[np.ndarray], preds: list[np.ndarray]) -> tuple[list[float], int, int]:
    """Greedy IoU matching; returns IoUs of matched pairs, missed labels, extra predictions."""
    pairs = []
    for i, a in enumerate(labels):
        for j, b in enumerate(preds):
            inter = np.logical_and(a, b).sum()
            if inter:
                pairs.append((inter / np.logical_or(a, b).sum(), i, j))
    used_i, used_j, ious = set(), set(), []
    for iou, i, j in sorted(pairs, reverse=True):
        if iou >= 0.5 and i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            ious.append(float(iou))
    return ious, len(labels) - len(used_i), len(preds) - len(used_j)


def draw(image, masks, title, scores=None) -> np.ndarray:
    canvas = image.copy()
    overlay = image.copy()
    for k, mask in enumerate(masks):
        color = COLORS[k % len(COLORS)]
        overlay[mask] = color
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 4)
        if scores is not None:
            ys, xs = np.nonzero(mask)
            cv2.putText(canvas, f"{scores[k]:.2f}", (int(xs.min()) + 6, int(ys.min()) + 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    canvas = cv2.addWeighted(overlay, 0.3, canvas, 0.7, 0)
    tile = cv2.resize(canvas, TILE)
    head = np.full((36, TILE[0], 3), 255, np.uint8)
    cv2.putText(head, title, (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([head, tile])


def save_sheet(rows: list[np.ndarray], path: Path) -> None:
    for n, start in enumerate(range(0, len(rows), 6), 1):
        cv2.imwrite(str(path.with_name(f"{path.stem}_{n:02d}.jpg")), np.vstack(rows[start:start + 6]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", default="brick_seg")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--view", choices=["standing", "top"], default="standing")
    parser.add_argument("--no-stress", action="store_true", help="skip the unseen stress sheets")
    args = parser.parse_args()
    dataset.configure(args.view)
    out = RUNS / args.run / ("comparison" if args.view == "standing" else f"comparison_{args.view}")
    out.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(RUNS / args.run / "weights" / "best.pt"))

    records = json.loads(dataset.CACHE_PATH.read_text(encoding="utf-8"))
    excluded = {l.strip() for l in dataset.EXCLUDE_PATH.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")}
    val = [r for r in records if r["source"] in dataset.VAL_SOURCES and photo_id(r) not in excluded and not r["dark"]]

    rows, ious, missed, extra, per_photo = [], [], 0, 0, []
    for r in val:
        image = cv2.imread(str(PROJECT_ROOT / r["path"]))
        labels = polygons_to_masks([b["polygon"] for b in labeled_bricks(r)], image.shape)
        preds, scores = predict_masks(model, image, args.conf)
        photo_ious, m, e = match(labels, preds)
        ious += photo_ious
        missed += m
        extra += e
        per_photo.append({"photo": photo_id(r), "labels": len(labels), "predicted": len(preds),
                          "missed": m, "extra": e, "mean_iou": round(float(np.mean(photo_ious)), 3) if photo_ious else None})
        rows.append(np.hstack([draw(image, labels, f"{photo_id(r)}  pipeline: {len(labels)}"),
                               draw(image, preds, f"YOLO: {len(preds)}  missed {m}  extra {e}", scores)]))
    save_sheet(rows, out / "val_side_by_side.jpg")

    stress = [r for r in records if photo_id(r) in excluded]
    stress_paths = [] if args.no_stress else [PROJECT_ROOT / r["path"] for r in stress]
    if args.view == "standing" and not args.no_stress:
        stress_paths += sorted((PROJECT_ROOT / "Second_Dataset_Bricks").glob("*.jpg"))
    stress_rows = []
    for path in stress_paths:
        image = cv2.imread(str(path))
        preds, scores = predict_masks(model, image, args.conf)
        stress_rows.append(draw(image, preds, f"{path.parent.name}/{path.name}  YOLO: {len(preds)}", scores))
    pairs = [np.hstack(stress_rows[i:i + 2]) if i + 1 < len(stress_rows)
             else np.hstack([stress_rows[i], np.full_like(stress_rows[i], 250)]) for i in range(0, len(stress_rows), 2)]
    save_sheet(pairs, out / "unseen_stress.jpg")

    image = cv2.imread(str(PROJECT_ROOT / val[0]["path"]))
    for _ in range(5):
        model.predict(image, verbose=False)
    times = []
    for _ in range(30):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        start = time.perf_counter()
        model.predict(image, conf=args.conf, verbose=False, retina_masks=True)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        times.append(time.perf_counter() - start)
    median = statistics.median(times)

    summary = {"val_photos": len(val), "label_bricks": sum(p["labels"] for p in per_photo),
               "matched": len(ious), "missed": missed, "extra": extra,
               "mean_mask_iou": round(float(np.mean(ious)), 3), "min_mask_iou": round(float(np.min(ious)), 3),
               "speed_ms_per_frame_1080p": round(median * 1000, 1),
               "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
               "per_photo": per_photo}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print({k: v for k, v in summary.items() if k != "per_photo"})
    for p in per_photo:
        if p["missed"] or p["extra"] or (p["mean_iou"] or 1) < 0.85:
            print("  check:", p)
    print(f"output: {out}")


if __name__ == "__main__":
    main()

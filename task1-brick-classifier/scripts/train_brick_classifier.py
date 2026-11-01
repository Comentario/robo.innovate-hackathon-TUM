"""Train and evaluate the good/bad neural-network classifier (YOLO11n-cls on brick crops).

Crops come from build_classifier_dataset.py. Color is the signal, so every color
augmentation is off (no hue / saturation / value jitter, no RandAugment, no random
erasing); only flips and a mild crop are used.

Experiments (--experiment):
  conditions  same bricks, new conditions: train on top_night + wood, test on carpet
              (the carpet photos are new, but the bricks are the same 10)
  unseen      unseen brick: inside one package (wood or carpet), train on 9 bricks
              and test on the 10th, for every brick. Other packages are left out
              because they contain the same physical bricks. This is the honest
              estimate for bricks never seen; only ~30 training crops per run.
  final       train on every crop (the model for the live demo)
  light       new light, same bricks: for each --holdout calibration, train on every
              other crop (needs --include-calibrations) and test on that calibration

--include-calibrations adds the bricks of every calibration in outputs2/calibration
(each one taken in its own light): crops saved by web_demo.py are used as they are;
for older calibrations the bricks are cut out of their frames (YOLO mask matched to
the calibration box) and cached in <calibration>/crops/. web_demo.py retrains this
way after each calibration, so the network sees more light conditions over time.

--include-videos adds the labeled crops of recorded videos: outputs2/video_crops/<video>/index.csv
(same columns as classifier_crops/index.csv, absolute crop paths), e.g. the Gemini 2 recordings.

Results: outputs2/classifier_runs/<name>/results.json (+ predictions.csv)
Weights of `final`: outputs2/classifier_runs/<name>/weights/best.pt (name = experiment by default)
Usage: train_brick_classifier.py --experiment conditions|unseen|final [--epochs 40]
                                 [--include-calibrations] [--include-videos] [--name web_20261026_170000]
"""

import argparse
import csv
import json
import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
CROPS = PROJECT_ROOT / "outputs2" / "classifier_crops"
RUNS = PROJECT_ROOT / "outputs2" / "classifier_runs"
BASE_WEIGHTS = PROJECT_ROOT / "models" / "yolo11n-cls.pt"
CALIBRATION_ROOT = PROJECT_ROOT / "outputs2" / "calibration"
VIDEO_CROPS = PROJECT_ROOT / "outputs2" / "video_crops"
DETECTOR = PROJECT_ROOT / "outputs2" / "yolo_runs" / "brick_seg_v3" / "weights" / "best.pt"
NO_COLOR_AUGMENT = {"hsv_h": 0.0, "hsv_s": 0.0, "hsv_v": 0.0, "auto_augment": None, "erasing": 0.0,
                    "scale": 0.1, "fliplr": 0.5, "flipud": 0.5}


def link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def crop_path(row: dict) -> Path:
    path = Path(row["file"])
    return path if path.is_absolute() else CROPS / "images" / path


def make_split(root: Path, rows: list[dict]) -> Path:
    """Folder layout for YOLO-cls; val is a copy of train (evaluation is done separately)."""
    if root.exists():
        shutil.rmtree(root)
    for split in ("train", "val"):
        for r in rows:
            name = r["file"] if not Path(r["file"]).is_absolute() else f"{r['group']}_{Path(r['file']).name}"
            link(crop_path(r), root / split / r["label"] / name)
    return root


def box_iou(a: dict, b: dict) -> float:
    ax2, ay2, bx2, by2 = a["x"] + a["width"], a["y"] + a["height"], b["x"] + b["width"], b["y"] + b["height"]
    inter = max(0, min(ax2, bx2) - max(a["x"], b["x"])) * max(0, min(ay2, by2) - max(a["y"], b["y"]))
    return inter / (a["width"] * a["height"] + b["width"] * b["height"] - inter + 1e-6)


def calibration_rows() -> list[dict]:
    """Crops of the labeled bricks of every calibration (cut out of the frames when missing)."""
    from scripts.build_classifier_dataset import brick_crop

    detector, rows = None, []
    for path in sorted(CALIBRATION_ROOT.glob("*/calibration.json")):
        root = path.parent
        data = json.loads(path.read_text(encoding="utf-8"))
        for photo in sorted({r["photo"] for r in data["rows"]}):
            faces = [r for r in data["rows"] if r["photo"] == photo]
            missing = [r for r in faces if not (root / (r.get("crop") or f"crops/{photo}_{r['position']}.png")).exists()]
            if missing:
                frame = cv2.imread(str(root / "frames" / f"{photo}.jpg"))
                if frame is None:
                    continue
                detector = detector or YOLO(str(DETECTOR))
                result = detector.predict(frame, conf=0.5, retina_masks=True, verbose=False)[0]
                if result.masks is None:
                    continue
                boxes = [{"x": int(x1), "y": int(y1), "width": int(x2 - x1), "height": int(y2 - y1)}
                         for x1, y1, x2, y2 in result.boxes.xyxy.cpu().numpy().round().astype(int)]
                for r in missing:
                    overlaps = [box_iou(r["bbox_px"], b) for b in boxes]
                    best = int(np.argmax(overlaps))
                    if overlaps[best] >= 0.5:
                        (root / "crops").mkdir(exist_ok=True)
                        cv2.imwrite(str(root / f"crops/{photo}_{r['position']}.png"),
                                    brick_crop(frame, result.masks.xy[best], 224))
            for r in faces:
                crop = root / (r.get("crop") or f"crops/{photo}_{r['position']}.png")
                if crop.exists():
                    rows.append({"file": str(crop), "label": r["label"], "source": f"calibration_{root.name}",
                                 "group": f"{root.name}_{photo}", "brick_id": "", "face": "", "face_type": ""})
    return rows


def video_rows() -> list[dict]:
    """Labeled crops of recorded videos (outputs2/video_crops/<video>/index.csv)."""
    rows = []
    for index in sorted(VIDEO_CROPS.glob("*/index.csv")):
        rows += [{k: r[k] for k in ("file", "label", "source", "group", "brick_id", "face", "face_type")}
                 for r in csv.DictReader(index.open(encoding="utf-8"))]
    return rows


def train(name: str, rows: list[dict], epochs: int, batch: int) -> YOLO:
    data = make_split(RUNS / "_data" / name, rows)
    model = YOLO(str(BASE_WEIGHTS))
    model.train(data=str(data), epochs=epochs, imgsz=224, batch=batch, workers=0, seed=0, deterministic=True,
                project=str(RUNS), name=name, exist_ok=True, plots=False, verbose=False, patience=epochs,
                **NO_COLOR_AUGMENT)
    return YOLO(str(RUNS / name / "weights" / "best.pt"))


def predict(model: YOLO, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        result = model.predict(str(crop_path(r)), imgsz=224, verbose=False)[0]
        probs = result.probs.data.cpu().numpy()
        names = result.names
        good = float(probs[[k for k, v in names.items() if v == "good"][0]])
        out.append({**r, "prediction": "good" if good >= 0.5 else "bad", "p_good": round(good, 3)})
    return out


def metrics(pred: list[dict]) -> dict:
    truth = np.array([p["label"] for p in pred])
    guess = np.array([p["prediction"] for p in pred])
    good = float((guess[truth == "good"] == "good").mean()) if (truth == "good").any() else float("nan")
    bad = float((guess[truth == "bad"] == "bad").mean()) if (truth == "bad").any() else float("nan")
    return {"n": len(pred), "correct": int((truth == guess).sum()), "accuracy": round(float((truth == guess).mean()), 3),
            "good_recall": round(good, 3), "bad_recall": round(bad, 3), "balanced_accuracy": round((good + bad) / 2, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", choices=["conditions", "unseen", "final", "light"], required=True)
    parser.add_argument("--holdout", nargs="*", default=[],
                        help="light: calibration folders to hold out one at a time (same bricks, light not seen)")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--include-calibrations", action="store_true",
                        help="add the bricks of every calibration in outputs2/calibration")
    parser.add_argument("--include-videos", action="store_true",
                        help="add the labeled crops of recorded videos in outputs2/video_crops")
    parser.add_argument("--name", help="run name for final (default: the experiment name)")
    args = parser.parse_args()
    rows = list(csv.DictReader((CROPS / "index.csv").open(encoding="utf-8")))
    if args.include_calibrations:
        extra = calibration_rows()
        print(f"calibration crops: {len(extra)} from {len({r['source'] for r in extra})} calibrations")
        rows += extra
    if args.include_videos:
        extra = video_rows()
        print(f"video crops: {len(extra)} from {len({r['source'] for r in extra})} videos")
        rows += extra
    name = args.name or args.experiment
    out = RUNS / name
    out.mkdir(parents=True, exist_ok=True)
    results, predictions = {}, []

    if args.experiment == "conditions":
        model = train("conditions", [r for r in rows if r["source"] != "carpet"], args.epochs, args.batch)
        predictions = predict(model, [r for r in rows if r["source"] == "carpet"])
        results["carpet_same_bricks"] = metrics(predictions)
    elif args.experiment == "light":
        for held in args.holdout:
            source = f"calibration_{held}"
            test = [r for r in rows if r["source"] == source]
            if not test:
                print(f"{held}: no crops, skipped")
                continue
            model = train(f"light_{held}", [r for r in rows if r["source"] != source], args.epochs, args.batch)
            fold = predict(model, test)
            predictions += [{**p, "fold": held} for p in fold]
            results[held] = metrics(fold)
            print(held, results[held])
        results["all_held_out_lights"] = metrics(predictions)
    elif args.experiment == "unseen":
        for source in ("wood", "carpet"):
            part = [r for r in rows if r["source"] == source]
            for brick in sorted({r["brick_id"] for r in part}):
                held = [r for r in part if r["brick_id"] == brick]
                model = train(f"unseen_{source}_{brick}", [r for r in part if r["brick_id"] != brick],
                              args.epochs, args.batch)
                predictions += [{**p, "fold": f"{source}_{brick}"} for p in predict(model, held)]
            results[f"{source}_unseen_brick"] = metrics([p for p in predictions if p["source"] == source])
            per_brick = {}
            for p in predictions:
                if p["source"] == source:
                    per_brick.setdefault(p["brick_id"], []).append(p["prediction"] == p["label"])
            results[f"{source}_per_brick"] = {b: f"{sum(v)}/{len(v)}" for b, v in sorted(per_brick.items())}
        results["all_unseen_brick"] = metrics(predictions)
    else:
        model = train(name, rows, args.epochs, args.batch)
        predictions = predict(model, rows)
        results["training_data"] = metrics(predictions)
        results["note"] = "scored on its own training crops: memorization, not generalization"
        results["crops"] = {source: sum(r["source"] == source for r in rows) for source in sorted({r["source"] for r in rows})}

    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (out / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

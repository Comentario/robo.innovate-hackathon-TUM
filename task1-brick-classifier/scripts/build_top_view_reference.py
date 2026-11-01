"""Build a top-view calibration file from the labeled top-view photos.

Runs the live classifier's own measurement (YOLO detector, same color features)
on every Top_View_Dataset photo, takes the labels from outputs2/top_view/labels.csv
(g / b; ? is left out) by matching each detection to the labeled brick box, and
writes a calibration.json usable with live_brick_classifier.py --reference.

It also reports leave-one-photo-out accuracy of the 1-NN rule (the live
classifier's knn) and of the L* band on these rows. The same physical bricks are
in many photos, so this measures recognition of THESE bricks, not new ones.

Output: outputs2/top_view/reference/calibration.json
Usage: build_top_view_reference.py [--session Top_View_Dataset/20261025_211845] [--features raw]
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.live_brick_classifier as live
from scripts.top_view_marks import OUTPUT, SESSION

MIN_MATCH_IOU = 0.5


def box_iou(a: dict, b: dict) -> float:
    ax2, ay2, bx2, by2 = a["x"] + a["width"], a["y"] + a["height"], b["x"] + b["width"], b["y"] + b["height"]
    w = max(0, min(ax2, bx2) - max(a["x"], b["x"]))
    h = max(0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = w * h
    return inter / (a["width"] * a["height"] + b["width"] * b["height"] - inter + 1e-6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, default=SESSION)
    parser.add_argument("--features", choices=sorted(live.FEATURE_OPTIONS), default="raw")
    args = parser.parse_args()

    labels = {r["id"]: r["label"].strip() for r in csv.DictReader((OUTPUT / "labels.csv").open(encoding="utf-8-sig"))}
    bricks = json.loads((OUTPUT / "bricks.json").read_text(encoding="utf-8"))
    placeholder = live.Reference([{"photo": "x", "position": 1, "label": "good", "L_med": 0.0, "C_med": 0.0}],
                                 "raw", "placeholder")
    classifier = live.BrickClassifier(placeholder, detector="yolo")

    rows, lightness, camera = [], [], None
    for photo in sorted({b["photo"] for b in bricks}):
        frame = cv2.imread(str(args.session / photo))
        lightness.append(live.scene_lightness(frame))
        meta = args.session / photo.replace(".jpg", ".json")
        if camera is None and meta.exists():
            camera = json.loads(meta.read_text(encoding="utf-8")).get("camera")
        measured = classifier.measure(frame)["bricks"]
        for b in (b for b in bricks if b["photo"] == photo):
            label = {"g": "good", "b": "bad"}.get(labels.get(b["id"], "?"))
            if label is None or not measured:
                continue
            best = max(measured, key=lambda m: box_iou(m["bbox_px"], b["bbox_px"]))
            if box_iou(best["bbox_px"], b["bbox_px"]) < MIN_MATCH_IOU:
                continue
            features = {k: float(v) for k, v in best["all_features"].items() if isinstance(v, (int, float))}
            rows.append({"photo": photo.replace(".jpg", ""), "position": b["position"], "label": label,
                         "bbox_px": best["bbox_px"], "face": best["all_features"]["face"],
                         "scene_lightness": round(float(lightness[-1]), 1), **features})
    goods = sum(r["label"] == "good" for r in rows)
    print(f"{len(rows)} labeled bricks matched ({goods} good, {len(rows) - goods} bad)")

    # Leave-one-photo-out with the live classifier's own rules.
    keys = live.FEATURE_OPTIONS[args.features]
    knn_ok, band_ok = [], []
    for photo in sorted({r["photo"] for r in rows}):
        train = [r for r in rows if r["photo"] != photo]
        test = [r for r in rows if r["photo"] == photo]
        reference = live.Reference(train, args.features, "loo")
        low, high = live.fit_band(train, "L_med")
        for r in test:
            knn_ok.append((reference.predict(r)["prediction"], r["label"]))
            band_ok.append(("good" if low <= r["L_med"] <= high else "bad", r["label"]))
    for name, pairs in (("1-NN " + "+".join(keys), knn_ok), ("band L_med", band_ok)):
        correct = sum(p == t for p, t in pairs)
        good = [p == t for p, t in pairs if t == "good"]
        bad = [p == t for p, t in pairs if t == "bad"]
        print(f"leave-one-photo-out {name:18s} {correct}/{len(pairs)} ({correct / len(pairs):.0%})  "
              f"good {np.mean(good):.0%}  bad {np.mean(bad):.0%}")

    out = OUTPUT / "reference"
    out.mkdir(parents=True, exist_ok=True)
    band = live.fit_band(rows, "L_med")
    data = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "source": str(args.session), "view": "top",
            "camera": camera, "scene_lightness": round(float(np.median(lightness)), 1), "feature_set": args.features,
            "band_L_med": [band[0], band[1]], "bands_by_face": {"solid": [band[0], band[1]], "perforated": None},
            "good_bricks": goods, "bad_bricks": len(rows) - goods, "rows": rows}
    (out / "calibration.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"reference: {out / 'calibration.json'}")


if __name__ == "__main__":
    main()

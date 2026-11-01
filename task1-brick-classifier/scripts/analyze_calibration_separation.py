"""Which color features separate good from bad bricks in one (top-view) calibration?

Every calibration face is re-measured from its frame with the top-view measurement
of evaluate_top_view.py (YOLO mask, dark holes and stains handled, local table ring)
and simple rules are scored leave-one-capture-out (the face's own capture is never
in the training data):
  band on one feature, ellipse around the good faces (2 features), logistic
  regression (2-3 features), decision tree (depth 2) and the 1-NN of the live demo.
Perforated faces are measured like the others and also reported separately.

Output in <calibration>/separation/:
  1_features.png    every feature, good vs bad, with separability (0.5 none, 1 perfect)
  2_best_pairs.png  the most separating feature pairs
  3_gallery.jpg     the faces sorted by the best feature, label border
  features.csv, results.json
Usage: analyze_calibration_separation.py <calibration folder> [--weights detector.pt]
"""

import argparse
import csv
import itertools
import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze_second_dataset_colors import bgr_to_lab
from scripts.evaluate_top_view import (BAD_COLOR, FEATURES, GOOD_COLOR, INK, SURFACE, TEXT_COLOR, balanced, ellipse_rule,
                                       fit_band, gallery, held_out, knn_rule, measure, separability, style)

WEIGHTS = PROJECT_ROOT / "outputs2" / "yolo_runs" / "brick_seg_v3" / "weights" / "best.pt"
MIN_MATCH_IOU = 0.5


def box_iou(a: dict, b: dict) -> float:
    ax2, ay2, bx2, by2 = a["x"] + a["width"], a["y"] + a["height"], b["x"] + b["width"], b["y"] + b["height"]
    inter = max(0, min(ax2, bx2) - max(a["x"], b["x"])) * max(0, min(ay2, by2) - max(a["y"], b["y"]))
    return inter / (a["width"] * a["height"] + b["width"] * b["height"] - inter + 1e-6)


def model_rule(make, keys):
    """Wrap a scikit-learn classifier as a rule fitted on rows (features standardized)."""
    def fit(train):
        X = np.array([[r[k] for k in keys] for r in train])
        y = np.array([r["label"] == "good" for r in train])
        scaler = StandardScaler().fit(X)
        model = make().fit(scaler.transform(X), y)
        return lambda r: "good" if model.predict(scaler.transform([[r[k] for k in keys]]))[0] else "bad"
    return fit


def band_rule(key):
    def fit(train):
        low, high = fit_band([r[key] for r in train], [r["label"] for r in train])
        return lambda r: "good" if low <= r[key] <= high else "bad"
    return fit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--weights", type=Path, default=WEIGHTS)
    args = parser.parse_args()
    out = args.calibration / "separation"
    out.mkdir(exist_ok=True)
    data = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))
    detector = YOLO(str(args.weights))

    rows, frames = [], {}
    for photo in sorted({r["photo"] for r in data["rows"]}):
        frame = cv2.imread(str(args.calibration / "frames" / f"{photo}.jpg"))
        frames[photo] = frame
        result = detector.predict(frame, conf=0.5, retina_masks=True, verbose=False)[0]
        if result.masks is None:
            continue
        boxes = [{"x": int(x1), "y": int(y1), "width": int(x2 - x1), "height": int(y2 - y1)}
                 for x1, y1, x2, y2 in result.boxes.xyxy.cpu().numpy().round().astype(int)]
        all_masks = np.zeros(frame.shape[:2], np.uint8)
        for polygon in result.masks.xy:
            cv2.fillPoly(all_masks, [polygon.astype(np.int32)], 1)
        others = cv2.dilate(all_masks, np.ones((15, 15), np.uint8)).astype(bool)
        lab = bgr_to_lab(frame.reshape(-1, 3)).reshape(*frame.shape[:2], 3)
        for r in (r for r in data["rows"] if r["photo"] == photo):
            ious = [box_iou(r["bbox_px"], b) for b in boxes]
            best = int(np.argmax(ious))
            if ious[best] < MIN_MATCH_IOU:
                continue
            rows.append({"id": f"{photo}#{r['position']}", "photo": photo, "label": r["label"],
                         "polygon": result.masks.xy[best].tolist(), **measure(lab, result.masks.xy[best], others)})
    goods = sum(r["label"] == "good" for r in rows)
    print(f"{len(rows)} faces re-measured ({goods} good, {len(rows) - goods} bad; "
          f"{sum(r['face'] == 'perforated' for r in rows)} perforated)")

    keys = list(FEATURES)
    sep = {k: separability([r[k] for r in rows], [r["label"] for r in rows]) for k in keys}
    order = sorted(keys, key=lambda k: -sep[k])
    truth = [r["label"] for r in rows]
    by_capture = lambda r: r["photo"]
    results = {"faces": len(rows), "good": goods, "separability": {k: round(sep[k], 3) for k in order}, "rules": {}}

    rules = {f"band {k}": band_rule(k) for k in order[:6]}
    top = order[:4]
    for a, b in itertools.combinations(top, 2):
        rules[f"ellipse {a}+{b}"] = (lambda a, b: lambda t: ellipse_rule(t, [a, b]))(a, b)
    rules[f"logistic {'+'.join(order[:2])}"] = model_rule(lambda: LogisticRegression(class_weight="balanced"), order[:2])
    rules[f"logistic {'+'.join(order[:3])}"] = model_rule(lambda: LogisticRegression(class_weight="balanced"), order[:3])
    rules[f"tree depth 2 ({', '.join(order[:4])})"] = model_rule(
        lambda: DecisionTreeClassifier(max_depth=2, class_weight="balanced", random_state=0), order[:4])
    rules["1-NN L_med+C_med (live demo)"] = lambda t: knn_rule(t, ["L_med", "C_med"])
    for name, make in rules.items():
        results["rules"][name] = {"leave_one_capture_out": balanced(held_out(rows, by_capture, make), truth),
                                  "in_sample": balanced([make(rows)(r) for r in rows], truth)}

    figure, axes = plt.subplots(len(order), 1, figsize=(12, 1.15 * len(order) + 1))
    rng = np.random.default_rng(0)
    for axis, key in zip(axes, order):
        for label, color, marker, y in (("good", GOOD_COLOR, "o", 0.5), ("bad", BAD_COLOR, "^", -0.5)):
            for face, filled in (("solid", True), ("perforated", False)):
                pts = [r[key] for r in rows if r["label"] == label and r["face"] == face]
                axis.scatter(pts, y + rng.uniform(-0.22, 0.22, len(pts)), s=40, marker=marker,
                             facecolors=color if filled else "none", edgecolors=color, linewidths=1.3)
        axis.set_yticks([0.5, -0.5], ["good", "bad"])
        axis.set_ylim(-1, 1)
        axis.set_title(f"{FEATURES[key]}   separability {sep[key]:.2f}", loc="left", fontsize=9, color=INK)
        style(axis)
    figure.suptitle("Calibration faces, each feature alone (filled = solid face, hollow = perforated face)",
                    color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "1_features.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    pairs = list(itertools.combinations(top, 2))[:4]
    figure, axes = plt.subplots(2, 2, figsize=(14, 10))
    for axis, (xk, yk) in zip(axes.ravel(), pairs):
        for r in rows:
            color = GOOD_COLOR if r["label"] == "good" else BAD_COLOR
            marker = "o" if r["label"] == "good" else "^"
            axis.scatter(r[xk], r[yk], s=70, marker=marker, color=color if r["face"] == "solid" else "none",
                         edgecolors=color, linewidths=1.4, zorder=3)
            axis.annotate(r["id"].replace("cal", ""), (r[xk], r[yk]), xytext=(3, 3), textcoords="offset points",
                          fontsize=6.5, color=TEXT_COLOR)
        axis.set_xlabel(FEATURES[xk], color=TEXT_COLOR)
        axis.set_ylabel(FEATURES[yk], color=TEXT_COLOR)
        style(axis)
    figure.suptitle("Best feature pairs. Blue circle = good, orange triangle = bad; hollow = perforated face",
                    color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "2_best_pairs.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    best = order[0]
    gallery(sorted(rows, key=lambda r: r[best]), frames, out / "3_gallery.jpg",
            lambda r: f"{r['id']} {r['label'][0].upper()} {best} {r[best]:.1f} {r['face'][0]}")

    fields = ["id", "label", "face", *keys, "holes_share"]
    with (out / "features.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("separability:")
    for k in order:
        print(f"  {FEATURES[k]:22s} {sep[k]:.2f}")
    print("rules (balanced accuracy, leave-one-capture-out | in-sample):")
    for name, ev in sorted(results["rules"].items(), key=lambda kv: -kv[1]["leave_one_capture_out"]["balanced_accuracy"]):
        v, s = ev["leave_one_capture_out"], ev["in_sample"]
        print(f"  {name:48s} {v['correct']:2d}/{v['n']} bal {v['balanced_accuracy']:.2f} "
              f"(G {v['good_recall']:.2f} B {v['bad_recall']:.2f}) | in-sample bal {s['balanced_accuracy']:.2f}")
    print(f"output: {out}")


if __name__ == "__main__":
    main()

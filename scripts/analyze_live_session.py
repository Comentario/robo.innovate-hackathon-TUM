"""Diagnose a live session: why were bricks misclassified?

Re-runs the pipeline on every logged frame to get all color features and masks,
then compares the live bricks with the reference set:
  1. scene brightness (table L*) and camera gain, reference vs live;
  2. the classifier feature space (L* minus table, chroma) with live bricks;
  3. per-capture distances to the nearest good and bad reference brick;
  4. bright pixels inside the mask (wall seen through the brick holes);
  5. alternative feature sets scored on the live labels (diagnostic only:
     the live session is small, so this suggests a direction, not a model).

Usage: analyze_live_session.py outputs2/live/<session>
Writes <session>/analysis/.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.live_brick_classifier import REFERENCE_PATH, BrickClassifier, draw_result
from scripts.analyze_second_dataset_colors import bgr_to_lab

ALTERNATIVES = {
    "current: L* minus table, chroma": ["dL_wood", "C_med"],
    "table white balance: L*, chroma": ["wb_L", "wb_C"],
    "table white balance: L*, a*, b*": ["wb_L", "wb_a", "wb_b"],
    "raw L*, chroma": ["L_med", "C_med"],
}
HOLE_L_RISE = 15.0

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"
INK = "#0b0b0b"
SURFACE = "#fcfcfb"


def style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def table_lightness(image: np.ndarray) -> float:
    h = image.shape[0]
    return float(np.median(bgr_to_lab(image[h - 120:h - 20, 300:1600].reshape(-1, 3))[:, 0]))


def nearest_label(train: list[dict], test: dict, keys: list[str]) -> str:
    X = np.array([[r[k] for k in keys] for r in train])
    center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
    z = (np.array([test[k] for k in keys]) - center) / spread
    return train[int(np.argmin(np.linalg.norm((X - center) / spread - z, axis=1)))]["label"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    out = args.session / "analysis"
    out.mkdir(exist_ok=True)

    records = [json.loads(line) for line in (args.session / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    classifier = BrickClassifier()

    live = []
    for record in records:
        if not record["bricks"]:
            continue
        frame = cv2.imread(str(args.session / "frames" / f"{record['capture_id']}.jpg"))
        result = classifier.classify(frame)
        logged = {b["position"]: b for b in record["bricks"]}
        for brick in result["bricks"]:
            true_label = logged.get(brick["position"], {}).get("true_label")
            if true_label is None:
                continue
            mask = result["label_map"] == brick["mask_index"]
            lab = bgr_to_lab(frame[mask])
            # Holes in perforated faces show the wall: much brighter than the brick body.
            hole_share = float((lab[:, 0] > np.median(lab[:, 0]) + HOLE_L_RISE).mean())
            from scripts.analyze_second_dataset_colors import brick_features
            from scripts.evaluate_third_dataset import table_reference
            features = brick_features(frame[mask], table_reference(frame, [brick["bbox_px"]]))
            live.append({"capture_id": record["capture_id"], "label": true_label,
                         "prediction": brick["prediction"], "confidence": brick["confidence"],
                         "distance_to_good": brick["distance_to_good"], "distance_to_bad": brick["distance_to_bad"],
                         "gain": record["camera"]["gain"] if record["camera"] else None,
                         "table_L": table_lightness(frame), "hole_share": hole_share, **features})
        result["bricks"] = [{**b, "true_label": logged.get(b["position"], {}).get("true_label")} for b in result["bricks"]]
        cv2.imwrite(str(out / f"{record['capture_id']}_mask.jpg"), draw_result(frame, result))

    reference_table = [table_lightness(cv2.imread(str(PROJECT_ROOT / "Third_Dataset_Bricks" / f"{p}.jpg")))
                       for p in sorted({r["photo"] for r in reference})]

    # Alternative feature sets, scored on the live labels.
    scores = []
    for name, keys in ALTERNATIVES.items():
        predictions = [nearest_label(reference, b, keys) for b in live]
        good = [p for p, b in zip(predictions, live) if b["label"] == "good"]
        bad = [p for p, b in zip(predictions, live) if b["label"] == "bad"]
        scores.append({"features": name, "keys": keys,
                       "accuracy": round(np.mean([p == b["label"] for p, b in zip(predictions, live)]), 3),
                       "good_accepted": f"{good.count('good')}/{len(good)}",
                       "bad_rejected": f"{bad.count('bad')}/{len(bad)}"})

    summary = {
        "live_bricks": len(live),
        "live_correct": sum(b["prediction"] == b["label"] for b in live),
        "reference_table_L_median": round(float(np.median(reference_table)), 1),
        "live_table_L_median": round(float(np.median([b["table_L"] for b in live])), 1),
        "live_gain_values": sorted({b["gain"] for b in live if b["gain"] is not None}),
        "reference_gain": 0,
        "alternatives_on_live": scores,
        "bricks": live,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Figure 1: what the classifier sees.
    figure, axes = plt.subplots(1, 2, figsize=(15, 6))
    for axis, (xk, yk, title) in zip(axes, [("dL_wood", "C_med", "Classifier features (current)"),
                                            ("wb_L", "wb_C", "Same bricks, table white balance")]):
        for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
            ref = [r for r in reference if r["label"] == label]
            axis.scatter([r[xk] for r in ref], [r[yk] for r in ref], s=30, c=color, marker=marker,
                         alpha=0.25, edgecolors="none", label=f"reference {label}")
            now = [b for b in live if b["label"] == label]
            axis.scatter([b[xk] for b in now], [b[yk] for b in now], s=90, c=color, marker=marker,
                         edgecolors=INK, linewidths=1.2, label=f"live {label}", zorder=3)
            wrong = [b for b in now if b["prediction"] != b["label"]]
            axis.scatter([b[xk] for b in wrong], [b[yk] for b in wrong], s=220, facecolors="none",
                         edgecolors=INK, linewidths=1.0, linestyle="--", zorder=2,
                         label="live misclassified" if label == "good" else None)
        axis.set_title(title, color=INK, fontsize=11)
        axis.set_xlabel({"dL_wood": "L* minus table L*", "wb_L": "L* after table white balance"}[xk], color=TEXT_COLOR, fontsize=9)
        axis.set_ylabel({"C_med": "Chroma C*", "wb_C": "Chroma C* after table white balance"}[yk], color=TEXT_COLOR, fontsize=9)
        style(axis)
    axes[0].legend(frameon=False, fontsize=8, loc="lower left")
    figure.text(0.5, 0.01, "Faded = reference photos (Third_Dataset_Bricks). Solid = live captures. Dashed ring = misclassified.",
                ha="center", color=TEXT_COLOR, fontsize=9)
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(out / "1_feature_space.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 2: scene brightness and gain.
    figure, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    axes[0].hist(reference_table, bins=10, color="#b5b4ad", label="reference photos")
    axes[0].hist([b["table_L"] for b in live], bins=10, color=GOOD_COLOR, label="live captures")
    axes[0].set_xlabel("Table lightness L* (same table, same camera exposure)", color=TEXT_COLOR, fontsize=9)
    axes[0].set_ylabel("Photos", color=TEXT_COLOR, fontsize=9)
    axes[0].set_title("The scene was much darker live", color=INK, fontsize=11)
    axes[0].legend(frameon=False, fontsize=9)
    style(axes[0])
    axes[1].bar(["reference", "live"], [0, summary["live_gain_values"][0] if summary["live_gain_values"] else 0],
                color=["#b5b4ad", GOOD_COLOR], width=0.5)
    axes[1].set_ylabel("Camera gain", color=TEXT_COLOR, fontsize=9)
    axes[1].set_title("Gain was not at the reference value", color=INK, fontsize=11)
    style(axes[1])
    figure.tight_layout()
    figure.savefig(out / "2_scene_brightness_gain.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 3: per capture, nearest good vs nearest bad distance.
    figure, axis = plt.subplots(figsize=(14, 5))
    x = np.arange(len(live))
    axis.bar(x - 0.2, [b["distance_to_good"] for b in live], 0.4, color=GOOD_COLOR, label="distance to nearest good reference")
    axis.bar(x + 0.2, [b["distance_to_bad"] for b in live], 0.4, color=BAD_COLOR, label="distance to nearest bad reference")
    axis.set_xticks(x, [f"{b['capture_id']}\n{b['label']}" + ("\nWRONG" if b["prediction"] != b["label"] else "") for b in live],
                    fontsize=7)
    axis.set_ylabel("Standardized distance (lower = more similar)", color=TEXT_COLOR, fontsize=9)
    axis.set_title("Each live capture: the shorter bar wins", color=INK, fontsize=11)
    axis.legend(frameon=False, fontsize=9)
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "3_distances_per_capture.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 4: holes.
    figure, axis = plt.subplots(figsize=(9, 5))
    for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
        now = [b for b in live if b["label"] == label]
        axis.scatter([b["hole_share"] for b in now], [b["C_med"] for b in now], s=80, c=color, marker=marker,
                     edgecolors="white", linewidths=1.2, label=f"live {label}")
    axis.set_xlabel("Share of mask pixels much brighter than the brick (wall through holes)", color=TEXT_COLOR, fontsize=9)
    axis.set_ylabel("Chroma C*", color=TEXT_COLOR, fontsize=9)
    axis.set_title("Do visible holes change the measured color?", color=INK, fontsize=11)
    axis.legend(frameon=False, fontsize=9)
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "4_holes_vs_chroma.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    print(f"live bricks: {summary['live_bricks']}, correct: {summary['live_correct']}")
    print(f"table L*: reference {summary['reference_table_L_median']}  live {summary['live_table_L_median']}")
    print(f"gain: reference 0  live {summary['live_gain_values']}")
    for s in scores:
        print(f"  {s['features']:36s} acc {s['accuracy']:.2f}  good {s['good_accepted']}  bad {s['bad_rejected']}")
    print(f"analysis: {out}")


if __name__ == "__main__":
    main()

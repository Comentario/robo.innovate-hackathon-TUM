"""Analyze a calibration and the live session classified with it.

Answers three questions:
  1. Which color features separate good from bad in the calibration?
  2. Does the live accuracy come from recognizing the calibrated bricks
     (memorization) or from a color rule that would work on new bricks?
       - self-check: each calibration capture classified without itself
         (one capture = one brick face, so this is "unseen brick face");
       - live: the session as logged (same bricks as the calibration);
       - live without its twin: each live brick classified after removing
         the calibration capture closest to it (very likely the same brick).
  3. Why did the misclassified bricks fail (nearest references, margins)?

Usage: analyze_calibrated_session.py <calibration folder> <live session folder>
Writes <live session>/calibration_analysis/.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.live_brick_classifier import add_relative_lightness


FEATURE_SETS = {"raw: L*, chroma": ["L_med", "C_med"], "table: L* - table, chroma": ["dL_wood", "C_med"],
                "table_ratio: L* / table, chroma": ["rel_L", "C_med"]}
SINGLE_FEATURES = {"L_med": "L* (lightness)", "dL_wood": "L* minus table", "rel_L": "L* relative to table",
                   "C_med": "Chroma C*"}

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
NEUTRAL = "#b5b4ad"
TEXT_COLOR = "#52514e"
INK = "#0b0b0b"
SURFACE = "#fcfcfb"


def style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(NEUTRAL)
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def nearest(train: list[dict], item: dict, keys: list[str]) -> tuple[dict, float, float]:
    """Nearest reference, plus distances to the nearest good and nearest bad."""
    X = np.array([[r[k] for k in keys] for r in train])
    center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
    z = (np.array([item[k] for k in keys]) - center) / spread
    d = np.linalg.norm((X - center) / spread - z, axis=1)
    labels = np.array([r["label"] for r in train])
    return train[int(np.argmin(d))], float(d[labels == "good"].min()), float(d[labels == "bad"].min())


def auc(values_good: list[float], values_bad: list[float]) -> float:
    g, b = np.array(values_good)[:, None], np.array(values_bad)[None, :]
    value = float((g > b).mean() + 0.5 * (g == b).mean())
    return max(value, 1 - value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    out = args.session / "calibration_analysis"
    out.mkdir(exist_ok=True)

    calibration = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))
    cal = [add_relative_lightness(r) for r in calibration["rows"]]
    live = []
    for line in (args.session / "log.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        for b in record["bricks"]:
            if b["true_label"] and all(b["features"].get(k) is not None for k in ("L_med", "dL_wood", "C_med")):
                live.append(add_relative_lightness(
                    {"id": f"{record['capture_id']}#{b['position']}", "label": b["true_label"],
                     "logged_prediction": b["prediction"], "scene_lightness": record.get("scene_lightness"),
                     **b["features"]}))

    metrics = {"calibration": str(args.calibration), "session": str(args.session),
               "calibration_bricks": {"good": sum(r["label"] == "good" for r in cal),
                                      "bad": sum(r["label"] == "bad" for r in cal)},
               "live_labeled_bricks": len(live),
               "logged_live_accuracy": round(np.mean([b["logged_prediction"] == b["label"] for b in live]), 3),
               "feature_sets": {}, "single_feature_separability": {}}

    # 1. Single-feature separability in the calibration.
    for key, name in SINGLE_FEATURES.items():
        metrics["single_feature_separability"][name] = {
            "auc": round(auc([r[key] for r in cal if r["label"] == "good"], [r[key] for r in cal if r["label"] == "bad"]), 3),
            "good_range": [round(min(r[key] for r in cal if r["label"] == "good"), 1),
                           round(max(r[key] for r in cal if r["label"] == "good"), 1)],
            "bad_range": [round(min(r[key] for r in cal if r["label"] == "bad"), 1),
                          round(max(r[key] for r in cal if r["label"] == "bad"), 1)]}

    # 2. Memorization check, per feature set.
    per_brick = {}
    for name, keys in FEATURE_SETS.items():
        self_check = []
        for photo in sorted({r["photo"] for r in cal}):
            train = [r for r in cal if r["photo"] != photo]
            for r in (r for r in cal if r["photo"] == photo):
                self_check.append(nearest(train, r, keys)[0]["label"] == r["label"])
        live_ok, twin_ok = [], []
        for b in live:
            ref, to_good, to_bad = nearest(cal, b, keys)
            live_ok.append(ref["label"] == b["label"])
            # Remove the closest calibration capture (the brick's own twin).
            twin = ref["photo"]
            ref2, _, _ = nearest([r for r in cal if r["photo"] != twin], b, keys)
            twin_ok.append(ref2["label"] == b["label"])
            per_brick.setdefault(b["id"], {})[name] = {
                "prediction": ref["label"], "nearest": f"{ref['photo']}#{ref['position']}",
                "distance_to_good": round(to_good, 3), "distance_to_bad": round(to_bad, 3),
                "prediction_without_twin": ref2["label"]}
        metrics["feature_sets"][name] = {
            "self_check_unseen_capture": round(float(np.mean(self_check)), 3),
            "live_same_bricks": round(float(np.mean(live_ok)), 3),
            "live_without_twin": round(float(np.mean(twin_ok)), 3),
            "live_errors": [b["id"] for b, ok in zip(live, live_ok) if not ok]}
    metrics["bricks"] = [{**b, "by_feature_set": per_brick[b["id"]]} for b in live]
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # Figure 1: feature space, both feature sets.
    figure, axes = plt.subplots(1, 3, figsize=(20, 6))
    for axis, (name, (xk, yk)) in zip(axes, FEATURE_SETS.items()):
        for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
            ref = [r for r in cal if r["label"] == label]
            axis.scatter([r[xk] for r in ref], [r[yk] for r in ref], s=120, c=color, marker=marker, alpha=0.3,
                         edgecolors="none", label=f"calibration {label}")
            now = [b for b in live if b["label"] == label]
            axis.scatter([b[xk] for b in now], [b[yk] for b in now], s=40, c=color, marker=marker,
                         edgecolors=INK, linewidths=0.8, label=f"live {label}", zorder=3)
        for b in live:
            info = per_brick[b["id"]][name]
            if info["prediction"] != b["label"]:
                axis.scatter([b[xk]], [b[yk]], s=260, facecolors="none", edgecolors=INK, linestyle="--", zorder=2)
                axis.annotate(b["id"], (b[xk], b[yk]), xytext=(6, 6), textcoords="offset points", fontsize=8, color=INK)
        axis.set_title(f"{name}  (live accuracy {metrics['feature_sets'][name]['live_same_bricks']:.0%})",
                       color=INK, fontsize=11)
        axis.set_xlabel(SINGLE_FEATURES[xk], color=TEXT_COLOR, fontsize=9)
        axis.set_ylabel(SINGLE_FEATURES[yk], color=TEXT_COLOR, fontsize=9)
        style(axis)
    axes[0].legend(frameon=False, fontsize=8)
    figure.text(0.5, 0.01, "Large faded = calibration captures (one per brick face). Small solid = live bricks. "
                "Dashed ring = misclassified with that feature set.", ha="center", color=TEXT_COLOR, fontsize=9)
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    figure.savefig(out / "1_feature_space.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 2: memorization check.
    figure, axis = plt.subplots(figsize=(10, 5))
    groups = ["self_check_unseen_capture", "live_without_twin", "live_same_bricks"]
    titles = ["calibration, each capture\nleft out (unseen face)", "live, closest calibration\ncapture removed",
              "live, as classified\n(same bricks)"]
    width = 0.26
    for i, (name, color) in enumerate(zip(FEATURE_SETS, ["#2a78d6", "#eb6834", "#1baf7a"])):
        values = [metrics["feature_sets"][name][g] for g in groups]
        bars = axis.bar(np.arange(3) + (i - 1) * width, values, width, color=color, label=name)
        for bar, v in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.0%}", ha="center", fontsize=8, color=TEXT_COLOR)
    axis.set_xticks(np.arange(3), titles, fontsize=8)
    axis.set_ylim(0, 1.08)
    axis.set_ylabel("Accuracy", color=TEXT_COLOR, fontsize=9)
    axis.set_title("Recognizing known bricks vs. a rule that generalizes", color=INK, fontsize=11)
    axis.legend(frameon=False, fontsize=8, loc="upper left")
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "2_memorization_check.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 3: single features.
    figure, axes = plt.subplots(1, 4, figsize=(19, 4.5))
    for axis, (key, name) in zip(axes, SINGLE_FEATURES.items()):
        for row, (label, color) in enumerate((("good", GOOD_COLOR), ("bad", BAD_COLOR))):
            values = [r[key] for r in cal if r["label"] == label]
            axis.scatter(values, np.full(len(values), row) + np.random.default_rng(row).uniform(-0.12, 0.12, len(values)),
                         s=60, c=color, edgecolors="white", linewidths=1.0)
        axis.set_yticks([0, 1], ["good", "bad"])
        axis.set_ylim(-0.6, 1.6)
        axis.set_title(f"{name}  (separability {metrics['single_feature_separability'][name]['auc']:.2f})",
                       color=INK, fontsize=10)
        style(axis)
    figure.suptitle("Calibration bricks, one feature at a time (0.5 = no separation, 1.0 = perfect)",
                    color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "3_single_features.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Figure 4: one row per live brick, how clearly it was decided.
    figure, axes = plt.subplots(1, len(FEATURE_SETS), figsize=(6 * len(FEATURE_SETS), 0.28 * len(live) + 2),
                                sharey=True)
    y = np.arange(len(live))[::-1]
    for axis, name in zip(axes, FEATURE_SETS):
        margins = [per_brick[b["id"]][name]["distance_to_bad"] - per_brick[b["id"]][name]["distance_to_good"]
                   for b in live]
        colors = [GOOD_COLOR if b["label"] == "good" else BAD_COLOR for b in live]
        axis.barh(y, margins, color=colors, height=0.7)
        for yi, m, b in zip(y, margins, live):
            if per_brick[b["id"]][name]["prediction"] != b["label"]:
                axis.text(m + (0.05 if m >= 0 else -0.05), yi, "WRONG", va="center",
                          ha="left" if m >= 0 else "right", fontsize=7, color=INK, weight="bold")
        axis.axvline(0, color=INK, linewidth=1)
        axis.set_title(f"{name}\n{metrics['feature_sets'][name]['live_same_bricks']:.0%} correct", color=INK, fontsize=10)
        axis.set_xlabel("<- predicted BAD        margin        predicted GOOD ->", color=TEXT_COLOR, fontsize=8)
        style(axis)
    axes[0].set_yticks(y, [f"{b['id']} ({b['label']})" for b in live], fontsize=7)
    figure.suptitle("Each live brick: bar color = true label (blue good, orange bad). "
                    "A blue bar must point right and an orange bar left; short bars = undecided.",
                    color=INK, fontsize=10)
    figure.tight_layout()
    figure.savefig(out / "4_decision_per_brick.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    print(json.dumps({k: v for k, v in metrics.items() if k != "bricks"}, indent=2))
    print(f"analysis: {out}")


if __name__ == "__main__":
    main()

"""Which color features separate good from bad? Honest evaluation on a calibration.

Every brick of the calibration and of a live session classified with it is
re-measured from its saved frame and saved box (same MobileSAM masks as live).
Per brick: L* and C* as median and as mode (base color, robust to large stains),
a*, hue, and lightness relative to the table (difference and ratio).

Models compared:
  - 1-nearest-neighbor on several feature sets;
  - "band" rule on a single lightness: good if A <= L* <= B, with A and B
    chosen on the training bricks (good bricks are in the middle range).

Three scores per model:
  honest       each calibration capture classified without itself (unseen brick face)
  live         live bricks against the whole calibration (same bricks)
  live w/o twin  live bricks after removing their closest calibration capture

Usage: evaluate_calibration_features.py <calibration folder> <live session folder>
Writes <calibration>/feature_evaluation/.
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

from scripts.analyze_second_dataset_colors import bgr_to_lab
from scripts.run_mobile_sam import MODEL_PATH, segment, to_corners
from scripts.visualize_pipeline_steps import histogram_mode
from ultralytics import SAM

FEATURE_SETS = {
    "L median": ["L_med"],
    "L mode": ["L_mode"],
    "L mode, ratio to table": ["rL_mode"],
    "L median + C median (raw)": ["L_med", "C_med"],
    "L mode + C mode": ["L_mode", "C_mode"],
    "L - table + C (table, current)": ["dL_med", "C_med"],
    "L ratio + C (table_ratio)": ["rL_med", "C_med"],
    "L mode ratio + C mode": ["rL_mode", "C_mode"],
    "L mode + C mode + a*": ["L_mode", "C_mode", "a_mode"],
    "L mode + C mode + hue": ["L_mode", "C_mode", "hue"],
}
BAND_FEATURES = {"band on L median": "L_med", "band on L mode": "L_mode", "band on L mode ratio": "rL_mode"}

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
NEUTRAL = "#b5b4ad"
TEXT_COLOR = "#52514e"
INK = "#0b0b0b"
SURFACE = "#fcfcfb"


def relative_lightness(L: float, table_L: float) -> float:
    ratio = ((L + 16) / 116) ** 3 / ((table_L + 16) / 116) ** 3
    return float(116 * np.cbrt(ratio) - 16)


def measure_frame(sam: SAM, frame: np.ndarray, items: list[dict]) -> list[dict]:
    """Re-measure the given bricks of one frame from their saved boxes."""
    boxes = [it["bbox_px"] for it in items]
    label_map = segment(sam, frame, [to_corners(b) for b in boxes])
    lab = bgr_to_lab(frame.reshape(-1, 3)).reshape(frame.shape)
    bottom = max(b["y"] + b["height"] for b in boxes)
    x1, x2 = min(b["x"] for b in boxes), max(b["x"] + b["width"] for b in boxes)
    table_L = float(np.median(lab[bottom + 25:min(frame.shape[0], bottom + 140), x1:x2, 0]))
    out = []
    for index, item in enumerate(items, 1):
        mask = label_map == index
        if mask.sum() < 500:
            continue
        L, a, b = lab[..., 0][mask], lab[..., 1][mask], lab[..., 2][mask]
        C = np.hypot(a, b)
        f = {"L_med": float(np.median(L)), "L_mode": histogram_mode(L),
             "C_med": float(np.median(C)), "C_mode": histogram_mode(C),
             "a_mode": histogram_mode(a), "hue": float(np.degrees(np.arctan2(np.median(b), np.median(a)))),
             "table_L": table_L}
        f["dL_med"] = f["L_med"] - table_L
        f["rL_med"] = relative_lightness(f["L_med"], table_L)
        f["rL_mode"] = relative_lightness(f["L_mode"], table_L)
        out.append({**item, **f})
    return out


def nearest(train: list[dict], item: dict, keys: list[str]) -> dict:
    X = np.array([[r[k] for k in keys] for r in train])
    center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
    z = (np.array([item[k] for k in keys]) - center) / spread
    return train[int(np.argmin(np.linalg.norm((X - center) / spread - z, axis=1)))]


def fit_band(train: list[dict], key: str) -> tuple[float, float]:
    """Interval [A, B] of `key` that classifies the most training bricks correctly."""
    values = sorted({r[key] for r in train})
    best, band = -1.0, (values[0], values[-1])
    for i, low in enumerate(values):
        for high in values[i:]:
            score = np.mean([(low <= r[key] <= high) == (r["label"] == "good") for r in train])
            if score > best:
                best, band = score, (low, high)
    return band


def predict(model: str, train: list[dict], item: dict) -> str:
    if model in BAND_FEATURES:
        low, high = fit_band(train, BAND_FEATURES[model])
        return "good" if low <= item[BAND_FEATURES[model]] <= high else "bad"
    return nearest(train, item, FEATURE_SETS[model])["label"]


def style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(NEUTRAL)
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(axis="x", color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    out = args.calibration / "feature_evaluation"
    out.mkdir(exist_ok=True)
    sam = SAM(str(MODEL_PATH))

    calibration = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))
    cal = []
    for photo in sorted({r["photo"] for r in calibration["rows"]}):
        items = [{"id": f"{photo}#{r['position']}", "capture": photo, "label": r["label"], "bbox_px": r["bbox_px"]}
                 for r in calibration["rows"] if r["photo"] == photo]
        cal += measure_frame(sam, cv2.imread(str(args.calibration / "frames" / f"{photo}.jpg")), items)

    live = []
    for line in (args.session / "log.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        items = [{"id": f"{record['capture_id']}#{b['position']}", "capture": record["capture_id"],
                  "label": b["true_label"], "bbox_px": b["bbox_px"]}
                 for b in record["bricks"] if b["true_label"]]
        if items:
            live += measure_frame(sam, cv2.imread(str(args.session / "frames" / f"{record['capture_id']}.jpg")), items)

    results = {}
    for model in [*FEATURE_SETS, *BAND_FEATURES]:
        honest = [predict(model, [r for r in cal if r["capture"] != c["capture"]], c) == c["label"] for c in cal]
        same = [predict(model, cal, b) for b in live]
        keys = FEATURE_SETS.get(model, [BAND_FEATURES.get(model)])
        no_twin = []
        for b in live:
            twin = nearest(cal, b, ["L_mode", "C_mode"])["capture"]
            no_twin.append(predict(model, [r for r in cal if r["capture"] != twin], b) == b["label"])
        results[model] = {
            "features": keys,
            "honest": round(float(np.mean(honest)), 3),
            "live_same_bricks": round(float(np.mean([p == b["label"] for p, b in zip(same, live)])), 3),
            "live_without_twin": round(float(np.mean(no_twin)), 3),
            "live_errors": [b["id"] for p, b in zip(same, live) if p != b["label"]],
        }
    for model in BAND_FEATURES:
        results[model]["band_on_full_calibration"] = [round(v, 1) for v in fit_band(cal, BAND_FEATURES[model])]

    data = {"calibration": str(args.calibration), "session": str(args.session),
            "calibration_bricks": len(cal), "live_bricks": len(live), "results": results,
            "calibration_measurements": [{k: v for k, v in r.items() if k != "bbox_px"} for r in cal],
            "live_measurements": [{k: v for k, v in r.items() if k != "bbox_px"} for r in live]}
    (out / "results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Chart 1: three scores per model, sorted by the honest score.
    order = sorted(results, key=lambda m: (results[m]["honest"], results[m]["live_same_bricks"]))
    figure, axis = plt.subplots(figsize=(12, 0.62 * len(order) + 1.8))
    y = np.arange(len(order))
    for offset, (key, color, name) in zip((-0.27, 0, 0.27), [
            ("honest", INK, "honest: unseen brick face"),
            ("live_without_twin", NEUTRAL, "live, closest calibration capture removed"),
            ("live_same_bricks", GOOD_COLOR, "live, same bricks as calibration")]):
        values = [results[m][key] for m in order]
        axis.barh(y + offset, values, 0.25, color=color, label=name)
        for yi, v in zip(y + offset, values):
            axis.text(v + 0.005, yi, f"{v:.0%}", va="center", fontsize=7, color=TEXT_COLOR)
    axis.set_yticks(y, order, fontsize=8)
    axis.set_xlim(0, 1.1)
    axis.set_xlabel("Accuracy", color=TEXT_COLOR, fontsize=9)
    axis.set_title("Feature sets on the calibration bricks (sorted by the honest score)", color=INK, fontsize=11)
    axis.legend(frameon=False, fontsize=8, loc="lower right")
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "1_scores.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    # Chart 2: every brick on the L* mode axis, with the band fitted on the calibration.
    figure, axes = plt.subplots(2, 1, figsize=(12, 5.5), sharex=True)
    low, high = fit_band(cal, "L_mode")
    for axis, (rows, title) in zip(axes, [(cal, "Calibration bricks"), (live, "Live bricks")]):
        axis.axvspan(low, high, color="#e8e7e2", zorder=0)
        rng = np.random.default_rng(0)
        for label, color, marker, row in (("good", GOOD_COLOR, "o", 1), ("bad", BAD_COLOR, "^", 0)):
            values = [r["L_mode"] for r in rows if r["label"] == label]
            axis.scatter(values, row + rng.uniform(-0.15, 0.15, len(values)), s=55, c=color, marker=marker,
                         edgecolors="white", linewidths=1.0, zorder=3)
        axis.set_yticks([0, 1], ["bad", "good"])
        axis.set_ylim(-0.6, 1.6)
        axis.set_title(f"{title}: grey band = good range fitted on the calibration ({low:.1f} - {high:.1f})",
                       loc="left", color=INK, fontsize=10)
        style(axis)
    axes[1].set_xlabel("L* mode (base lightness of the brick)", color=TEXT_COLOR, fontsize=9)
    figure.tight_layout()
    figure.savefig(out / "2_lightness_band.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)

    print(f"calibration bricks {len(cal)}, live bricks {len(live)}")
    print(f"{'model':34s} honest  live w/o twin  live same")
    for m in sorted(results, key=lambda m: -results[m]["honest"]):
        r = results[m]
        print(f"{m:34s} {r['honest']:5.0%}  {r['live_without_twin']:10.0%}  {r['live_same_bricks']:8.0%}"
              f"   errors {r['live_errors'] if len(r['live_errors']) <= 5 else len(r['live_errors'])}")
    for m in BAND_FEATURES:
        print(f"{m}: band on full calibration {results[m]['band_on_full_calibration']}")
    print(f"results: {out}")


if __name__ == "__main__":
    main()

"""Which color features separate good from bad bricks in one calibration + session?

Every labeled brick of the calibration and of the live session is re-measured
from its saved frame and box (MobileSAM mask, holes and lit top edge excluded,
as in the live classifier). Features: L* and C* (mode and median), a*, b*, hue,
light stains, dark specks, L* spread.

Output in <session>/feature_separation/:
  1_single_features.png  one strip per feature, every brick, with its
                         separability (0.5 = none, 1.0 = perfect); good bricks
                         in the middle range still score low on one feature
  2_pairs.png            the most useful feature pairs, bricks labeled by id
  features.csv           all numbers per brick
Usage: diagnose_feature_separation.py <calibration folder> <live session folder>
"""

import argparse
import csv
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
from scripts.live_brick_classifier import histogram_mode, surface_features
from scripts.run_mobile_sam import MODEL_PATH, segment, to_corners
from ultralytics import SAM

FEATURES = {
    "L_mode": "L* mode (lightness)", "L_med": "L* median", "C_mode": "C* mode (chroma)",
    "C_med": "C* median", "a_med": "a* (red)", "b_med": "b* (yellow)", "hue": "hue angle",
    "stain_share": "light stain share", "speck_share": "dark speck share", "L_iqr": "L* spread",
}
PAIRS = [("L_mode", "C_mode"), ("a_med", "b_med"), ("L_mode", "hue"), ("C_mode", "hue")]
GOOD_COLOR, BAD_COLOR = "#2a78d6", "#eb6834"
TEXT_COLOR, INK, SURFACE = "#52514e", "#0b0b0b", "#fcfcfb"


def measure_frame(sam, frame, items):
    label_map = segment(sam, frame, [to_corners(it["bbox_px"]) for it in items])
    out = []
    for index, item in enumerate(items, 1):
        mask = label_map == index
        if mask.sum() < 500:
            continue
        surface = surface_features(frame, mask, item["bbox_px"])
        lab = bgr_to_lab(frame[mask])
        L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
        base = surface["L_mode"]
        out.append({**item, **surface,
                    "L_med": float(np.median(L)), "C_med": float(np.median(np.hypot(a, b))),
                    "a_med": float(np.median(a)), "b_med": float(np.median(b)),
                    "hue": float(np.degrees(np.arctan2(np.median(b), np.median(a)))),
                    "speck_share": float((L < base - 12).mean()),
                    "L_iqr": float(np.subtract(*np.percentile(L, [75, 25])))})
    return out


def separability(rows, key):
    g = np.array([r[key] for r in rows if r["label"] == "good"])[:, None]
    b = np.array([r[key] for r in rows if r["label"] == "bad"])[None, :]
    value = float((g > b).mean() + 0.5 * (g == b).mean())
    return max(value, 1 - value)


def style(axis):
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    out = args.session / "feature_separation"
    out.mkdir(exist_ok=True)
    sam = SAM(str(MODEL_PATH))

    calibration = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))
    rows = []
    for photo in sorted({r["photo"] for r in calibration["rows"]}):
        items = [{"id": f"{photo}#{r['position']}", "source": "calibration", "label": r["label"], "bbox_px": r["bbox_px"]}
                 for r in calibration["rows"] if r["photo"] == photo]
        rows += measure_frame(sam, cv2.imread(str(args.calibration / "frames" / f"{photo}.jpg")), items)
    for line in (args.session / "log.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        items = [{"id": record["capture_id"] + "#" + str(b["position"]), "source": "live", "label": b["true_label"],
                  "bbox_px": b["bbox_px"]} for b in record["bricks"] if b["true_label"]]
        if items:
            rows += measure_frame(sam, cv2.imread(str(args.session / "frames" / f"{record['capture_id']}.jpg")), items)

    scores = {k: separability(rows, k) for k in FEATURES}
    order = sorted(FEATURES, key=lambda k: -scores[k])

    figure, axes = plt.subplots(len(order), 1, figsize=(12, 1.25 * len(order) + 1))
    rng = np.random.default_rng(0)
    for axis, key in zip(axes, order):
        for label, color, marker, y in (("good", GOOD_COLOR, "o", 0.5), ("bad", BAD_COLOR, "^", -0.5)):
            for source, filled in (("calibration", False), ("live", True)):
                pts = [r for r in rows if r["label"] == label and r["source"] == source]
                axis.scatter([r[key] for r in pts], y + rng.uniform(-0.2, 0.2, len(pts)), s=55, marker=marker,
                             facecolors=color if filled else "none", edgecolors=color, linewidths=1.4)
        axis.set_yticks([0.5, -0.5], ["good", "bad"])
        axis.set_ylim(-1, 1)
        axis.set_title(f"{FEATURES[key]}   separability {scores[key]:.2f}", loc="left", fontsize=9, color=INK)
        style(axis)
    figure.suptitle("Each feature alone (hollow = calibration, filled = live)", color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "1_single_features.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    figure, axes = plt.subplots(2, 2, figsize=(15, 11))
    for axis, (xk, yk) in zip(axes.ravel(), PAIRS):
        for r in rows:
            color = GOOD_COLOR if r["label"] == "good" else BAD_COLOR
            marker = "o" if r["label"] == "good" else "^"
            axis.scatter(r[xk], r[yk], s=80, marker=marker, facecolors=color if r["source"] == "live" else "none",
                         edgecolors=color, linewidths=1.5, zorder=3)
            note = r["id"] + (" P" if r["face"] == "perforated" else "") + (" S" if r["stain_share"] >= 0.1 else "")
            axis.annotate(note, (r[xk], r[yk]), xytext=(4, 4), textcoords="offset points", fontsize=7, color=TEXT_COLOR)
        axis.set_xlabel(FEATURES[xk], color=TEXT_COLOR, fontsize=9)
        axis.set_ylabel(FEATURES[yk], color=TEXT_COLOR, fontsize=9)
        style(axis)
    figure.suptitle("Feature pairs. Circle = good, triangle = bad; hollow = calibration, filled = live; "
                    "P = perforated face, S = stains >= 10%", color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "2_pairs.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    fields = ["id", "source", "label", "face", *FEATURES, "holes_share"]
    with (out / "features.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (r["source"], r["L_mode"])):
            writer.writerow({k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})

    print("separability (good vs bad, all bricks):")
    for key in order:
        print(f"  {FEATURES[key]:22s} {scores[key]:.2f}")
    print(f"\n{'id':10s} {'src':4s} {'label':5s} {'face':10s} " + " ".join(f"{k:>7s}" for k in ("L_mode", "C_mode", "a_med", "b_med", "hue", "stain_share")))
    for r in sorted(rows, key=lambda r: r["L_mode"]):
        print(f"{r['id']:10s} {r['source'][:4]:4s} {r['label']:5s} {r['face']:10s} " +
              " ".join(f"{r[k]:7.2f}" for k in ("L_mode", "C_mode", "a_med", "b_med", "hue", "stain_share")))
    print(f"\noutput: {out}")


if __name__ == "__main__":
    main()

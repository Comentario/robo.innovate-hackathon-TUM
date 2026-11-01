"""Good/bad color separation in the top-view photos, compared with the standing view.

Needs outputs2/top_view/bricks.json and labels.csv from top_view_marks.py (labels
g / b / ?; ? is left out). Each brick is measured inside its YOLO mask with a
top-view version of the live classifier features: holes are DARK here (belt or
carpet seen through them), so they are found below the brick base lightness;
light stains (L* > mode + 12) and dark specks are shares of the clean surface;
the carpet ring around the brick gives a local background lightness.

The same physical bricks appear in many photos and there is no brick id, so
leave-one-photo-out and leave-one-block-out (10 photos) still see the test brick
in training: scores are optimistic, a brick-level test needs a new capture.
Classes are unbalanced (about 1 good : 3 bad); bands are fitted for balanced
accuracy and balanced accuracy is reported.

Output in outputs2/top_view/analysis/:
  1_feature_separation.png  every feature, top view, with separability; standing
                            calibration separability for comparison
  2_lightness_chroma.png    L* median vs C* median, face type and stains marked
  3_gallery_by_lightness.jpg  brick crops sorted by L* median, label border
  4_band_errors.jpg         bricks the leave-one-photo-out band gets wrong
  5_light_per_photo.png     scene light (carpet L*) and brick L* along the session
  features.csv, results.json
Usage: evaluate_top_view.py [--standing-calibration outputs2/calibration/20261025_201100]
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
from scripts.live_brick_classifier import STAIN_L_RISE, STAIN_UNKNOWN_SHARE, histogram_mode
from scripts.run_mobile_sam import ERODE_PX
from scripts.top_view_marks import OUTPUT, SESSION, straight_crop

STANDING_CALIBRATION = PROJECT_ROOT / "outputs2" / "calibration" / "20261025_201100"
STANDING_BAND = (31.1, 34.4)
HOLE_BELOW_BASE = 20.0
HOLE_DILATE_PX = 9
PERFORATED_HOLE_SHARE = 0.04
RING_PX = (20, 60)
BLOCK = 10
FEATURES = {
    "L_med": "L* median", "L_mode": "L* mode", "C_med": "C* median (chroma)", "C_mode": "C* mode",
    "a_med": "a* (red)", "b_med": "b* (yellow)", "hue": "hue angle", "dL_bg": "L* minus carpet",
    "stain_share": "light stain share", "speck_share": "dark speck share", "L_iqr": "L* spread",
}
STANDING_KEYS = {"L_med": "L_med", "L_mode": "L_mode", "C_med": "C_med", "C_mode": "C_mode",
                 "a_med": "a_med", "b_med": "b_med", "hue": "h_med", "L_iqr": "L_iqr"}
GOOD_COLOR, BAD_COLOR = "#2a78d6", "#eb6834"
TEXT_COLOR, INK, SURFACE, GRID = "#52514e", "#0b0b0b", "#fcfcfb", "#e8e7e2"


def measure(lab: np.ndarray, polygon: np.ndarray, others: np.ndarray) -> dict:
    mask = np.zeros(lab.shape[:2], np.uint8)
    cv2.fillPoly(mask, [polygon.astype(np.int32)], 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ERODE_PX + 1, 2 * ERODE_PX + 1))
    region = cv2.erode(mask, kernel).astype(bool)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    base = histogram_mode(L[region])

    holes = region & (L < base - HOLE_BELOW_BASE)
    hole_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * HOLE_DILATE_PX + 1,) * 2)
    clean = region & ~cv2.dilate(holes.astype(np.uint8), hole_kernel).astype(bool)
    if clean.sum() < 0.3 * region.sum():
        clean = region
    Lc, ac, bc = L[clean], a[clean], b[clean]
    L_mode = histogram_mode(Lc)

    near = cv2.dilate(mask, np.ones((2 * RING_PX[1] + 1,) * 2, np.uint8)).astype(bool)
    inner = cv2.dilate(mask, np.ones((2 * RING_PX[0] + 1,) * 2, np.uint8)).astype(bool)
    ring = near & ~inner & ~others
    bg_L = float(np.median(L[ring])) if ring.sum() > 500 else float("nan")
    L_med = float(np.median(Lc))
    return {"L_med": L_med, "L_mode": L_mode, "C_med": float(np.median(np.hypot(ac, bc))),
            "C_mode": histogram_mode(np.hypot(ac, bc)), "a_med": float(np.median(ac)), "b_med": float(np.median(bc)),
            "hue": float(np.degrees(np.arctan2(np.median(bc), np.median(ac)))), "bg_L": bg_L, "dL_bg": L_med - bg_L,
            "stain_share": float((Lc > L_mode + STAIN_L_RISE).mean()),
            "speck_share": float((Lc < L_mode - STAIN_L_RISE).mean()),
            "L_iqr": float(np.subtract(*np.percentile(Lc, [75, 25]))),
            "holes_share": float(holes.sum() / max(1, region.sum())),
            "face": "perforated" if holes.sum() / max(1, region.sum()) >= PERFORATED_HOLE_SHARE else "solid"}


def separability(values, labels) -> float:
    g = np.array([v for v, l in zip(values, labels) if l == "good"])[:, None]
    b = np.array([v for v, l in zip(values, labels) if l == "bad"])[None, :]
    if not g.size or not b.size:
        return float("nan")
    value = float((g > b).mean() + 0.5 * (g == b).mean())
    return max(value, 1 - value)


def balanced(pred, labels) -> dict:
    pred, labels = np.array(pred), np.array(labels)
    good_recall = float((pred[labels == "good"] == "good").mean()) if (labels == "good").any() else float("nan")
    bad_recall = float((pred[labels == "bad"] == "bad").mean()) if (labels == "bad").any() else float("nan")
    return {"accuracy": round(float((pred == labels).mean()), 3), "balanced_accuracy": round((good_recall + bad_recall) / 2, 3),
            "good_recall": round(good_recall, 3), "bad_recall": round(bad_recall, 3),
            "correct": int((pred == labels).sum()), "n": int(len(labels))}


def fit_band(values, labels) -> tuple[float, float]:
    """Interval with the best balanced accuracy (good inside, bad outside)."""
    candidates = np.unique(np.round(values, 1))
    good = np.array([v for v, l in zip(values, labels) if l == "good"])
    bad = np.array([v for v, l in zip(values, labels) if l == "bad"])
    best, band = -1.0, (candidates[0], candidates[-1])
    for i, low in enumerate(candidates):
        for high in candidates[i:]:
            score = ((good >= low) & (good <= high)).mean() / 2 + (~((bad >= low) & (bad <= high))).mean() / 2
            if score > best:
                best, band = score, (float(low), float(high))
    return band


def ellipse_rule(train, keys):
    """Mahalanobis distance to the good class; threshold with the best balanced accuracy."""
    X = np.array([[r[k] for k in keys] for r in train])
    labels = np.array([r["label"] for r in train])
    good = X[labels == "good"]
    mean, inv = good.mean(axis=0), np.linalg.pinv(np.cov(good.T) + 1e-6 * np.eye(len(keys)))
    dist = np.sqrt(np.einsum("ij,jk,ik->i", X - mean, inv, X - mean))
    best, limit = -1.0, 0.0
    for t in np.unique(np.round(dist, 2)):
        pred = np.where(dist <= t, "good", "bad")
        score = balanced(pred, labels)["balanced_accuracy"]
        if score > best:
            best, limit = score, t
    return lambda r: "good" if np.sqrt((np.array([r[k] for k in keys]) - mean) @ inv @ (np.array([r[k] for k in keys]) - mean)) <= limit else "bad"


def knn_rule(train, keys):
    X = np.array([[r[k] for k in keys] for r in train])
    center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
    Z = (X - center) / spread
    return lambda r: train[int(np.argmin(np.linalg.norm(Z - (np.array([r[k] for k in keys]) - center) / spread, axis=1)))]["label"]


def held_out(rows, group, make_rule) -> list[str]:
    """Predict every row with a rule fitted on the rows of the other groups."""
    pred = [None] * len(rows)
    for g in sorted({group(r) for r in rows}):
        train = [r for r in rows if group(r) != g]
        rule = make_rule(train)
        for i, r in enumerate(rows):
            if group(r) == g:
                pred[i] = rule(r)
    return pred


def band_rule(key):
    def make(train):
        low, high = fit_band([r[key] for r in train], [r["label"] for r in train])
        return lambda r: "good" if low <= r[key] <= high else "bad"
    return make


def style(axis):
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)


def gallery(rows, frames, path, title_of, per_row=6, width=300):
    tiles = []
    for r in rows:
        crop = straight_crop(frames[r["photo"]], np.array(r["polygon"]))
        crop = cv2.resize(crop, (width, max(1, int(crop.shape[0] * width / crop.shape[1]))))[:110]
        crop = np.vstack([crop, np.full((110 - crop.shape[0], width, 3), 255, np.uint8)]) if crop.shape[0] < 110 else crop
        color = (214, 120, 42) if r["label"] == "good" else (52, 104, 235)
        crop = cv2.copyMakeBorder(crop, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=color)
        head = np.full((26, width + 10, 3), 255, np.uint8)
        cv2.putText(head, title_of(r), (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(np.vstack([head, crop]))
    if not tiles:
        return
    tiles += [np.full_like(tiles[0], 255)] * (-len(tiles) % per_row)
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, default=SESSION)
    parser.add_argument("--standing-calibration", type=Path, default=STANDING_CALIBRATION)
    args = parser.parse_args()
    out = OUTPUT / "analysis"
    out.mkdir(parents=True, exist_ok=True)

    bricks = json.loads((OUTPUT / "bricks.json").read_text(encoding="utf-8"))
    labels = {r["id"]: r["label"].strip() for r in csv.DictReader((OUTPUT / "labels.csv").open(encoding="utf-8-sig"))}
    light = {r["file"]: r for r in csv.DictReader((args.session / "log.csv").open(encoding="utf-8"))}
    frames, rows = {}, []
    for photo in sorted({b["photo"] for b in bricks}):
        frames[photo] = cv2.imread(str(args.session / photo))
        in_photo = [b for b in bricks if b["photo"] == photo]
        all_masks = np.zeros(frames[photo].shape[:2], np.uint8)
        for b in in_photo:
            cv2.fillPoly(all_masks, [np.array(b["polygon"], np.int32)], 1)
        others = cv2.dilate(all_masks, np.ones((15, 15), np.uint8)).astype(bool)
        lab = bgr_to_lab(frames[photo].reshape(-1, 3)).reshape(*frames[photo].shape[:2], 3)
        for b in in_photo:
            label = {"g": "good", "b": "bad"}.get(labels.get(b["id"], "?"))
            if label is None:
                continue
            number = int(photo[4:7])
            rows.append({**b, "label": label, "block": (number - 1) // BLOCK, "center_L": float(light[photo]["center_L"]),
                         **measure(lab, np.array(b["polygon"]), others)})
    print(f"{len(rows)} labeled bricks: {sum(r['label'] == 'good' for r in rows)} good, "
          f"{sum(r['label'] == 'bad' for r in rows)} bad, {sum(r['face'] == 'perforated' for r in rows)} perforated faces")

    solid = [r for r in rows if r["face"] == "solid"]
    clean = [r for r in solid if r["stain_share"] < STAIN_UNKNOWN_SHARE]
    results = {"counts": {"labeled": len(rows), "solid": len(solid), "solid_clean": len(clean)}}

    # Separability, top view vs standing calibration.
    standing = [r for r in json.loads((args.standing_calibration / "calibration.json").read_text(encoding="utf-8"))["rows"]
                if r.get("face", "solid") == "solid" and r.get("stain_share", 0) < STAIN_UNKNOWN_SHARE]
    sep_top = {k: separability([r[k] for r in clean], [r["label"] for r in clean]) for k in FEATURES}
    sep_standing = {k: separability([r[s] for r in standing], [r["label"] for r in standing])
                    for k, s in STANDING_KEYS.items() if s in standing[0]}
    results["separability_top_solid_clean"] = {k: round(v, 3) for k, v in sep_top.items()}
    results["separability_standing_calibration"] = {k: round(v, 3) for k, v in sep_standing.items()}

    # Rules: in-sample, leave-one-photo-out, leave-one-block-out.
    evaluations = {}
    rules = {"band L_med": band_rule("L_med"), "band L_mode": band_rule("L_mode"), "band C_med": band_rule("C_med"),
             "band dL_bg": band_rule("dL_bg"), "ellipse L_med+C_med": lambda t: ellipse_rule(t, ["L_med", "C_med"]),
             "ellipse L_med+C_med+hue": lambda t: ellipse_rule(t, ["L_med", "C_med", "hue"]),
             "1-NN L_med+C_med": lambda t: knn_rule(t, ["L_med", "C_med"])}
    for name, make in rules.items():
        truth = [r["label"] for r in clean]
        evaluations[name] = {
            "in_sample": balanced([make(clean)(r) for r in clean], truth),
            "leave_one_photo_out": balanced(held_out(clean, lambda r: r["photo"], make), truth),
            "leave_one_block_out": balanced(held_out(clean, lambda r: r["block"], make), truth)}
    standing_pred = ["good" if STANDING_BAND[0] <= r["L_med"] <= STANDING_BAND[1] else "bad" for r in clean]
    evaluations["standing calibration band L_med 31.1-34.4"] = {"transfer": balanced(standing_pred, [r["label"] for r in clean])}
    band_all = fit_band([r["L_med"] for r in clean], [r["label"] for r in clean])
    results["band_L_med_all_data"] = band_all
    results["rules_solid_clean"] = evaluations

    # Charts.
    order = sorted(FEATURES, key=lambda k: -sep_top[k])
    figure, axes = plt.subplots(len(order), 1, figsize=(12, 1.2 * len(order) + 1))
    rng = np.random.default_rng(0)
    for axis, key in zip(axes, order):
        for label, color, marker, y in (("good", GOOD_COLOR, "o", 0.5), ("bad", BAD_COLOR, "^", -0.5)):
            pts = [r[key] for r in clean if r["label"] == label]
            axis.scatter(pts, y + rng.uniform(-0.22, 0.22, len(pts)), s=22, marker=marker, color=color, alpha=0.75, linewidths=0)
        axis.set_yticks([0.5, -0.5], ["good", "bad"])
        axis.set_ylim(-1, 1)
        standing_note = f"   standing view {sep_standing[key]:.2f}" if key in sep_standing else ""
        axis.set_title(f"{FEATURES[key]}   separability top view {sep_top[key]:.2f}{standing_note}",
                       loc="left", fontsize=9, color=INK)
        style(axis)
    figure.suptitle("Top view, solid faces without large stains: each feature alone (0.5 = no separation, 1 = perfect)",
                    color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(out / "1_feature_separation.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(11, 8))
    for r in rows:
        color = GOOD_COLOR if r["label"] == "good" else BAD_COLOR
        marker = ("s" if r["face"] == "perforated" else "o") if r["label"] == "good" else ("D" if r["face"] == "perforated" else "^")
        stained = r["stain_share"] >= STAIN_UNKNOWN_SHARE
        axis.scatter(r["L_med"], r["C_med"], s=60, marker=marker, facecolors="none" if stained else color,
                     edgecolors=color, linewidths=1.3, alpha=0.85, zorder=3)
    for value in band_all:
        axis.axvline(value, color=TEXT_COLOR, linewidth=1, linestyle="--")
    axis.text(np.mean(band_all), axis.get_ylim()[1], f"best band on all data {band_all[0]:.1f}-{band_all[1]:.1f}",
              ha="center", va="bottom", fontsize=9, color=TEXT_COLOR)
    axis.set_xlabel("L* median (lightness)", color=TEXT_COLOR)
    axis.set_ylabel("C* median (chroma)", color=TEXT_COLOR)
    axis.set_title("Top view. Blue circle = good, orange triangle = bad; square / diamond = perforated face; "
                   "hollow = stains >= 12%", loc="left", fontsize=10, color=INK)
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "2_lightness_chroma.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    gallery(sorted(clean, key=lambda r: r["L_med"]), frames, out / "3_gallery_by_lightness.jpg",
            lambda r: f"{r['id']} {r['label'][0].upper()} L*{r['L_med']:.1f} C*{r['C_med']:.1f}")
    lopo = held_out(clean, lambda r: r["photo"], band_rule("L_med"))
    wrong = [r for r, p in zip(clean, lopo) if p != r["label"]]
    gallery(sorted(wrong, key=lambda r: r["L_med"]), frames, out / "4_band_errors.jpg",
            lambda r: f"{r['id']} true {r['label']} L*{r['L_med']:.1f} st{r['stain_share']:.0%}")

    figure, axis = plt.subplots(figsize=(13, 5))
    photos = sorted({r["photo"] for r in rows})
    x = {p: i for i, p in enumerate(photos)}
    bg = {p: np.nanmedian([r["bg_L"] for r in rows if r["photo"] == p]) for p in photos}
    axis.plot([x[p] for p in photos], [bg[p] for p in photos], color=TEXT_COLOR, linewidth=2, label="carpet L* (scene light)")
    for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
        pts = [r for r in clean if r["label"] == label]
        axis.scatter([x[r["photo"]] for r in pts], [r["L_med"] for r in pts], s=26, marker=marker, color=color,
                     alpha=0.8, label=f"{label} brick L* median", zorder=3)
    axis.set_xticks(range(0, len(photos), 5), [photos[i][4:7] for i in range(0, len(photos), 5)])
    axis.set_xlabel("photo (capture order)", color=TEXT_COLOR)
    axis.set_ylabel("L*", color=TEXT_COLOR)
    axis.legend(frameon=False, fontsize=9)
    axis.set_title("Scene light and brick lightness along the session", loc="left", fontsize=10, color=INK)
    style(axis)
    figure.tight_layout()
    figure.savefig(out / "5_light_per_photo.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    fields = ["id", "label", "face", "block", "center_L", "bg_L", *FEATURES, "holes_share"]
    with (out / "features.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(json.dumps(results["counts"]))
    print("separability (top / standing):")
    for k in order:
        print(f"  {FEATURES[k]:22s} {sep_top[k]:.2f}   {sep_standing.get(k, float('nan')):.2f}")
    print(f"best L_med band on all top data: {band_all}")
    for name, ev in evaluations.items():
        print(f"{name:42s} " + "  ".join(f"{s}: {v['correct']}/{v['n']} bal {v['balanced_accuracy']:.2f} "
                                         f"(G {v['good_recall']:.2f} B {v['bad_recall']:.2f})" for s, v in ev.items()))
    print(f"output: {out}")


if __name__ == "__main__":
    main()

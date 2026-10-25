"""Save every step of the brick pipeline for one photo, as numbered images.

  01 input photo
  02 Grounding DINO raw boxes
  03 row split: darkness profile across the row and the chosen cuts
  04 one box per brick
  05 MobileSAM raw masks (before cleaning)
  06 final masks: pixels claimed by two bricks removed, edges eroded
  07 measurement regions: brick masks (color) and table strip (light reference)
  08 L* (lightness) of every pixel inside the masks
  09 C* (chroma) of every pixel inside the masks
  10 per-brick numbers: median L*, median C*, table L*, L* minus table,
     L* relative to table, and the classification when a reference is given
  00 overview with all steps

Usage: visualize_pipeline_steps.py photo.jpg [--reference calibration.json]
Writes outputs2/pipeline_steps/<photo name>/.
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

from scripts.live_brick_classifier import (MIN_BRICK_COVERAGE, BrickClassifier, Reference,
                                           add_relative_lightness, histogram_mode)
from scripts.analyze_second_dataset_colors import bgr_to_lab, brick_features
from scripts.evaluate_third_dataset import MIN_MASK_COVERAGE, box_region, table_reference
from scripts.run_mobile_sam import segment, to_corners
from scripts.split_brick_row import BAND_MARGIN, darkness_profile, split_scene

OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "pipeline_steps"
BRICK_COLORS = [(214, 120, 42), (52, 104, 235), (122, 175, 27), (0, 161, 237),
                (164, 123, 232), (0, 131, 0), (214, 80, 98), (40, 40, 200)]
TABLE_BGR = (0, 200, 255)
INK = "#0b0b0b"
TEXT_COLOR = "#52514e"
SURFACE = "#fcfcfb"


def caption(image: np.ndarray, text: str) -> np.ndarray:
    canvas = image.copy()
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 70), (255, 255, 255), -1)
    cv2.putText(canvas, text, (20, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
    return canvas


def draw_boxes(image: np.ndarray, boxes: list[dict], numbered: bool) -> np.ndarray:
    canvas = image.copy()
    for i, b in enumerate(boxes, 1):
        color = BRICK_COLORS[(i - 1) % len(BRICK_COLORS)] if numbered else (60, 60, 230)
        cv2.rectangle(canvas, (b["x"], b["y"]), (b["x"] + b["width"], b["y"] + b["height"]), color, 4)
        if numbered:
            cv2.putText(canvas, str(i), (b["x"] + 10, b["y"] + 45), cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 4)
    return canvas


def masks_overlay(image: np.ndarray, masks: list[np.ndarray]) -> np.ndarray:
    overlay = image.copy()
    for i, mask in enumerate(masks):
        overlay[mask] = BRICK_COLORS[i % len(BRICK_COLORS)]
    return cv2.addWeighted(overlay, 0.5, image, 0.5, 0)


def value_map(image: np.ndarray, values: np.ndarray, region: np.ndarray, vmin: float, vmax: float,
              colormap: int) -> np.ndarray:
    """Pixels outside the region dimmed to gray; inside, the value as a color ramp."""
    gray = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    canvas = (gray * 0.35 + 255 * 0.65).astype(np.uint8)
    scaled = np.clip((values - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(scaled, colormap)
    canvas[region] = colored[region]
    return canvas


STAIN_L_RISE = 12.0
SPECK_L_DROP = 12.0
CANDIDATES = {
    "L_med": "L* median (current)",
    "L_mode": "L* mode (base color, ignores large stains)",
    "L_clean": "L* median without stains/specks",
    "C_med": "C* median (current)",
    "C_mode": "C* mode (base color)",
    "hue": "hue angle h (deg)",
    "a_med": "a* median (green-red)",
    "b_med": "b* median (blue-yellow)",
    "stain_frac": "light stain share",
    "speck_frac": "dark speck share",
    "L_iqr": "L* spread (IQR)",
}


def read_true_labels(session: Path, capture_id: str) -> dict[int, str]:
    for line in (session / "log.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["capture_id"] == capture_id:
            return {b["position"]: b["true_label"] for b in record["bricks"] if b["true_label"]}
    return {}


def candidate_features(pixels_lab: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    """Extra color features of one brick, plus its stain and speck pixel flags."""
    L, a, b = pixels_lab[:, 0], pixels_lab[:, 1], pixels_lab[:, 2]
    L_med = float(np.median(L))
    stain = L > L_med + STAIN_L_RISE
    speck = L < L_med - SPECK_L_DROP
    clean = ~(stain | speck)
    return {
        "L_med": L_med,
        "L_mode": histogram_mode(L),
        "L_clean": float(np.median(L[clean])),
        "C_med": float(np.median(np.hypot(a, b))),
        "C_mode": histogram_mode(np.hypot(a, b)),
        "hue": float(np.degrees(np.arctan2(np.median(b), np.median(a)))),
        "a_med": float(np.median(a)),
        "b_med": float(np.median(b)),
        "stain_frac": float(stain.mean()),
        "speck_frac": float(speck.mean()),
        "L_iqr": float(np.subtract(*np.percentile(L, [75, 25]))),
    }, stain, speck


def candidate_steps(frame, lab, chroma, masks, rows, true_labels, steps, out) -> None:
    """Steps 11-13: hue map, stains/specks, and every candidate feature per brick."""
    inside = np.any(masks, axis=0)
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    steps["11_hue"] = caption(value_map(frame, hue, inside, 45, 80, cv2.COLORMAP_COOL),
                              "11. Hue angle of each pixel: pink = redder (~45 deg), cyan = more yellow (~80 deg)")

    stains = frame.copy()
    stains = (cv2.cvtColor(cv2.cvtColor(stains, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) * 0.6).astype(np.uint8)
    features = []
    for i, mask in enumerate(masks, 1):
        f, stain, speck = candidate_features(lab[mask])
        ys, xs = np.nonzero(mask)
        stains[ys[stain], xs[stain]] = (255, 255, 0)
        stains[ys[speck], xs[speck]] = (255, 0, 255)
        features.append((i, f))
    steps["12_stains_specks"] = caption(
        stains, f"12. Cyan = light stains (L* > brick median + {STAIN_L_RISE:.0f}), "
                f"magenta = dark specks (L* < median - {SPECK_L_DROP:.0f})")

    figure, axes = plt.subplots(len(CANDIDATES), 1, figsize=(11, 1.15 * len(CANDIDATES) + 1.2))
    for axis, (key, name) in zip(axes, CANDIDATES.items()):
        values = {i: f[key] for i, f in features}
        goods = [v for i, v in values.items() if true_labels.get(i) == "good"]
        bads = [v for i, v in values.items() if true_labels.get(i) == "bad"]
        for i, v in values.items():
            label = true_labels.get(i)
            color = {"good": "#2a78d6", "bad": "#eb6834"}.get(label, "#b5b4ad")
            marker = {"good": "o", "bad": "^"}.get(label, "s")
            axis.scatter([v], [0], s=140, c=color, marker=marker, edgecolors="white", linewidths=1.2, zorder=3)
            axis.annotate(str(i), (v, 0), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=9)
        separates = bool(goods and bads and (max(goods) < min(bads) or min(goods) > max(bads)))
        axis.set_yticks([])
        axis.set_title(f"{name}:  {'one threshold separates this photo' if separates else 'groups overlap'}",
                       loc="left", fontsize=9, color=INK if separates else TEXT_COLOR,
                       weight="bold" if separates else "normal")
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(labelsize=8, colors=TEXT_COLOR)
        axis.margins(x=0.15)
    figure.suptitle("13. Candidate features of each brick in this photo (circle = true good, triangle = true bad; "
                    "number = brick)", fontsize=10, color=INK)
    figure.tight_layout()
    figure.savefig(out / "13_candidate_features.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    header = "brick | true | " + " | ".join(CANDIDATES)
    lines = [header] + [f"  {i}   | {true_labels.get(i, '?'):4s} | " + " | ".join(f"{f[k]:.3f}" for k in CANDIDATES)
                        for i, f in features]
    (out / "13_candidate_features.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path)
    parser.add_argument("--reference", type=Path, help="calibration.json to also classify the bricks")
    parser.add_argument("--log", type=Path,
                        help="live session folder: true labels are read for the capture named like the photo")
    args = parser.parse_args()

    frame = cv2.imread(str(args.image))
    out = OUTPUT_ROOT / args.image.stem
    out.mkdir(parents=True, exist_ok=True)
    classifier = BrickClassifier(reference=Reference.load(args.reference) if args.reference else None)
    steps = {}

    steps["01_input"] = caption(frame, "1. Input photo")

    raw_boxes = classifier.detect_boxes(frame)
    steps["02_grounding_dino"] = caption(draw_boxes(frame, raw_boxes, numbered=False),
                                         f"2. Grounding DINO: {len(raw_boxes)} raw boxes (stack box, halves, extras)")

    split = split_scene(frame, raw_boxes)
    boxes = [d["bbox_px"] for d in split["detections"]]
    x1, y1, x2, y2 = split["row_px"]
    height = y2 - y1
    band = frame[y1 + round(BAND_MARGIN * height):y2 - round(BAND_MARGIN * height), x1:x2]
    profile = darkness_profile(cv2.cvtColor(band.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB))
    canvas = frame.copy()
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (120, 120, 120), 3)
    base = y2 + 200
    peak = max(profile.max(), 1e-6)
    for x, v in enumerate(profile):
        cv2.line(canvas, (x1 + x, base), (x1 + x, base - int(v / peak * 170)), (60, 60, 230), 1)
    for left, right, kind in split["segments"]:
        for x in (left, right):
            cv2.line(canvas, (x, y1), (x, y2), (0, 0, 0) if kind == "brick" else (180, 180, 180), 3)
    method = ("joints = peaks of the red darkness profile; black lines = chosen cuts"
              if split["segments"] else "no joint partition found: Grounding DINO boxes used (fallback)")
    steps["03_row_split"] = caption(canvas, f"3. Row split: {method}")

    steps["04_brick_boxes"] = caption(draw_boxes(frame, boxes, numbered=True), f"4. One box per brick: {len(boxes)}")

    sam = classifier.segmenter(frame, bboxes=[to_corners(b) for b in boxes], verbose=False)[0]
    raw_masks = list(sam.masks.data.cpu().numpy().astype(bool))
    steps["05_sam_raw"] = caption(masks_overlay(frame, raw_masks), "5. MobileSAM raw masks, one per box")

    label_map = segment(classifier.segmenter, frame, [to_corners(b) for b in boxes])
    final_masks = [label_map == i for i in range(1, len(boxes) + 1)]
    # Same rule as the live classifier: a mask filling too little of its box is
    # background (or a piece cut by the frame) and is dropped, then bricks are
    # renumbered so positions match the live log.
    kept = [(b, m) for b, m in zip(boxes, final_masks)
            if m[b["y"]:b["y"] + b["height"], b["x"]:b["x"] + b["width"]].mean() >= MIN_BRICK_COVERAGE]
    dropped = len(boxes) - len(kept)
    boxes, final_masks = [b for b, _ in kept], [m for _, m in kept]
    steps["06_final_masks"] = caption(draw_boxes(masks_overlay(frame, final_masks), boxes, numbered=True),
                                      f"6. Final masks: shared pixels removed, edges eroded; {dropped} dropped, "
                                      f"{len(boxes)} bricks kept")

    regions = masks_overlay(frame, final_masks)
    ty = max(b["y"] + b["height"] for b in boxes)
    tx1, tx2 = min(b["x"] for b in boxes), max(b["x"] + b["width"] for b in boxes)
    table_rect = (tx1, ty + 25, tx2, min(frame.shape[0], ty + 140))
    cv2.rectangle(regions, table_rect[:2], table_rect[2:], TABLE_BGR, 6)
    cv2.putText(regions, "table strip = light reference only", (tx1, max(100, table_rect[1] - 15)),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, TABLE_BGR, 3)
    steps["07_regions"] = caption(regions, "7. Color is measured inside the masks; the table strip is a separate light meter")

    lab = bgr_to_lab(frame.reshape(-1, 3)).reshape(frame.shape)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    inside = np.any(final_masks, axis=0)
    steps["08_lightness"] = caption(value_map(frame, lab[..., 0], inside, 10, 60, cv2.COLORMAP_BONE),
                                    "8. L* (lightness) of each pixel inside the masks: dark = low, light = high")
    steps["09_chroma"] = caption(value_map(frame, chroma, inside, 15, 45, cv2.COLORMAP_INFERNO),
                                 "9. C* (chroma) of each pixel: dark = little color, bright = saturated")

    table = table_reference(frame, boxes)
    rows = []
    for i, (bbox, mask) in enumerate(zip(boxes, final_masks), 1):
        x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
        coverage = float(mask[y:y + h, x:x + w].mean())
        region = mask if coverage >= MIN_MASK_COVERAGE else box_region(bbox, frame.shape[:2])
        features = add_relative_lightness(brick_features(frame[region], table))
        prediction = classifier.reference.predict(features) if args.reference else None
        rows.append((i, features, prediction, lab[region][:, 0], chroma[region]))
    table_L = rows[0][1]["L_med"] - rows[0][1]["dL_wood"]

    # Step 10: distributions per brick and the resulting numbers.
    figure, axes = plt.subplots(1, 2, figsize=(16, 0.7 * len(rows) + 3))
    for axis, (index, label, unit) in zip(axes, [(3, "L* (lightness) of mask pixels", "L*"),
                                                 (4, "C* (chroma) of mask pixels", "C*")]):
        data = [r[index] for r in rows]
        parts = axis.boxplot(data, orientation="horizontal", widths=0.6, showfliers=False, patch_artist=True)
        for patch, (i, *_rest) in zip(parts["boxes"], rows):
            b, g, r = BRICK_COLORS[(i - 1) % len(BRICK_COLORS)]
            patch.set_facecolor((r / 255, g / 255, b / 255, 0.6))
        for median in parts["medians"]:
            median.set_color(INK)
            median.set_linewidth(2)
        axis.set_yticks(range(1, len(rows) + 1), [f"brick {r[0]}" for r in rows])
        axis.invert_yaxis()
        if index == 3:
            axis.axvline(table_L, color="#c98500", linewidth=2, linestyle="--")
            axis.text(table_L, 0.4, f" table L* {table_L:.1f}", color="#c98500", fontsize=9)
        axis.set_xlabel(f"{unit} (box = middle 50% of pixels, black line = median used as feature)",
                        color=TEXT_COLOR, fontsize=9)
        axis.set_title(label, color=INK, fontsize=11)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="x", color="#e8e7e2")
    figure.tight_layout()
    figure.savefig(out / "10_brick_distributions.png", dpi=120, facecolor=SURFACE)
    plt.close(figure)

    lines = [f"table strip L* = {table_L:.1f}   (light reference, not part of any brick)", "",
             "brick | median L* | median C* | L* - table | L* rel. table | prediction"]
    for i, f, prediction, *_ in rows:
        pred = (f"{prediction['prediction']} (conf {prediction['confidence']:.2f}, nearest "
                f"{prediction['nearest_reference']})") if prediction else "-"
        lines.append(f"  {i}   |  {f['L_med']:6.1f}   |  {f['C_med']:6.1f}   |  {f['dL_wood']:7.1f}   |"
                     f"   {f['rel_L']:6.1f}     | {pred}")
    if args.reference:
        lines += ["", f"reference: {classifier.reference.name}",
                  f"feature set used: {classifier.reference.feature_set} -> {classifier.reference.keys}"]
    (out / "10_brick_numbers.txt").write_text("\n".join(lines), encoding="utf-8")

    true_labels = read_true_labels(args.log, args.image.stem) if args.log else {}
    candidate_steps(frame, lab, chroma, final_masks, rows, true_labels, steps, out)

    for name, image in steps.items():
        cv2.imwrite(str(out / f"{name}.jpg"), image)
    tiles = [cv2.resize(image, (960, 540)) for image in steps.values()]
    tiles.append(np.full_like(tiles[0], 252))
    overview = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
    cv2.imwrite(str(out / "00_overview.jpg"), overview)
    print("\n".join(lines))
    print(f"steps: {out}")


if __name__ == "__main__":
    main()

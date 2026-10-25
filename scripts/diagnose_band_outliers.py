"""Why is each brick lighter or darker than expected? Per-brick diagnosis.

For every brick of a calibration and of a live session (re-segmented from the
saved frames and boxes) this script reports what can move its L* mode:
  - face: solid or perforated (wall visible through holes inside the box),
    and box aspect (a wide box means two faces are visible);
  - light stains (possible mortar/contamination) and dark specks in the mask;
  - scene light of that capture (table L*) and horizontal position in the frame.

Output (in <live session>/band_diagnosis/):
  gallery_calibration.jpg / gallery_live.jpg: every brick sorted by L* mode,
     mask outline, stains in cyan, specks in magenta, label and numbers;
     a red header marks bricks on the wrong side of the band;
  factors.png: L* mode against scene light, stain share and face type;
  bricks.csv: all numbers per brick.

Usage: diagnose_band_outliers.py <calibration folder> <live session folder> [--band LOW HIGH]
Without --band, the band stored in the calibration is used.
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
from scripts.live_brick_classifier import histogram_mode
from scripts.run_mobile_sam import MODEL_PATH, segment, to_corners
from ultralytics import SAM

HOLE_L = 55.0
PERFORATED_HOLE_SHARE = 0.02
STAIN_L_RISE = 12.0
SPECK_L_DROP = 12.0
TWO_FACES_ASPECT = 2.9
TILE = (130, 360)

GOOD_BGR = (214, 120, 42)
BAD_BGR = (52, 104, 235)
GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"
INK = "#0b0b0b"
SURFACE = "#fcfcfb"


def table_lightness(lab: np.ndarray, boxes: list[dict]) -> float:
    bottom = max(b["y"] + b["height"] for b in boxes)
    x1, x2 = min(b["x"] for b in boxes), max(b["x"] + b["width"] for b in boxes)
    return float(np.median(lab[bottom + 25:min(lab.shape[0], bottom + 140), x1:x2, 0]))


def diagnose_frame(sam: SAM, frame: np.ndarray, items: list[dict]) -> list[dict]:
    boxes = [it["bbox_px"] for it in items]
    label_map = segment(sam, frame, [to_corners(b) for b in boxes])
    lab = bgr_to_lab(frame.reshape(-1, 3)).reshape(frame.shape)
    scene = table_lightness(lab, boxes)
    out = []
    for index, item in enumerate(items, 1):
        b = item["bbox_px"]
        mask = label_map == index
        if mask.sum() < 500:
            continue
        L = lab[..., 0][mask]
        C = np.hypot(lab[..., 1][mask], lab[..., 2][mask])
        L_mode = histogram_mode(L)
        mx, my = round(b["width"] * 0.15), round(b["height"] * 0.08)
        inner = lab[b["y"] + my:b["y"] + b["height"] - my, b["x"] + mx:b["x"] + b["width"] - mx, 0]
        holes = float((inner > HOLE_L).mean())
        aspect = b["height"] / max(1, b["width"])
        out.append({
            **item,
            "L_mode": L_mode, "L_med": float(np.median(L)), "C_mode": histogram_mode(C),
            "stain_share": float((L > L_mode + STAIN_L_RISE).mean()),
            "speck_share": float((L < L_mode - SPECK_L_DROP).mean()),
            "holes": holes,
            "face": "perforated" if holes >= PERFORATED_HOLE_SHARE else "solid",
            "two_faces": aspect < TWO_FACES_ASPECT,
            "aspect": aspect,
            "scene_L": scene,
            "x_position": (b["x"] + b["width"] / 2) / frame.shape[1],
            "mask": mask, "frame": frame, "lab_L": lab[..., 0],
        })
    return out


def reasons(brick: dict, band: tuple[float, float], scene_ref: float) -> list[str]:
    """Plain-language hints for why a brick sits where it does."""
    hints = []
    if brick["stain_share"] >= 0.05:
        hints.append(f"stains {brick['stain_share']:.0%}")
    if brick["face"] == "perforated":
        hints.append("perforated face")
    if brick["two_faces"]:
        hints.append("2 faces in box")
    if abs(brick["scene_L"] - scene_ref) >= 2.5:
        hints.append(f"light {brick['scene_L'] - scene_ref:+.1f}")
    if brick["x_position"] < 0.25 or brick["x_position"] > 0.75:
        hints.append("frame edge")
    return hints


def tile(brick: dict, band: tuple[float, float], scene_ref: float) -> np.ndarray:
    b = brick["bbox_px"]
    pad = 10
    y1, y2 = max(0, b["y"] - pad), min(brick["frame"].shape[0], b["y"] + b["height"] + pad)
    x1, x2 = max(0, b["x"] - pad), min(brick["frame"].shape[1], b["x"] + b["width"] + pad)
    crop = brick["frame"][y1:y2, x1:x2].copy()
    mask = brick["mask"][y1:y2, x1:x2]
    L = brick["lab_L"][y1:y2, x1:x2]
    crop[mask & (L > brick["L_mode"] + STAIN_L_RISE)] = (255, 255, 0)
    crop[mask & (L < brick["L_mode"] - SPECK_L_DROP)] = (255, 0, 255)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(crop, contours, -1, (0, 255, 0), 2)
    crop = cv2.resize(crop, TILE)

    inside = band[0] <= brick["L_mode"] <= band[1]
    wrong = inside != (brick["label"] == "good")
    head = np.full((112, TILE[0], 3), (200, 200, 255) if wrong else (255, 255, 255), np.uint8)
    color = GOOD_BGR if brick["label"] == "good" else BAD_BGR
    lines = [(brick["id"], (0, 0, 0)), (f"{brick['label'].upper()} L{brick['L_mode']:.1f}", color),
             (f"{'IN' if inside else 'OUT'} {'WRONG' if wrong else 'ok'}", (0, 0, 180) if wrong else (0, 120, 0)),
             (f"{brick['face'][:5]} st{brick['stain_share']:.0%}", (0, 0, 0)),
             (f"scene {brick['scene_L']:.0f} C{brick['C_mode']:.0f}", (0, 0, 0))]
    for i, (text, c) in enumerate(lines):
        cv2.putText(head, text, (4, 18 + i * 21), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1 if i != 1 else 2, cv2.LINE_AA)
    return np.vstack([head, crop])


def gallery(bricks: list[dict], band, scene_ref, title: str, path: Path, per_row: int = 12) -> None:
    tiles = [tile(b, band, scene_ref) for b in sorted(bricks, key=lambda b: b["L_mode"])]
    blank = np.full_like(tiles[0], 250)
    while len(tiles) % per_row:
        tiles.append(blank)
    rows = [np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)]
    banner = np.full((50, rows[0].shape[1], 3), 255, np.uint8)
    cv2.putText(banner, f"{title}  band {band[0]:.1f}-{band[1]:.1f}  (red header = wrong side of the band; "
                        "cyan = light stains, magenta = dark specks, green = mask)",
                (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), np.vstack([banner, *rows]))


def factors_chart(cal: list[dict], live: list[dict], band, path: Path) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(17, 5), sharey=True)
    for axis, (key, name) in zip(axes, [("scene_L", "Scene light (table L*) of the capture"),
                                        ("stain_share", "Light stain share in the mask"),
                                        ("holes", "Perforation (wall visible through holes)")]):
        axis.axhspan(band[0], band[1], color="#e8e7e2", zorder=0)
        for rows, filled in ((cal, False), (live, True)):
            for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
                pts = [r for r in rows if r["label"] == label]
                axis.scatter([r[key] for r in pts], [r["L_mode"] for r in pts], s=55, marker=marker,
                             facecolors=color if filled else "none", edgecolors=color, linewidths=1.4,
                             label=f"{'live' if filled else 'calibration'} {label}", zorder=3)
        axis.set_xlabel(name, color=TEXT_COLOR, fontsize=9)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(color="#e8e7e2", linewidth=0.6)
        axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axes[0].set_ylabel("L* mode of the brick", color=TEXT_COLOR, fontsize=9)
    axes[0].legend(frameon=False, fontsize=8)
    figure.suptitle("What moves the brick lightness? Grey band = band used. Hollow = calibration, filled = live.",
                    color=INK, fontsize=11)
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("session", type=Path)
    parser.add_argument("--band", type=float, nargs=2, metavar=("LOW", "HIGH"))
    args = parser.parse_args()
    out = args.session / "band_diagnosis"
    out.mkdir(exist_ok=True)
    sam = SAM(str(MODEL_PATH))

    calibration = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))
    band = tuple(args.band) if args.band else tuple(calibration.get("band_L_mode", (0, 100)))
    scene_ref = float(calibration.get("scene_lightness") or 0)

    cal = []
    for photo in sorted({r["photo"] for r in calibration["rows"]}):
        items = [{"id": f"{photo}#{r['position']}", "source": "calibration", "label": r["label"],
                  "bbox_px": r["bbox_px"]} for r in calibration["rows"] if r["photo"] == photo]
        cal += diagnose_frame(sam, cv2.imread(str(args.calibration / "frames" / f"{photo}.jpg")), items)
    live = []
    for line in (args.session / "log.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        items = [{"id": f"{record['capture_id']}#{b['position']}", "source": "live", "label": b["true_label"],
                  "bbox_px": b["bbox_px"]} for b in record["bricks"] if b["true_label"]]
        if items:
            live += diagnose_frame(sam, cv2.imread(str(args.session / "frames" / f"{record['capture_id']}.jpg")), items)

    gallery(cal, band, scene_ref, "CALIBRATION", out / "gallery_calibration.jpg")
    gallery(live, band, scene_ref, "LIVE", out / "gallery_live.jpg")
    factors_chart(cal, live, band, out / "factors.png")

    fields = ["id", "source", "label", "L_mode", "L_med", "C_mode", "stain_share", "speck_share", "face",
              "holes", "two_faces", "aspect", "scene_L", "x_position", "band_side", "hints"]
    with (out / "bricks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        for b in sorted(cal + live, key=lambda b: (b["source"], b["L_mode"])):
            side = "in" if band[0] <= b["L_mode"] <= band[1] else ("below" if b["L_mode"] < band[0] else "above")
            writer.writerow({**{k: (round(b[k], 3) if isinstance(b[k], float) else b[k]) for k in fields[:14]},
                             "band_side": side, "hints": "; ".join(reasons(b, band, scene_ref))})

    print(f"band {band}, calibration scene L* {scene_ref:.1f}")
    for name, rows in (("CALIBRATION", cal), ("LIVE", live)):
        print(f"\n{name}: bricks on the wrong side of the band")
        for b in sorted(rows, key=lambda b: b["L_mode"]):
            inside = band[0] <= b["L_mode"] <= band[1]
            if inside != (b["label"] == "good"):
                print(f"  {b['id']:9s} {b['label']:4s} L_mode {b['L_mode']:5.1f} (median {b['L_med']:5.1f})  "
                      f"{b['face']:10s} stains {b['stain_share']:5.1%}  scene {b['scene_L']:4.1f}  "
                      f"x {b['x_position']:.2f}  -> {', '.join(reasons(b, band, scene_ref)) or '-'}")
    print(f"\noutput: {out}")


if __name__ == "__main__":
    main()

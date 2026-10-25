"""Build a YOLO segmentation dataset (one class: brick) from our own photos.

Labels are produced automatically by the current pipeline (distillation):
Grounding DINO -> row split -> MobileSAM. Unlike the live classifier, the masks
are NOT eroded (a detector must learn the whole brick outline); only pixels
claimed by two masks and pixels outside the box are removed.

Two phases, so the labels can be reviewed before training:
  1. auto-label every photo (slow, ~1 s per photo on GPU) -> labels_cache.json
  2. write the dataset from the cache, leaving out the photos listed in
     exclude.txt (fast; rerun with --from-cache after editing exclude.txt)

Sources: calibration and live frames in outputs2/, Third_Dataset_Bricks and the
clean first-dataset photos (standing bricks). Second_Dataset_Bricks (lying
bricks seen from above) is left out: the row split only handles standing bricks.

Review material in outputs2/yolo_dataset/review/:
  sheet_<source>_NN.jpg  every photo with its polygons, numbered; red title =
                         flagged photo to check
  review.csv             one row per photo: bricks, flags, split
Flags: no_bricks, dropped_detections (a box whose mask was background or a
piece), edge (a mask touches the image border: partially visible brick),
odd_shape (box not shaped like a standing brick), few_points (tiny polygon).

Labeling policy: only the bricks under inspection are labeled. Loose bricks at
the image border (background, cut by the frame) are never labeled, so the
detector learns to ignore them; they are drawn in grey on the review sheets.

Validation split: whole sessions are held out (VAL_SOURCES), never single
photos, so near-duplicate frames cannot leak between train and val.

Top view (--view top): photos from Top_View_Dataset/ (bricks lying on a belt-like
surface, seen from above). Grounding DINO boxes are cleaned without the row split
(stack boxes and boxes nested in a larger one removed), then MobileSAM. Output in
outputs2/yolo_dataset_top/. Validation holds out whole blocks of 10 consecutive
photos, so near-identical frames never fall on both sides.

Usage:
  build_yolo_dataset.py [--view standing|top]               auto-label and write the dataset
  build_yolo_dataset.py [--view standing|top] --from-cache  rewrite after editing exclude.txt
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "yolo_dataset"
CACHE_PATH = OUTPUT_ROOT / "labels_cache.json"
EXCLUDE_PATH = OUTPUT_ROOT / "exclude.txt"
REVIEW_ROOT = OUTPUT_ROOT / "review"

# Whole sources held out for validation (~20% of the photos).
VAL_SOURCES = {"live_20261024_203017", "calibration_20261025_104739", "third_MIX"}
MIN_COVERAGE = 0.25
POLYGON_EPSILON = 0.003
MIN_POLYGON_POINTS = 6
EDGE_PX = 3
STANDING_ASPECT = (2.0, 5.5)
TILE = (480, 270)
COLORS = [(214, 120, 42), (52, 104, 235), (122, 175, 27), (0, 161, 237),
          (164, 123, 232), (0, 131, 0), (214, 80, 98), (40, 40, 200), (200, 200, 0)]


TOP_PHOTOS = PROJECT_ROOT / "Top_View_Dataset"
TOP_BLOCK = 10
TOP_VAL_BLOCKS = {3, 8}
TOP_ASPECT = (2.3, 5.0)
NESTED_SHARE = 0.8
VIEW = "standing"


def configure(view: str) -> None:
    """Point the module paths and validation split at the chosen view."""
    global VIEW, OUTPUT_ROOT, CACHE_PATH, EXCLUDE_PATH, REVIEW_ROOT, VAL_SOURCES
    VIEW = view
    if view == "top":
        OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "yolo_dataset_top"
        VAL_SOURCES = {f"top_block{b:02d}" for b in TOP_VAL_BLOCKS}
    CACHE_PATH = OUTPUT_ROOT / "labels_cache.json"
    EXCLUDE_PATH = OUTPUT_ROOT / "exclude.txt"
    REVIEW_ROOT = OUTPUT_ROOT / "review"


def collect_top_photos() -> list[tuple[str, Path]]:
    """Top-view photos grouped in blocks of consecutive captures."""
    paths = sorted(p for session in sorted(TOP_PHOTOS.glob("2*")) for p in sorted(session.glob("*.jpg")))
    return [(f"top_block{i // TOP_BLOCK:02d}", p) for i, p in enumerate(paths)]


def clean_top_boxes(boxes: list[dict]) -> list[dict]:
    """Drop stack boxes (holding the centers of 2+ others) and boxes nested in a larger one."""
    def area(b): return b["width"] * b["height"]

    def center_in(inner, outer):
        cx, cy = inner["x"] + inner["width"] / 2, inner["y"] + inner["height"] / 2
        return outer["x"] <= cx <= outer["x"] + outer["width"] and outer["y"] <= cy <= outer["y"] + outer["height"]

    def overlap(a, b):
        w = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
        h = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
        return max(0, w) * max(0, h)

    median = float(np.median([area(b) for b in boxes])) if boxes else 0.0
    singles = [b for b in boxes
               if not (sum(center_in(o, b) for o in boxes if o is not b) >= 2 and area(b) >= 1.8 * median)]
    kept = []
    for box in sorted(singles, key=area, reverse=True):
        if all(overlap(box, k) < NESTED_SHARE * area(box) for k in kept):
            kept.append(box)
    return kept


def collect_photos() -> list[tuple[str, Path]]:
    """(source, path) for every photo that shows standing bricks."""
    photos = []
    for session in sorted((PROJECT_ROOT / "outputs2" / "calibration").glob("2*")):
        photos += [(f"calibration_{session.name}", p) for p in sorted((session / "frames").glob("cal???.jpg"))]
    for session in sorted((PROJECT_ROOT / "outputs2" / "live").glob("2*")):
        photos += [(f"live_{session.name}", p) for p in sorted((session / "frames").glob("*.jpg"))]
    for p in sorted((PROJECT_ROOT / "Third_Dataset_Bricks").glob("*.jpg")):
        photos.append((f"third_{p.stem.split('_')[0]}", p))
    for p in sorted((PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO").glob("*B_*_NS.jpg")):
        photos.append(("first_dataset", p))
    return photos


def full_masks(classifier, frame: np.ndarray, boxes: list[dict]) -> list[np.ndarray]:
    """MobileSAM masks clipped to their boxes, without erosion and without shared pixels."""
    from scripts.run_mobile_sam import to_corners
    result = classifier.segmenter(frame, bboxes=[to_corners(b) for b in boxes], verbose=False)[0]
    masks = result.masks.data.cpu().numpy().astype(bool)
    claimed = masks.sum(axis=0)
    out = []
    for mask, b in zip(masks, boxes):
        inside = np.zeros_like(mask)
        inside[b["y"]:b["y"] + b["height"], b["x"]:b["x"] + b["width"]] = True
        out.append(mask & inside & (claimed == 1))
    return out


def mask_polygon(mask: np.ndarray) -> list[list[int]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, POLYGON_EPSILON * cv2.arcLength(contour, True), True)
    return contour.reshape(-1, 2).tolist()


def auto_label(photos: list[tuple[str, Path]]) -> list[dict]:
    from scripts.live_brick_classifier import MIN_FRAME_MEAN, BrickClassifier
    from scripts.split_brick_row import split_scene

    classifier = BrickClassifier()
    records = []
    for i, (source, path) in enumerate(photos, 1):
        frame = cv2.imread(str(path))
        height, width = frame.shape[:2]
        record = {"source": source, "path": str(path.relative_to(PROJECT_ROOT)), "width": width,
                  "height": height, "bricks": [], "dropped": 0, "dark": bool(frame.mean() < MIN_FRAME_MEAN)}
        raw = [] if record["dark"] else classifier.detect_boxes(frame)
        if VIEW == "top":
            boxes = clean_top_boxes(raw)
        else:
            boxes = [d["bbox_px"] for d in split_scene(frame, raw)["detections"]] if raw else []
        if boxes:
            for b, mask in zip(boxes, full_masks(classifier, frame, boxes)):
                coverage = float(mask[b["y"]:b["y"] + b["height"], b["x"]:b["x"] + b["width"]].mean())
                if coverage < MIN_COVERAGE:
                    record["dropped"] += 1
                    continue
                record["bricks"].append({"bbox_px": b, "coverage": round(coverage, 3),
                                         "polygon": mask_polygon(mask)})
        records.append(record)
        print(f"[{i}/{len(photos)}] {source}/{path.name}: {len(record['bricks'])} bricks, dropped {record['dropped']}")
    return records


def touches_border(brick: dict, record: dict) -> bool:
    pts = np.array(brick["polygon"]) if brick["polygon"] else np.zeros((0, 2))
    return bool(len(pts)) and bool(
        pts[:, 0].min() <= EDGE_PX or pts[:, 1].min() <= EDGE_PX
        or pts[:, 0].max() >= record["width"] - 1 - EDGE_PX or pts[:, 1].max() >= record["height"] - 1 - EDGE_PX)


def labeled_bricks(record: dict) -> list[dict]:
    """Bricks written to the dataset: background bricks at the border are left out."""
    return [b for b in record["bricks"] if not touches_border(b, record)
            and len(b["polygon"]) >= MIN_POLYGON_POINTS]


def flags(record: dict) -> list[str]:
    out = []
    if record["dark"]:
        out.append("dark_frame")
    if not record["bricks"]:
        out.append("no_bricks")
    if record["dropped"]:
        out.append("dropped_detections")
    for brick in record["bricks"]:
        pts = np.array(brick["polygon"]) if brick["polygon"] else np.zeros((0, 2))
        if len(pts) < MIN_POLYGON_POINTS:
            out.append("few_points")
        elif touches_border(brick, record):
            out.append("background_not_labeled")
        b = brick["bbox_px"]
        if VIEW == "top":
            aspect = max(b["width"], b["height"]) / max(1, min(b["width"], b["height"]))
            expected = TOP_ASPECT
        else:
            aspect, expected = b["height"] / max(1, b["width"]), STANDING_ASPECT
        if not expected[0] <= aspect <= expected[1]:
            out.append("odd_shape")
    return sorted(set(out))


def photo_id(record: dict) -> str:
    return f"{record['source']}__{Path(record['path']).stem}"


def draw(record: dict, excluded: bool = False) -> np.ndarray:
    image = cv2.imread(str(PROJECT_ROOT / record["path"]))
    overlay = image.copy()
    kept = labeled_bricks(record)
    for i, brick in enumerate(record["bricks"], 1):
        color = COLORS[(i - 1) % len(COLORS)] if brick in kept else (150, 150, 150)
        pts = np.array(brick["polygon"], np.int32)
        if len(pts):
            cv2.fillPoly(overlay, [pts], color)
            cv2.polylines(image, [pts], True, color, 4)
        b = brick["bbox_px"]
        cv2.putText(image, str(i), (b["x"] + 8, b["y"] + 50), cv2.FONT_HERSHEY_SIMPLEX, 1.6, color, 4)
    image = cv2.addWeighted(overlay, 0.3, image, 0.7, 0)
    tile = cv2.resize(image, TILE)
    record_flags = flags(record)
    head = np.full((44, TILE[0], 3), (200, 200, 255) if record_flags else (255, 255, 255), np.uint8)
    cv2.putText(head, f"{Path(record['path']).stem}  {len(kept)} labeled bricks", (6, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    if excluded:
        record_flags = ["EXCLUDED"] + record_flags
        head[:] = (190, 190, 190)
    cv2.putText(head, ", ".join(record_flags) or "ok", (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (0, 0, 160) if record_flags else (0, 120, 0), 1, cv2.LINE_AA)
    return np.vstack([head, tile])


def write_review(records: list[dict], excluded: set[str]) -> None:
    # Replace the files, not the folder: it is often open in a file explorer.
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    for old in REVIEW_ROOT.glob("sheet_*.jpg"):
        old.unlink()
    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)
    for source, rows in by_source.items():
        tiles = [draw(r, photo_id(r) in excluded) for r in rows]
        for n, start in enumerate(range(0, len(tiles), 12), 1):
            chunk = tiles[start:start + 12]
            while len(chunk) % 4:
                chunk.append(np.full_like(tiles[0], 250))
            sheet = np.vstack([np.hstack(chunk[i:i + 4]) for i in range(0, len(chunk), 4)])
            cv2.imwrite(str(REVIEW_ROOT / f"sheet_{source}_{n:02d}.jpg"), sheet)
    with (REVIEW_ROOT / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["photo_id", "source", "path", "bricks", "dropped", "flags", "split", "excluded"])
        for r in records:
            writer.writerow([photo_id(r), r["source"], r["path"], len(labeled_bricks(r)), r["dropped"],
                             ";".join(flags(r)), "val" if r["source"] in VAL_SOURCES else "train",
                             photo_id(r) in excluded])


def write_dataset(records: list[dict], excluded: set[str]) -> dict:
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            folder = OUTPUT_ROOT / kind / split
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
    counts = {"train": [0, 0], "val": [0, 0]}
    for r in records:
        if photo_id(r) in excluded or r["dark"]:
            continue
        split = "val" if r["source"] in VAL_SOURCES else "train"
        name = photo_id(r)
        shutil.copy(PROJECT_ROOT / r["path"], OUTPUT_ROOT / "images" / split / f"{name}.jpg")
        lines = []
        for brick in labeled_bricks(r):
            coords = " ".join(f"{x / r['width']:.5f} {y / r['height']:.5f}" for x, y in brick["polygon"])
            lines.append(f"0 {coords}")
        (OUTPUT_ROOT / "labels" / split / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
        counts[split][0] += 1
        counts[split][1] += len(lines)
    (OUTPUT_ROOT / "data.yaml").write_text(
        f"path: {OUTPUT_ROOT.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: brick\n", encoding="utf-8")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-cache", action="store_true", help="skip auto-labeling, reuse labels_cache.json")
    parser.add_argument("--view", choices=["standing", "top"], default="standing")
    args = parser.parse_args()
    configure(args.view)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if args.from_cache:
        records = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    else:
        records = auto_label(collect_top_photos() if VIEW == "top" else collect_photos())
        CACHE_PATH.write_text(json.dumps(records), encoding="utf-8")
    if not EXCLUDE_PATH.exists():
        EXCLUDE_PATH.write_text("# one photo_id per line (see review/review.csv); lines with # are ignored\n",
                                encoding="utf-8")
    excluded = {line.strip() for line in EXCLUDE_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")}

    write_review(records, excluded)
    counts = write_dataset(records, excluded)
    flagged = [r for r in records if flags(r)]
    print(f"\nphotos {len(records)}, flagged {len(flagged)}, excluded {len(excluded)}")
    for split, (images, bricks) in counts.items():
        print(f"  {split}: {images} images, {bricks} brick polygons")
    print(f"review: {REVIEW_ROOT}\ndataset: {OUTPUT_ROOT / 'data.yaml'}")


if __name__ == "__main__":
    main()

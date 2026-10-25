"""Split a row of standing bricks into one box per brick using the joints.

When the bricks stand apart, Grounding DINO boxes are already one per brick
and are used directly. When they touch, Grounding DINO gives the extent of the
row (its stack box, or the union of its boxes) but often misses, merges or
splits individual bricks. Between touching bricks there is always a dark,
nearly vertical joint, so:

1. A darkness profile is computed across the middle band of the row; joints
   and row ends are its peaks.
2. Dynamic programming picks the cut positions. A segment is either a brick
   (width close to row height / BRICK_ASPECT) or a gap that looks like the wall
   behind the bricks. Strong joints and brick-like widths are rewarded.
3. Brick segments become boxes in the same format as the other cleaners, so
   run_mobile_sam.py can refine them into tilted brick masks.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Third_Dataset_Bricks"
INPUT_PATH = PROJECT_ROOT / "outputs2" / "third_dataset" / "grounding_dino" / "detections.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "third_dataset" / "row_split"

BRICK_ASPECT = 3.6
MIN_BRICK_RATIO = 0.6
MAX_BRICK_RATIO = 1.45
BAND_MARGIN = 0.2
PEAK_MIN_SHARE = 0.12
WALL_DELTA_E = 12.0
WALL_L_DROP = 15.0
WALL_GAP_SHARE = 0.5
WIDTH_PENALTY = 0.6
SEPARATED_MAX_OVERLAP = 0.15
SEPARATED_MIN_HEIGHT = 0.8
SAME_COLUMN_OVERLAP = 0.5
EDGE_PX = 5
EDGE_PIECE_RATIO = 0.6
SEPARATED_CHECK_GAP = 0.4
GAP_MIN_L_RISE = 10.0


def row_extent(boxes: list[dict]) -> tuple[int, int, int, int]:
    x1 = min(b["x"] for b in boxes)
    y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes)
    y2 = max(b["y"] + b["height"] for b in boxes)
    return x1, y1, x2, y2


def darkness_profile(lab: np.ndarray) -> np.ndarray:
    """Per-column darkness relative to the nearby brick surface."""
    lightness = cv2.GaussianBlur(lab[..., 0], (0, 0), 3)
    local_max = cv2.dilate(lightness, np.ones((1, 31), np.uint8))
    profile = np.clip(local_max - lightness, 0, None).mean(axis=0)
    return cv2.GaussianBlur(profile.reshape(1, -1), (0, 0), 4).ravel()


def candidate_cuts(profile: np.ndarray) -> list[int]:
    """Local maxima of the profile plus both row ends."""
    threshold = PEAK_MIN_SHARE * profile.max()
    peaks = [x for x in range(1, len(profile) - 1)
             if profile[x] >= threshold and profile[x] >= profile[x - 1] and profile[x] > profile[x + 1]]
    return sorted({0, len(profile) - 1, *peaks})


def best_partition(cuts: list[int], profile: np.ndarray, wall_share: np.ndarray,
                   brick_width: float) -> list[tuple[int, int, str]]:
    """Highest-scoring sequence of brick and gap segments between the ends."""
    strength = profile / max(profile.max(), 1e-6)
    best = {0: (0.0, [])}
    for j in range(1, len(cuts)):
        candidates = []
        for i in range(j):
            if i not in best:
                continue
            left, right = cuts[i], cuts[j]
            width = right - left
            is_wall = wall_share[left:right].mean() >= WALL_GAP_SHARE
            if is_wall:
                kind, gain = "gap", 0.0
            elif MIN_BRICK_RATIO * brick_width <= width <= MAX_BRICK_RATIO * brick_width:
                kind = "brick"
                gain = 1.0 + strength[right] - WIDTH_PENALTY * abs(width - brick_width) / brick_width
            else:
                continue
            score, segments = best[i]
            candidates.append((score + gain, segments + [(left, right, kind)]))
        if candidates:
            best[j] = max(candidates, key=lambda c: c[0])
    last = len(cuts) - 1
    if last not in best:
        return []
    return best[last][1]


def separated_bricks(image: np.ndarray, boxes: list[dict]) -> list[dict] | None:
    """Grounding DINO boxes as-is when the bricks stand apart from each other.

    The stack box (one containing the centers of two or more others) is
    ignored. The remaining boxes are used only if no two of them overlap
    horizontally (fragments of one brick always do) and every wide space between
    them is clearly lighter than the bricks, i.e. wall and not a missed brick.
    """
    def center_inside(inner: dict, outer: dict) -> bool:
        cx, cy = inner["x"] + inner["width"] / 2, inner["y"] + inner["height"] / 2
        return outer["x"] <= cx <= outer["x"] + outer["width"] and outer["y"] <= cy <= outer["y"] + outer["height"]

    def band_lightness(x1: int, x2: int, box: dict) -> float:
        y1 = box["y"] + round(BAND_MARGIN * box["height"])
        y2 = box["y"] + box["height"] - round(BAND_MARGIN * box["height"])
        pixels = image[y1:y2, x1:x2].astype(np.float32) / 255.0
        return float(np.median(cv2.cvtColor(pixels, cv2.COLOR_BGR2LAB)[..., 0]))

    singles = sorted((b for b in boxes if sum(center_inside(o, b) for o in boxes if o is not b) < 2),
                     key=lambda b: b["x"])
    if not singles:
        return None
    # A box much shorter than the row is a fragment (e.g. half of a cracked brick).
    row_height = max(b["height"] for b in singles)
    if any(b["height"] < SEPARATED_MIN_HEIGHT * row_height for b in singles):
        return None
    brick_l = np.median([band_lightness(b["x"], b["x"] + b["width"], b) for b in singles])
    median_width = np.median([b["width"] for b in singles])
    for left, right in zip(singles, singles[1:]):
        gap = right["x"] - (left["x"] + left["width"])
        if -gap > SEPARATED_MAX_OVERLAP * min(left["width"], right["width"]):
            return None
        if gap > SEPARATED_CHECK_GAP * median_width:
            if band_lightness(left["x"] + left["width"], right["x"], left) < brick_l + GAP_MIN_L_RISE:
                return None
    return singles


def fallback_to_detections(boxes: list[dict], row: list[int], brick_width: float, image_width: int) -> dict:
    """Grounding DINO boxes, cleaned: no stack box, crack halves merged, edge pieces dropped."""
    def contains(outer: dict, inner: dict) -> bool:
        cx, cy = inner["x"] + inner["width"] / 2, inner["y"] + inner["height"] / 2
        return outer["x"] <= cx <= outer["x"] + outer["width"] and outer["y"] <= cy <= outer["y"] + outer["height"]

    def same_column(a: dict, b: dict) -> bool:
        shared = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
        return shared >= SAME_COLUMN_OVERLAP * min(a["width"], b["width"])

    singles = [b for b in boxes if sum(contains(b, o) for o in boxes if o is not b) < 2]
    # Halves of a cracked brick share its column: keep their union.
    columns: list[dict] = []
    for box in sorted(singles, key=lambda b: -b["width"] * b["height"]):
        for i, column in enumerate(columns):
            if same_column(column, box):
                x1, y1 = min(column["x"], box["x"]), min(column["y"], box["y"])
                x2 = max(column["x"] + column["width"], box["x"] + box["width"])
                y2 = max(column["y"] + column["height"], box["y"] + box["height"])
                columns[i] = {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}
                break
        else:
            columns.append(dict(box))
    # Bricks cut by the image border are partial: their color is not representative.
    median_width = float(np.median([c["width"] for c in columns])) if columns else 0.0
    kept = [c for c in columns
            if not ((c["x"] <= EDGE_PX or c["x"] + c["width"] >= image_width - EDGE_PX)
                    and c["width"] < EDGE_PIECE_RATIO * median_width)]
    kept.sort(key=lambda b: b["x"])
    detections = [{"brick_id": f"brick_{i:03d}", "source": "detected_fallback", "bbox_px": b}
                  for i, b in enumerate(kept, 1)]
    return {"row_px": row, "brick_width_px": round(brick_width, 1), "segments": [],
            "count": len(detections), "detections": detections}


def split_scene(image: np.ndarray, boxes: list[dict]) -> dict:
    x1, y1, x2, y2 = row_extent(boxes)
    if (separated := separated_bricks(image, boxes)) is not None:
        detections = [{"brick_id": f"brick_{i:03d}", "source": "detected", "bbox_px": b}
                      for i, b in enumerate(separated, 1)]
        return {"row_px": [x1, y1, x2, y2], "brick_width_px": None, "segments": [],
                "count": len(detections), "detections": detections}
    height = y2 - y1
    band = image[y1 + round(BAND_MARGIN * height):y2 - round(BAND_MARGIN * height), x1:x2]
    lab = cv2.cvtColor(band.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)

    wall = image[max(0, y1 - 160):max(1, y1 - 30), x1:x2]
    wall_lab = np.median(cv2.cvtColor(wall.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB).reshape(-1, 3), axis=0)
    # Wall pixels: close in color, or just slightly darker (shadows next to bricks).
    wall_like = (np.linalg.norm(lab - wall_lab, axis=2) < WALL_DELTA_E) | (lab[..., 0] > wall_lab[0] - WALL_L_DROP)
    wall_share = wall_like.mean(axis=0)

    profile = darkness_profile(lab)
    brick_width = height / BRICK_ASPECT
    segments = best_partition(candidate_cuts(profile), profile, wall_share, brick_width)
    if not any(kind == "brick" for *_, kind in segments):
        # No brick-width partition exists (e.g. bricks seen from the side or very
        # close): fall back to Grounding DINO's own boxes without the stack box.
        return fallback_to_detections(boxes, [x1, y1, x2, y2], brick_width, image.shape[1])

    detections = []
    for left, right, kind in segments:
        if kind != "brick":
            continue
        detections.append({
            "brick_id": f"brick_{len(detections) + 1:03d}",
            "source": "row_split",
            "bbox_px": {"x": x1 + left, "y": y1, "width": right - left, "height": height},
        })
    return {"row_px": [x1, y1, x2, y2], "brick_width_px": round(brick_width, 1),
            "segments": [[x1 + l, x1 + r, k] for l, r, k in segments],
            "count": len(detections), "detections": detections}


def draw_preview(image: np.ndarray, result: dict) -> np.ndarray:
    canvas = image.copy()
    for left, right, kind in result["segments"]:
        if kind == "gap":
            cv2.rectangle(canvas, (left, result["row_px"][1]), (right, result["row_px"][3]), (180, 180, 180), 2)
    for d in result["detections"]:
        b = d["bbox_px"]
        cv2.rectangle(canvas, (b["x"], b["y"]), (b["x"] + b["width"], b["y"] + b["height"]), (0, 165, 255), 4)
        cv2.putText(canvas, d["brick_id"][-3:], (b["x"] + 8, b["y"] + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 3, cv2.LINE_AA)
    cv2.putText(canvas, f"{result['count']} bricks", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--images", type=Path, default=IMAGE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, record in records.items():
        boxes = [d["bbox_px"] for d in record["detections"]]
        image = cv2.imread(str(args.images / name))
        result = split_scene(image, boxes)
        results[name] = {"image": name, **result}
        cv2.imwrite(str(args.output / f"{Path(name).stem}_split.jpg"), draw_preview(image, result))
        print(f"{name:14s} bricks={result['count']}  gaps={sum(k == 'gap' for *_, k in result['segments'])}")
    (args.output / "detections_clean.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

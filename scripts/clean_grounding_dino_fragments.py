"""Rebuild whole bricks from fragmented Grounding DINO boxes in top-down views.

Grounding DINO often splits a lying brick at cracks or at the perforation
lines. A whole brick face has a stable aspect ratio (about 3.45 here), while
fragments are much squarer, so the brick shape is used as a prior:

1. Stack boxes (large boxes that contain the centers of two or more others)
   are removed.
2. Fragments (aspect ratio below FULL_MIN_ASPECT) are merged pairwise when they
   are aligned on the short axis, touch on the long axis, and their union has
   a brick-like aspect ratio. The pair closest to the brick aspect goes first.
3. A fragment left without a partner is extended along its long axis, into
   free space only, until it reaches the expected brick length.

Perspective (FRONT) views are skipped because the aspect prior does not hold.
"""

import argparse
import json
import re
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Second_Dataset_Bricks"
INPUT_PATH = PROJECT_ROOT / "outputs2" / "second_dataset" / "grounding_dino" / "detections.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "second_dataset" / "grounding_dino_clean"

DEFAULT_BRICK_ASPECT = 3.45
FULL_MIN_ASPECT = 2.8
FULL_MAX_ASPECT = 4.2
MERGED_ASPECT_TOLERANCE = 0.55
MIN_SHORT_AXIS_OVERLAP = 0.6
MAX_LONG_AXIS_GAP_RATIO = 0.12
STACK_AREA_RATIO = 1.8
STACK_MIN_CONTAINED = 2
SKIPPED_VIEWS = re.compile(r"_FRONT\.jpg$")
GRID_COUNT = re.compile(r"^(\d+)X(\d+)_")
BRICK_COUNT = re.compile(r"^(\d+)B_")

SOURCE_COLORS = {
    "detected": (60, 200, 60),
    "merged": (0, 165, 255),
    "extended": (255, 80, 200),
}


def to_corners(bbox: dict) -> list[float]:
    return [bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]]


def size(box: list[float]) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def aspect(box: list[float]) -> float:
    width, height = size(box)
    return max(width, height) / max(1.0, min(width, height))


def area(box: list[float]) -> float:
    width, height = size(box)
    return max(0.0, width) * max(0.0, height)


def union(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def interval_overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    return min(a2, b2) - max(a1, b1)


def expected_count(name: str) -> int | None:
    if match := GRID_COUNT.match(name):
        rows, cols = int(match.group(1)), int(match.group(2))
        return 10 if name.startswith("4X2_") else rows * cols
    if match := BRICK_COUNT.match(name):
        return int(match.group(1))
    return None


def remove_stack_boxes(boxes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop boxes that cover the whole arrangement instead of one brick."""
    median_area = float(np.median([area(b["box"]) for b in boxes]))
    stacks, kept = [], []
    for candidate in boxes:
        x1, y1, x2, y2 = candidate["box"]
        contained = sum(
            1 for other in boxes if other is not candidate
            and x1 <= (other["box"][0] + other["box"][2]) / 2 <= x2
            and y1 <= (other["box"][1] + other["box"][3]) / 2 <= y2
        )
        if contained >= STACK_MIN_CONTAINED and area(candidate["box"]) >= STACK_AREA_RATIO * median_area:
            stacks.append(candidate)
        else:
            kept.append(candidate)
    return stacks, kept


def brick_prior(boxes: list[dict]) -> tuple[float, float]:
    """Estimate brick aspect and long-side length from whole detections."""
    whole = [b["box"] for b in boxes if FULL_MIN_ASPECT <= aspect(b["box"]) <= FULL_MAX_ASPECT]
    if whole:
        target_aspect = float(np.median([aspect(b) for b in whole]))
        length = float(np.median([max(size(b)) for b in whole]))
    else:
        target_aspect = DEFAULT_BRICK_ASPECT
        length = float(np.median([min(size(b["box"])) for b in boxes])) * DEFAULT_BRICK_ASPECT
    return target_aspect, length


def pair_score(a: list[float], b: list[float], target_aspect: float, length: float) -> float | None:
    """Return how far the union is from a whole brick, or None if not mergeable."""
    merged = union(a, b)
    width, height = size(merged)
    horizontal = width >= height
    if horizontal:
        short_overlap = interval_overlap(a[1], a[3], b[1], b[3])
        short_extent = min(a[3] - a[1], b[3] - b[1])
        long_gap = -interval_overlap(a[0], a[2], b[0], b[2])
    else:
        short_overlap = interval_overlap(a[0], a[2], b[0], b[2])
        short_extent = min(a[2] - a[0], b[2] - b[0])
        long_gap = -interval_overlap(a[1], a[3], b[1], b[3])
    if short_overlap < MIN_SHORT_AXIS_OVERLAP * short_extent:
        return None
    if long_gap > MAX_LONG_AXIS_GAP_RATIO * length:
        return None
    aspect_error = abs(aspect(merged) - target_aspect)
    if aspect_error > MERGED_ASPECT_TOLERANCE:
        return None
    return aspect_error / target_aspect + abs(max(width, height) - length) / length


def best_matching(count: int, scores: dict[tuple[int, int], float]) -> list[tuple[int, int]]:
    """Disjoint pairs that maximize the number of merges, then minimize the error."""
    memo: dict[int, tuple[int, float, tuple]] = {}

    def solve(used: int) -> tuple[int, float, tuple]:
        if used in memo:
            return memo[used]
        first = next((i for i in range(count) if not used & (1 << i)), None)
        if first is None:
            return 0, 0.0, ()
        best = solve(used | (1 << first))  # leave this fragment unmatched
        for second in range(first + 1, count):
            if used & (1 << second) or (first, second) not in scores:
                continue
            merges, error, pairs = solve(used | (1 << first) | (1 << second))
            candidate = (merges + 1, error + scores[(first, second)], ((first, second),) + pairs)
            if candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] < best[1]):
                best = candidate
        memo[used] = best
        return best

    return list(solve(0)[2])


def merge_fragments(boxes: list[dict], target_aspect: float, length: float) -> list[dict]:
    """Merge fragment pairs into bricks, repeating while merges remain possible."""
    bricks = [{**b, "source": "detected", "raw_indices": [b["raw_index"]]} for b in boxes]
    while True:
        fragments = [b for b in bricks if aspect(b["box"]) < FULL_MIN_ASPECT]
        scores = {}
        for i, first in enumerate(fragments):
            for j in range(i + 1, len(fragments)):
                score = pair_score(first["box"], fragments[j]["box"], target_aspect, length)
                if score is not None:
                    scores[(i, j)] = score
        pairs = best_matching(len(fragments), scores)
        if not pairs:
            return bricks
        for i, j in pairs:
            first, second = fragments[i], fragments[j]
            bricks.remove(first)
            bricks.remove(second)
            bricks.append({
                "box": union(first["box"], second["box"]),
                "score": max(first["score"], second["score"]),
                "source": "merged",
                "raw_indices": sorted(first["raw_indices"] + second["raw_indices"]),
            })


def extend_fragments(bricks: list[dict], length: float, image_size: tuple[int, int]) -> None:
    """Grow unmatched fragments toward free space up to one brick length."""
    image_width, image_height = image_size
    for brick in bricks:
        box = brick["box"]
        if aspect(box) >= FULL_MIN_ASPECT:
            continue
        width, height = size(box)
        horizontal = width >= height
        missing = length - (width if horizontal else height)
        if missing <= 0:
            continue
        lo_axis, hi_axis, short_lo, short_hi = (0, 2, 1, 3) if horizontal else (1, 3, 0, 2)
        limit = image_width if horizontal else image_height

        # Free space on each side, bounded by neighbors that share the row/column.
        low_free, high_free = box[lo_axis], limit - box[hi_axis]
        for other in bricks:
            if other is brick:
                continue
            o = other["box"]
            if interval_overlap(box[short_lo], box[short_hi], o[short_lo], o[short_hi]) <= 0:
                continue
            if o[hi_axis] <= box[lo_axis] + 1:
                low_free = min(low_free, box[lo_axis] - o[hi_axis])
            elif o[lo_axis] >= box[hi_axis] - 1:
                high_free = min(high_free, o[lo_axis] - box[hi_axis])
        low_free, high_free = max(0.0, low_free), max(0.0, high_free)
        if low_free + high_free < 0.5 * missing:
            continue

        grow_low = min(low_free, missing) if low_free >= high_free else max(0.0, missing - high_free)
        grow_low = min(grow_low, low_free)
        grow_high = min(high_free, missing - grow_low)
        box[lo_axis] -= grow_low
        box[hi_axis] += grow_high
        brick["source"] = "extended"


def clean_scene(name: str, record: dict) -> dict:
    boxes = [
        {"box": to_corners(d["bbox_px"]), "score": d["score"], "raw_index": index}
        for index, d in enumerate(record["detections"], 1)
    ]
    stacks, singles = remove_stack_boxes(boxes)
    target_aspect, length = brick_prior(singles)
    bricks = merge_fragments(singles, target_aspect, length)
    extend_fragments(bricks, length, tuple(record["original_size"]))
    bricks.sort(key=lambda b: (round((b["box"][1] + b["box"][3]) / 2 / (length / DEFAULT_BRICK_ASPECT)),
                               b["box"][0]))

    detections = []
    for number, brick in enumerate(bricks, 1):
        x1, y1, x2, y2 = (round(v) for v in brick["box"])
        detections.append({
            "brick_id": f"brick_{number:03d}",
            "score": round(brick["score"], 3),
            "source": brick["source"],
            "raw_indices": brick["raw_indices"],
            "aspect": round(aspect(brick["box"]), 2),
            "bbox_px": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
        })
    return {
        "image": name,
        "expected_bricks": expected_count(name),
        "raw_count": record["count"],
        "count": len(detections),
        "brick_aspect_prior": round(target_aspect, 2),
        "brick_length_px": round(length, 1),
        "removed_stack_indices": [s["raw_index"] for s in stacks],
        "detections": detections,
    }


def draw_preview(image: np.ndarray, cleaned: dict) -> np.ndarray:
    canvas = image.copy()
    for detection in cleaned["detections"]:
        b = detection["bbox_px"]
        color = SOURCE_COLORS[detection["source"]]
        cv2.rectangle(canvas, (b["x"], b["y"]), (b["x"] + b["width"], b["y"] + b["height"]), color, 4)
        cv2.putText(canvas, f"{detection['brick_id'][-3:]} {detection['source']}",
                    (b["x"] + 8, b["y"] + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    status = "OK" if cleaned["count"] == cleaned["expected_bricks"] else "CHECK"
    cv2.putText(canvas, f"{status}: {cleaned['count']}/{cleaned['expected_bricks']} bricks "
                f"(raw {cleaned['raw_count']})", (30, 60), cv2.FONT_HERSHEY_SIMPLEX,
                1.4, (0, 0, 0), 3, cv2.LINE_AA)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--images", type=Path, default=IMAGE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    all_cleaned, summary = {}, []
    for name, record in records.items():
        if SKIPPED_VIEWS.search(name):
            print(f"SKIP  {name} (perspective view)")
            continue
        cleaned = clean_scene(name, record)
        stem = Path(name).stem
        image = cv2.imread(str(args.images / name))
        cv2.imwrite(str(args.output / f"{stem}_clean.jpg"), draw_preview(image, cleaned))
        (args.output / f"{stem}.json").write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        all_cleaned[name] = cleaned
        sources = [d["source"] for d in cleaned["detections"]]
        ok = cleaned["count"] == cleaned["expected_bricks"]
        summary.append({
            "image": name, "expected_bricks": cleaned["expected_bricks"],
            "raw_count": cleaned["raw_count"], "clean_count": cleaned["count"],
            "matches_expected": ok, "merged": sources.count("merged"),
            "extended": sources.count("extended"),
        })
        print(f"{'OK   ' if ok else 'CHECK'} {name:20s} raw={cleaned['raw_count']:2d} "
              f"clean={cleaned['count']:2d} expected={cleaned['expected_bricks']} "
              f"merged={sources.count('merged')} extended={sources.count('extended')}")

    (args.output / "detections_clean.json").write_text(json.dumps(all_cleaned, indent=2), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    matched = sum(item["matches_expected"] for item in summary)
    print(f"{matched}/{len(summary)} scenes match the expected brick count")


if __name__ == "__main__":
    main()

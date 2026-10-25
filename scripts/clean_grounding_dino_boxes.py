"""Clean raw Grounding DINO boxes into one box per standing brick.

Rules, applied per scene:
1. Group boxes: a box much wider than a single brick that contains the centers
   of at least two other boxes is treated as the whole stack and removed.
2. Fragments: bricks stand side by side, so boxes that share most of their
   horizontal extent belong to the same brick (crack splits, partial halves).
   Each such column is merged into its union box.
3. Recovery: if a removed group box covers a horizontal gap at least as wide as
   a brick that no kept box covers, that gap becomes a recovered brick box.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
INPUT_PATH = PROJECT_ROOT / "outputs2" / "grounding_dino" / "detections.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "grounding_dino_clean"

GROUP_WIDTH_RATIO = 1.6
GROUP_MIN_CONTAINED = 2
SAME_COLUMN_OVERLAP = 0.5
RECOVERY_WIDTH_RATIO = 0.7

SOURCE_COLORS = {
    "detected": (60, 200, 60),
    "merged": (0, 165, 255),
    "recovered": (255, 80, 200),
}


def width(box: list[float]) -> float:
    return box[2] - box[0]


def center_inside(inner: list[float], outer: list[float]) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def horizontal_overlap(a: list[float], b: list[float]) -> float:
    """Shared horizontal extent relative to the narrower box."""
    shared = min(a[2], b[2]) - max(a[0], b[0])
    return max(0.0, shared) / max(1.0, min(width(a), width(b)))


def split_group_boxes(boxes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate stack-level boxes from single-brick candidates."""
    reference_width = float(np.median([width(b["box"]) for b in boxes]))
    narrow = [b for b in boxes if width(b["box"]) < GROUP_WIDTH_RATIO * reference_width]
    if narrow:
        reference_width = float(np.median([width(b["box"]) for b in narrow]))

    groups, singles = [], []
    for candidate in boxes:
        contained = sum(
            1 for other in boxes
            if other is not candidate and center_inside(other["box"], candidate["box"])
        )
        is_wide = width(candidate["box"]) >= GROUP_WIDTH_RATIO * reference_width
        if is_wide and contained >= GROUP_MIN_CONTAINED:
            groups.append(candidate)
        else:
            singles.append(candidate)
    return groups, singles


def merge_columns(boxes: list[dict]) -> list[dict]:
    """Union every set of boxes that occupies the same brick column."""
    columns: list[list[dict]] = []
    for candidate in sorted(boxes, key=lambda b: -width(b["box"])):
        for column in columns:
            if any(
                horizontal_overlap(candidate["box"], member["box"]) >= SAME_COLUMN_OVERLAP
                for member in column
            ):
                column.append(candidate)
                break
        else:
            columns.append([candidate])

    merged = []
    for column in columns:
        stacked = np.array([member["box"] for member in column])
        merged.append(
            {
                "box": [
                    float(stacked[:, 0].min()), float(stacked[:, 1].min()),
                    float(stacked[:, 2].max()), float(stacked[:, 3].max()),
                ],
                "score": max(member["score"] for member in column),
                "source": "detected" if len(column) == 1 else "merged",
                "raw_indices": sorted(member["raw_index"] for member in column),
            }
        )
    return merged


def recover_from_groups(groups: list[dict], bricks: list[dict]) -> list[dict]:
    """Add bricks that only the stack-level box covered."""
    if not bricks:
        return []
    brick_width = float(np.median([width(b["box"]) for b in bricks]))
    recovered = []
    for group in groups:
        x1, y1, x2, y2 = group["box"]
        covered = sorted((b["box"][0], b["box"][2]) for b in bricks + recovered)
        gaps, cursor = [], x1
        for left, right in covered:
            if left > cursor:
                gaps.append((cursor, min(left, x2)))
            cursor = max(cursor, right)
        if cursor < x2:
            gaps.append((cursor, x2))
        for left, right in gaps:
            if right - left >= RECOVERY_WIDTH_RATIO * brick_width:
                recovered.append(
                    {
                        "box": [float(left), float(y1), float(right), float(y2)],
                        "score": group["score"],
                        "source": "recovered",
                        "raw_indices": [group["raw_index"]],
                    }
                )
    return recovered


def to_original_pixels(box: list[float], scale: float, size: tuple[int, int]) -> dict:
    image_width, image_height = size
    x1, y1, x2, y2 = (round(v * scale) for v in box)
    x1, x2 = max(0, x1), min(image_width, x2)
    y1, y2 = max(0, y1), min(image_height, y2)
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def clean_scene(record: dict) -> dict:
    """Return one cleaned record with spatially ordered brick IDs."""
    boxes = [
        {"box": d["box"], "score": d["score"], "raw_index": index}
        for index, d in enumerate(record["detections"], 1)
    ]
    groups, singles = split_group_boxes(boxes)
    bricks = merge_columns(singles)
    bricks += recover_from_groups(groups, bricks)
    bricks.sort(key=lambda b: b["box"][0])

    scale = record["original_size"][0] / record["size"][0]
    detections = []
    for brick_number, brick in enumerate(bricks, 1):
        detections.append(
            {
                "brick_id": f"brick_{brick_number:03d}",
                "score": round(brick["score"], 3),
                "source": brick["source"],
                "raw_indices": brick["raw_indices"],
                "box": [round(v, 1) for v in brick["box"]],
                "bbox_px": to_original_pixels(
                    brick["box"], scale, tuple(record["original_size"])
                ),
            }
        )

    return {
        "image": record["image"],
        "expected_bricks": record["expected_bricks"],
        "raw_count": record["count"],
        "count": len(detections),
        "removed_group_indices": [g["raw_index"] for g in groups],
        "detections": detections,
    }


def draw_preview(image: np.ndarray, cleaned: dict) -> np.ndarray:
    """Draw cleaned boxes colored by how they were obtained."""
    canvas = image.copy()
    for detection in cleaned["detections"]:
        bbox = detection["bbox_px"]
        color = SOURCE_COLORS[detection["source"]]
        top_left = (bbox["x"], bbox["y"])
        bottom_right = (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"])
        cv2.rectangle(canvas, top_left, bottom_right, color, 4)
        text = f"{detection['brick_id'][-3:]} {detection['source']}"
        cv2.putText(
            canvas, text, (bbox["x"] + 6, bbox["y"] + 34),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA,
        )
    status = "OK" if cleaned["count"] == cleaned["expected_bricks"] else "CHECK"
    cv2.putText(
        canvas,
        f"{status}: {cleaned['count']}/{cleaned['expected_bricks']} bricks "
        f"(raw {cleaned['raw_count']})",
        (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA,
    )
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--images", type=Path, default=IMAGE_ROOT)
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)

    all_cleaned, summary = {}, []
    for name, record in records.items():
        cleaned = clean_scene(record)
        stem = Path(name).stem
        image = cv2.imread(str(args.images / name))
        if image is None:
            raise FileNotFoundError(f"Could not read image: {args.images / name}")
        cv2.imwrite(str(args.output / f"{stem}_clean.jpg"), draw_preview(image, cleaned))
        (args.output / f"{stem}.json").write_text(
            json.dumps(cleaned, indent=2), encoding="utf-8"
        )
        all_cleaned[name] = cleaned
        sources = [d["source"] for d in cleaned["detections"]]
        summary.append(
            {
                "image": name,
                "expected_bricks": cleaned["expected_bricks"],
                "raw_count": cleaned["raw_count"],
                "clean_count": cleaned["count"],
                "matches_expected": cleaned["count"] == cleaned["expected_bricks"],
                "merged": sources.count("merged"),
                "recovered": sources.count("recovered"),
            }
        )
        status = "OK   " if cleaned["count"] == cleaned["expected_bricks"] else "CHECK"
        print(
            f"{status} {name:16s} raw={cleaned['raw_count']:2d} "
            f"clean={cleaned['count']} expected={cleaned['expected_bricks']} "
            f"merged={sources.count('merged')} recovered={sources.count('recovered')}"
        )

    (args.output / "detections_clean.json").write_text(
        json.dumps(all_cleaned, indent=2), encoding="utf-8"
    )
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    matched = sum(item["matches_expected"] for item in summary)
    print(f"{matched}/{len(summary)} scenes match the expected brick count")


if __name__ == "__main__":
    main()

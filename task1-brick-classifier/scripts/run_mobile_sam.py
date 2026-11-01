"""Segment each detected brick with MobileSAM, using its corrected box as prompt.

Pixels claimed by more than one brick mask are dropped, and every mask is
eroded so color measurements stay away from joints and neighbors. Each image
gets a label map (0 = background, i = i-th detection), a preview and coverage
statistics (mask area relative to its box).
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import SAM


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETECTIONS_PATH = PROJECT_ROOT / "outputs2" / "grounding_dino_clean" / "detections_clean.json"
IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "first_dataset" / "mobile_sam"
MODEL_PATH = PROJECT_ROOT / "models" / "mobile_sam.pt"

ERODE_PX = 7
MASK_COLORS = [(214, 120, 42), (52, 104, 235), (122, 175, 27), (0, 161, 237),
               (164, 123, 232), (0, 131, 0), (214, 80, 98)]


def to_corners(bbox: dict) -> list[int]:
    return [bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]]


def segment(model: SAM, source: Path | np.ndarray, boxes: list[list[int]]) -> np.ndarray:
    """Return a label map with one eroded, non-overlapping mask per box.

    `source` is an image path or a BGR image already in memory.
    """
    result = model(str(source) if isinstance(source, Path) else source, bboxes=boxes, verbose=False)[0]
    masks = result.masks.data.cpu().numpy().astype(bool)
    claimed = masks.sum(axis=0)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ERODE_PX + 1, 2 * ERODE_PX + 1))
    labels = np.zeros(masks.shape[1:], np.uint8)
    for index, (mask, box) in enumerate(zip(masks, boxes), 1):
        x1, y1, x2, y2 = box
        inside = np.zeros_like(mask)
        inside[y1:y2, x1:x2] = True
        exclusive = (mask & inside & (claimed == 1)).astype(np.uint8)
        labels[cv2.erode(exclusive, kernel).astype(bool)] = index
    return labels


def draw_preview(image: np.ndarray, labels: np.ndarray, boxes: list[list[int]]) -> np.ndarray:
    overlay = image.copy()
    for index, box in enumerate(boxes, 1):
        color = MASK_COLORS[(index - 1) % len(MASK_COLORS)]
        overlay[labels == index] = color
        cv2.rectangle(image, tuple(box[:2]), tuple(box[2:]), color, 3)
    return cv2.addWeighted(overlay, 0.45, image, 0.55, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detections", type=Path, default=DETECTIONS_PATH)
    parser.add_argument("--images", type=Path, default=IMAGE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    model = SAM(str(MODEL_PATH))
    records = json.loads(args.detections.read_text(encoding="utf-8"))
    summary = {}
    for name, record in records.items():
        boxes = [to_corners(d["bbox_px"]) for d in record["detections"]]
        if not boxes:
            continue
        image = cv2.imread(str(args.images / name))
        labels = segment(model, args.images / name, boxes)
        stem = Path(name).stem
        cv2.imwrite(str(args.output / f"{stem}_labels.png"), labels)
        cv2.imwrite(str(args.output / f"{stem}_mask_preview.jpg"), draw_preview(image, labels, boxes))
        coverage = []
        for index, (x1, y1, x2, y2) in enumerate(boxes, 1):
            coverage.append(round(float((labels[y1:y2, x1:x2] == index).mean()), 3))
        summary[name] = {"brick_ids": [d["brick_id"] for d in record["detections"]],
                         "mask_coverage_of_box": coverage}
        print(f"{name:20s} coverage " + " ".join(f"{c:.2f}" for c in coverage))
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

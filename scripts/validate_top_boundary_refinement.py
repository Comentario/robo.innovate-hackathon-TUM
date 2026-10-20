import json
import sys
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import perception.brick_detector.background_difference as detector
from validate_local_recovery import calculate_iou, load_brick_boxes
from validate_local_recovery_regression import match_boxes


DATASET_ROOT = (
    PROJECT_ROOT
    / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
    / "Bricks_Detection_Dataset/OBB/dataset_all"
)
IMAGE_PATH = DATASET_ROOT / "images/test/34c1881b-image_205.png"
LABEL_PATH = DATASET_ROOT / "labels/test/34c1881b-image_205.txt"
BASELINE_DIRECTORY = (
    PROJECT_ROOT / "outputs/alignment_mask_experiment/bricks_70/current"
)
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs/top_boundary_experiment/bricks_70"
TOP_SEARCH_DISTANCE = 60


def find_refined_top(
    image: np.ndarray,
    grouped_bbox: tuple[int, int, int, int],
) -> tuple[int, np.ndarray]:
    x0, y0, x1, y1 = grouped_bbox
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, detector.GRADIENT_BLUR_SIZE, 0)
    sobel_y = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3))
    search_end = min(y1, y0 + TOP_SEARCH_DISTANCE)
    profile = sobel_y[y0:search_end, x0:x1].mean(axis=1)
    return y0 + int(np.argmax(profile)), profile


def build_predictions(
    current: np.ndarray,
    aligned_background: np.ndarray,
    grouped_mask: np.ndarray,
    cells: list[dict],
) -> list[tuple[int, int, int, int]]:
    current_lab = cv2.cvtColor(current, cv2.COLOR_BGR2LAB).astype(np.float32)
    background_lab = cv2.cvtColor(
        aligned_background,
        cv2.COLOR_BGR2LAB,
    ).astype(np.float32)
    difference = np.linalg.norm(current_lab - background_lab, axis=2)

    gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    gradient_input = cv2.GaussianBlur(gray, detector.GRADIENT_BLUR_SIZE, 0)
    sobel_x = np.abs(cv2.Sobel(gradient_input, cv2.CV_64F, 1, 0, ksize=3))
    sobel_y = np.abs(cv2.Sobel(gradient_input, cv2.CV_64F, 0, 1, ksize=3))

    predictions = []
    for cell in cells:
        cell_region = grouped_mask[
            cell["y_start"] : cell["y_end"],
            cell["x_start"] : cell["x_end"],
        ] > 0
        foreground_y, foreground_x = np.nonzero(cell_region)
        if foreground_x.size < detector.MIN_COMPONENT_AREA:
            continue

        x0 = cell["x_start"] + int(foreground_x.min())
        y0 = cell["y_start"] + int(foreground_y.min())
        x1 = cell["x_start"] + int(foreground_x.max()) + 1
        y1 = cell["y_start"] + int(foreground_y.max()) + 1
        cell_area = cell_region.shape[0] * cell_region.shape[1]
        occupancy = foreground_x.size / cell_area
        local_recovery_applied = False

        if occupancy < detector.LOCAL_RECOVERY_OCCUPANCY_THRESHOLD:
            recovery = detector.recover_local_foreground(
                difference,
                cell,
                (x0, y0, x1, y1),
            )
            if recovery is not None:
                box_x, box_y, box_width, box_height = recovery["bbox"]
                x0, y0 = box_x, box_y
                x1 = box_x + box_width
                y1 = box_y + box_height
                local_recovery_applied = True

        cell_width = cell["x_end"] - cell["x_start"]
        cell_height = cell["y_end"] - cell["y_start"]
        if not local_recovery_applied and (
            (x1 - x0) / cell_width < detector.MIN_FOREGROUND_SPAN_RATIO
            or (y1 - y0) / cell_height < detector.MIN_FOREGROUND_SPAN_RATIO
        ):
            x0, y0 = cell["x_start"], cell["y_start"]
            x1, y1 = cell["x_end"], cell["y_end"]

        refined_bbox, _ = detector.refine_bbox_with_gradients(
            sobel_x,
            sobel_y,
            (x0, y0, x1, y1),
        )
        predictions.append(refined_bbox)

    return predictions


def calculate_metrics(
    predictions: list[tuple[int, int, int, int]],
    targets: list[tuple[float, float, float, float]],
) -> dict:
    matches = match_boxes(predictions, targets)
    ious = [
        calculate_iou(predictions[index], targets[target_index])
        for index, target_index in matches.items()
    ]
    valid_matches = int(sum(iou >= 0.5 for iou in ious))
    return {
        "detected_count": len(predictions),
        "expected_count": len(targets),
        "mean_iou": round(float(np.mean(ious)), 3),
        "minimum_iou": round(float(np.min(ious)), 3),
        "iou_50_matches": valid_matches,
        "precision_at_50": round(valid_matches / len(predictions), 3),
        "recall_at_50": round(valid_matches / len(targets), 3),
    }


def draw_cells(image: np.ndarray, cells: list[dict]) -> np.ndarray:
    preview = image.copy()
    for cell in cells:
        cv2.rectangle(
            preview,
            (cell["x_start"], cell["y_start"]),
            (cell["x_end"] - 1, cell["y_end"] - 1),
            (255, 255, 0),
            1,
        )
    return preview


def draw_predictions(
    image: np.ndarray,
    predictions: list[tuple[int, int, int, int]],
) -> np.ndarray:
    preview = image.copy()
    for index, (x0, y0, x1, y1) in enumerate(predictions, start=1):
        cv2.rectangle(preview, (x0, y0), (x1 - 1, y1 - 1), (0, 255, 0), 2)
        cv2.putText(
            preview,
            f"brick_{index:03d}",
            (x0, max(18, y0 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return preview


def main() -> None:
    image = cv2.imread(str(IMAGE_PATH))
    aligned_background = cv2.imread(
        str(BASELINE_DIRECTORY / "aligned_background.png")
    )
    grouped_mask = cv2.imread(
        str(BASELINE_DIRECTORY / "grouped_mask.png"),
        cv2.IMREAD_GRAYSCALE,
    )
    if image is None or aligned_background is None or grouped_mask is None:
        raise FileNotFoundError("Missing input from the alignment-mask experiment")

    foreground_y, foreground_x = np.nonzero(grouped_mask)
    x0 = int(foreground_x.min())
    x1 = int(foreground_x.max()) + 1
    original_y0 = int(foreground_y.min())
    y1 = int(foreground_y.max()) + 1
    refined_y0, profile = find_refined_top(
        image,
        (x0, original_y0, x1, y1),
    )

    refined_region = grouped_mask[refined_y0:y1, x0:x1] > 0
    row_layout = detector.estimate_row_layout(
        refined_region,
        image.shape[1],
        image.shape[0],
    )
    split_mask = grouped_mask.copy()
    _, _, _, cells = detector.split_component_hierarchy(
        split_mask,
        refined_region,
        refined_region,
        x0,
        refined_y0,
        x1 - x0,
        y1 - refined_y0,
    )
    predictions = build_predictions(
        image,
        aligned_background,
        grouped_mask,
        cells,
    )
    targets = load_brick_boxes(LABEL_PATH, image.shape)

    baseline_predictions = []
    baseline_inventory = json.loads(
        (BASELINE_DIRECTORY / "inventory.json").read_text(encoding="utf-8")
    )
    for brick in baseline_inventory["bricks"]:
        box = brick["bbox_px"]
        baseline_predictions.append(
            (
                box["x"],
                box["y"],
                box["x"] + box["width"],
                box["y"] + box["height"],
            )
        )

    report = {
        "scene": "bricks_70",
        "detector_modified": False,
        "original_top": original_y0,
        "refined_top": refined_y0,
        "top_gradient_strength": round(
            float(profile[refined_y0 - original_y0]),
            3,
        ),
        "row_layout": [
            {
                "orientation": row["orientation"],
                "start_y": refined_y0 + row["start_y"],
                "end_y": refined_y0 + row["end_y"],
                "expected_bricks": row["expected_bricks"],
                "score": float(row["score"]),
            }
            for row in row_layout
        ],
        "baseline_metrics": calculate_metrics(baseline_predictions, targets),
        "refined_metrics": calculate_metrics(predictions, targets),
    }

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    boundary_preview = image.copy()
    cv2.line(boundary_preview, (x0, original_y0), (x1, original_y0), (0, 0, 255), 2)
    cv2.line(boundary_preview, (x0, refined_y0), (x1, refined_y0), (255, 255, 0), 2)
    cv2.imwrite(str(OUTPUT_DIRECTORY / "top_boundary.png"), boundary_preview)
    cv2.imwrite(str(OUTPUT_DIRECTORY / "cells_preview.png"), draw_cells(image, cells))
    cv2.imwrite(
        str(OUTPUT_DIRECTORY / "detections_preview.png"),
        draw_predictions(image, predictions),
    )
    cv2.imwrite(str(OUTPUT_DIRECTORY / "split_mask.png"), split_mask)
    with (OUTPUT_DIRECTORY / "report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(f"Top boundary: {original_y0} -> {refined_y0}")
    print(
        "Layout: "
        + ", ".join(
            f"{row['orientation']}:{row['expected_bricks']}"
            for row in report["row_layout"]
        )
    )
    print(f"Baseline metrics: {report['baseline_metrics']}")
    print(f"Refined metrics: {report['refined_metrics']}")
    print(f"Saved experiment to: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

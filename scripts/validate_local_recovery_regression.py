import json
from pathlib import Path

import cv2
import numpy as np

from perception.brick_detector.background_difference import (
    LAYOUT_SHORT_SIDE,
    NOMINAL_BRICK_HEIGHT,
    REFERENCE_IMAGE_WIDTH,
    estimate_row_layout,
    split_component_hierarchy,
)
from scripts.validate_local_recovery import (
    calculate_iou,
    load_brick_boxes,
    recover_connected_low_threshold,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "local_recovery_regression"
LOW_OCCUPANCY_THRESHOLD = 0.25
LOW_THRESHOLDS = (20.0, 25.0)

DATASET_DIRECTORY = (
    PROJECT_ROOT
    / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
    / "Bricks_Detection_Dataset/OBB/dataset_all"
)

SCENES = {
    "02": ("c9706302-image_275.txt", "train"),
    "06": ("74831553-image_271.txt", "train"),
    "10": ("bcff4c6b-image_267.txt", "train"),
    "17": ("cc710eab-image_260.txt", "train"),
    "22": ("6ba46c8c-image_255.txt", "val"),
    "25": ("d7ff9b9a-image_252.txt", "train"),
    "32": ("1f38648d-image_245.txt", "val"),
    "37": ("2716974e-image_240.txt", "train"),
}


def get_cells(grouped_mask: np.ndarray) -> list[dict]:
    foreground_y, foreground_x = np.nonzero(grouped_mask)
    x0 = int(foreground_x.min())
    x1 = int(foreground_x.max()) + 1
    y0 = int(foreground_y.min())
    y1 = int(foreground_y.max()) + 1
    grouped_region = grouped_mask[y0:y1, x0:x1] > 0
    split_mask = grouped_mask.copy()
    _, _, _, cells = split_component_hierarchy(
        split_mask,
        grouped_region,
        grouped_region,
        x0,
        y0,
        x1 - x0,
        y1 - y0,
    )
    return cells


def calculate_search_bbox(cell: dict, image_shape: tuple[int, ...]) -> tuple:
    image_width = image_shape[1]
    expected_width = (
        LAYOUT_SHORT_SIDE
        if cell["orientation"] == "vertical"
        else NOMINAL_BRICK_HEIGHT
    ) * image_width / REFERENCE_IMAGE_WIDTH
    current_width = cell["x_end"] - cell["x_start"]
    if current_width >= expected_width * 0.8:
        return (
            cell["x_start"],
            cell["y_start"],
            cell["x_end"],
            cell["y_end"],
        )

    expected_width = round(expected_width)
    if cell["cell_index"] == 1:
        search_x1 = cell["x_end"]
        search_x0 = search_x1 - expected_width
    else:
        search_x0 = cell["x_start"]
        search_x1 = search_x0 + expected_width

    return (
        max(0, search_x0),
        cell["y_start"],
        min(image_width, search_x1),
        cell["y_end"],
    )


def match_boxes(predictions: list[tuple], targets: list[tuple]) -> dict[int, int]:
    candidates = []
    for prediction_index, prediction in enumerate(predictions):
        for target_index, target in enumerate(targets):
            candidates.append(
                (
                    calculate_iou(prediction, target),
                    prediction_index,
                    target_index,
                )
            )

    matches = {}
    used_targets = set()
    for _, prediction_index, target_index in sorted(candidates, reverse=True):
        if prediction_index in matches or target_index in used_targets:
            continue
        matches[prediction_index] = target_index
        used_targets.add(target_index)
    return matches


def draw_detection_box(
    image: np.ndarray,
    box: tuple,
    color: tuple,
    label: str,
) -> None:
    x0, y0, x1, y1 = map(round, box)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, 2)
    cv2.putText(
        image,
        label,
        (x0, max(18, y0 - 5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        color,
        1,
        cv2.LINE_AA,
    )


def save_visual_validation(
    scene_name: str,
    image: np.ndarray,
    inventory: dict,
    baseline_boxes: list[tuple],
    recovered_boxes: list[tuple],
    triggered_indices: set[int],
    targets: list[tuple],
    matches: dict[int, int],
) -> None:
    baseline_preview = image.copy()
    recovered_preview = image.copy()
    for index, (baseline_box, recovered_box) in enumerate(
        zip(baseline_boxes, recovered_boxes)
    ):
        brick_id = inventory["bricks"][index]["id"]
        baseline_color = (0, 0, 255) if index in triggered_indices else (0, 200, 0)
        recovered_color = (255, 255, 0) if index in triggered_indices else (0, 200, 0)
        draw_detection_box(baseline_preview, baseline_box, baseline_color, brick_id)
        draw_detection_box(recovered_preview, recovered_box, recovered_color, brick_id)
        if index in triggered_indices:
            draw_detection_box(
                recovered_preview,
                targets[matches[index]],
                (255, 255, 255),
                "ground_truth",
            )

    cv2.rectangle(baseline_preview, (0, 0), (220, 28), (30, 30, 30), -1)
    cv2.putText(
        baseline_preview,
        "Before local recovery",
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.rectangle(recovered_preview, (0, 0), (310, 28), (30, 30, 30), -1)
    cv2.putText(
        recovered_preview,
        f"After recovery - triggered: {len(triggered_indices)}",
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    scene_directory = OUTPUT_DIRECTORY / f"bricks_{scene_name}"
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(
        str(scene_directory / "before_after.png"),
        np.hstack((baseline_preview, recovered_preview)),
    )
    cv2.imwrite(
        str(scene_directory / "recovery_preview.png"),
        recovered_preview,
    )


def validate_scene(scene_name: str, label_config: tuple[str, str]) -> dict:
    image_path = PROJECT_ROOT / f"data/images/zenodo_detection/bricks_{scene_name}.png"
    if scene_name == "37":
        image_path = (
            DATASET_DIRECTORY
            / "images/train/2716974e-image_240.png"
        )
    label_name, split = label_config
    label_path = DATASET_DIRECTORY / "labels" / split / label_name
    result_directory = (
        PROJECT_ROOT / f"outputs/integration_validation/bricks_{scene_name}"
    )

    image = cv2.imread(str(image_path))
    aligned_background = cv2.imread(str(result_directory / "aligned_background.png"))
    grouped_mask = cv2.imread(
        str(result_directory / "grouped_mask.png"),
        cv2.IMREAD_GRAYSCALE,
    )
    inventory = json.loads(
        (result_directory / "inventory.json").read_text(encoding="utf-8")
    )
    if image is None or aligned_background is None or grouped_mask is None:
        raise FileNotFoundError(f"Missing validation data for scene {scene_name}")

    current_lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    background_lab = cv2.cvtColor(
        aligned_background,
        cv2.COLOR_BGR2LAB,
    ).astype(np.float32)
    difference = np.linalg.norm(current_lab - background_lab, axis=2)
    cells = get_cells(grouped_mask)
    predictions = []
    for brick in inventory["bricks"]:
        box = brick["bbox_px"]
        predictions.append(
            (
                box["x"],
                box["y"],
                box["x"] + box["width"],
                box["y"] + box["height"],
            )
        )

    targets = load_brick_boxes(label_path, image.shape)
    matches = match_boxes(predictions, targets)
    recovered_predictions = {
        threshold: predictions.copy() for threshold in LOW_THRESHOLDS
    }
    triggered_cells = []

    for index, (cell, observed_bbox) in enumerate(zip(cells, predictions)):
        cell_region = grouped_mask[
            cell["y_start"] : cell["y_end"],
            cell["x_start"] : cell["x_end"],
        ] > 0
        occupancy = np.count_nonzero(cell_region) / cell_region.size
        if occupancy >= LOW_OCCUPANCY_THRESHOLD:
            continue

        search_bbox = calculate_search_bbox(cell, image.shape)
        recovery_results = {}
        for threshold in LOW_THRESHOLDS:
            _, recovered_bbox = recover_connected_low_threshold(
                difference,
                observed_bbox,
                search_bbox,
                threshold,
            )
            if recovered_bbox is not None:
                recovered_predictions[threshold][index] = recovered_bbox
            recovery_results[str(round(threshold))] = recovered_bbox

        triggered_cells.append(
            {
                "brick_id": inventory["bricks"][index]["id"],
                "occupancy": round(float(occupancy), 3),
                "orientation": cell["orientation"],
                "observed_bbox": observed_bbox,
                "search_bbox": search_bbox,
                "recovered_bboxes": recovery_results,
            }
        )

    baseline_ious = [
        calculate_iou(predictions[index], targets[target_index])
        for index, target_index in matches.items()
    ]
    metrics = {
        "baseline": {
            "mean_iou": round(float(np.mean(baseline_ious)), 3),
            "minimum_iou": round(float(np.min(baseline_ious)), 3),
        }
    }
    for threshold, boxes in recovered_predictions.items():
        recovered_ious = [
            calculate_iou(boxes[index], targets[target_index])
            for index, target_index in matches.items()
        ]
        changed_ious = [
            {
                "brick_id": inventory["bricks"][index]["id"],
                "before": round(
                    calculate_iou(predictions[index], targets[matches[index]]),
                    3,
                ),
                "after": round(
                    calculate_iou(boxes[index], targets[matches[index]]),
                    3,
                ),
            }
            for index in range(len(predictions))
            if boxes[index] != predictions[index]
        ]
        metrics[f"threshold_{round(threshold)}"] = {
            "mean_iou": round(float(np.mean(recovered_ious)), 3),
            "minimum_iou": round(float(np.min(recovered_ious)), 3),
            "changed_ious": changed_ious,
        }

    save_visual_validation(
        scene_name,
        image,
        inventory,
        predictions,
        recovered_predictions[25.0],
        {
            index
            for index, box in enumerate(recovered_predictions[25.0])
            if box != predictions[index]
        },
        targets,
        matches,
    )

    return {
        "scene": scene_name,
        "brick_count": len(predictions),
        "triggered_cell_count": len(triggered_cells),
        "triggered_cells": triggered_cells,
        "metrics": metrics,
    }


def main() -> None:
    reports = []
    for scene_name, label_config in SCENES.items():
        report = validate_scene(scene_name, label_config)
        reports.append(report)
        baseline = report["metrics"]["baseline"]
        result = report["metrics"]["threshold_20"]
        print(
            f"Scene {scene_name}: triggered={report['triggered_cell_count']}, "
            f"mean IoU={baseline['mean_iou']:.3f}->{result['mean_iou']:.3f}, "
            f"min IoU={baseline['minimum_iou']:.3f}->{result['minimum_iou']:.3f}"
        )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIRECTORY / "report.json").open("w", encoding="utf-8") as file:
        json.dump(reports, file, indent=2)
    print(f"Saved regression report to: {OUTPUT_DIRECTORY / 'report.json'}")


if __name__ == "__main__":
    main()

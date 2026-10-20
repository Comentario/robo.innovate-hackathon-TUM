import json
from pathlib import Path

import cv2
import numpy as np

from perception.brick_detector.background_difference import (
    LAYOUT_SHORT_SIDE,
    MIN_COMPONENT_AREA,
    estimate_row_layout,
    split_component_hierarchy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "grouping_validation"
MIN_HORIZONTAL_OVERLAP = 0.50
REFERENCE_IMAGE_HEIGHT = 599

SCENES = {
    "17": {
        "image": PROJECT_ROOT / "data/images/zenodo_detection/bricks_17.png",
        "mask": PROJECT_ROOT
        / "outputs/alignment_regression/bricks_17/detector_affine/clean.png",
    },
    "32": {
        "image": PROJECT_ROOT / "data/images/zenodo_detection/bricks_32.png",
        "mask": PROJECT_ROOT
        / "outputs/alignment_regression/bricks_32/detector_affine/clean.png",
    },
    "37": {
        "image": PROJECT_ROOT
        / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
        / "Bricks_Detection_Dataset/OBB/dataset_all/images/train"
        / "2716974e-image_240.png",
        "mask": PROJECT_ROOT
        / "outputs/alignment_experiment_37/detector_affine/clean.png",
    },
}


def calculate_horizontal_overlap(
    candidate_x: int,
    candidate_width: int,
    anchor_x: int,
    anchor_width: int,
) -> float:
    candidate_end = candidate_x + candidate_width
    anchor_end = anchor_x + anchor_width
    overlap = max(0, min(candidate_end, anchor_end) - max(candidate_x, anchor_x))
    return overlap / candidate_width


def calculate_vertical_gap(
    candidate_y: int,
    candidate_height: int,
    anchor_y: int,
    anchor_height: int,
) -> int:
    candidate_end = candidate_y + candidate_height
    anchor_end = anchor_y + anchor_height
    return max(0, candidate_y - anchor_end, anchor_y - candidate_end)


def group_stack_components(
    component_labels: np.ndarray,
    component_stats: np.ndarray,
    image_shape: tuple[int, ...],
) -> dict:
    if component_stats.shape[0] <= 1:
        raise ValueError("No foreground components were found")

    foreground_areas = component_stats[1:, cv2.CC_STAT_AREA]
    anchor_label = 1 + int(np.argmax(foreground_areas))
    anchor_x, anchor_y, anchor_width, anchor_height = map(
        int,
        component_stats[anchor_label, :4],
    )
    scaled_short_side = LAYOUT_SHORT_SIDE * image_shape[0] / REFERENCE_IMAGE_HEIGHT

    selected_labels = []
    decisions = []
    for label in range(1, component_stats.shape[0]):
        x, y, width, height, area = map(int, component_stats[label])
        overlap_ratio = calculate_horizontal_overlap(
            x,
            width,
            anchor_x,
            anchor_width,
        )
        vertical_gap = calculate_vertical_gap(
            y,
            height,
            anchor_y,
            anchor_height,
        )

        if label == anchor_label:
            accepted = True
            reason = "largest_component_anchor"
        elif area < MIN_COMPONENT_AREA:
            accepted = False
            reason = "area_below_minimum"
        elif overlap_ratio < MIN_HORIZONTAL_OVERLAP:
            accepted = False
            reason = "insufficient_horizontal_overlap"
        elif vertical_gap > scaled_short_side:
            accepted = False
            reason = "vertical_gap_too_large"
        else:
            accepted = True
            reason = "overlap_and_distance_match"

        if accepted:
            selected_labels.append(label)

        decisions.append(
            {
                "label": label,
                "area": area,
                "bbox": {"x": x, "y": y, "width": width, "height": height},
                "horizontal_overlap": round(overlap_ratio, 3),
                "vertical_gap_px": vertical_gap,
                "accepted": accepted,
                "reason": reason,
            }
        )

    grouped_region = np.isin(component_labels, selected_labels)
    foreground_y, foreground_x = np.nonzero(grouped_region)
    if foreground_x.size == 0:
        raise ValueError("The grouped mask is empty")

    grouped_bbox = {
        "x": int(foreground_x.min()),
        "y": int(foreground_y.min()),
        "width": int(foreground_x.max() - foreground_x.min() + 1),
        "height": int(foreground_y.max() - foreground_y.min() + 1),
    }
    grouped_mask = np.where(grouped_region, 255, 0).astype(np.uint8)

    return {
        "anchor_label": anchor_label,
        "selected_labels": selected_labels,
        "grouped_mask": grouped_mask,
        "grouped_bbox": grouped_bbox,
        "scaled_short_side": round(scaled_short_side, 2),
        "decisions": decisions,
    }


def build_component_preview(
    component_labels: np.ndarray,
    component_stats: np.ndarray,
) -> np.ndarray:
    preview = np.zeros((*component_labels.shape, 3), dtype=np.uint8)
    for label in range(1, component_stats.shape[0]):
        color = (
            int((53 * label) % 200 + 55),
            int((97 * label) % 200 + 55),
            int((149 * label) % 200 + 55),
        )
        preview[component_labels == label] = color
        x, y, width, height = map(int, component_stats[label, :4])
        cv2.putText(
            preview,
            f"L{label}",
            (x, max(18, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return preview


def build_grouping_preview(
    image: np.ndarray,
    component_labels: np.ndarray,
    grouping: dict,
) -> np.ndarray:
    color_layer = np.zeros_like(image)
    for decision in grouping["decisions"]:
        label = decision["label"]
        if label == grouping["anchor_label"]:
            color = (255, 120, 0)
        elif decision["accepted"]:
            color = (0, 200, 0)
        else:
            color = (0, 0, 255)
        color_layer[component_labels == label] = color

    preview = cv2.addWeighted(image, 0.55, color_layer, 0.45, 0)
    for decision in grouping["decisions"]:
        box = decision["bbox"]
        color = (0, 255, 0) if decision["accepted"] else (0, 0, 255)
        if decision["label"] == grouping["anchor_label"]:
            color = (255, 120, 0)
        cv2.rectangle(
            preview,
            (box["x"], box["y"]),
            (box["x"] + box["width"] - 1, box["y"] + box["height"] - 1),
            color,
            2,
        )
        cv2.putText(
            preview,
            f"L{decision['label']}",
            (box["x"], max(18, box["y"] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return preview


def calculate_cells(grouping: dict) -> tuple[list[dict], list[dict]]:
    grouped_mask = grouping["grouped_mask"]
    box = grouping["grouped_bbox"]
    x, y, width, height = box["x"], box["y"], box["width"], box["height"]
    component_region = grouped_mask[y : y + height, x : x + width] > 0
    row_layout = estimate_row_layout(
        component_region,
        grouped_mask.shape[1],
        grouped_mask.shape[0],
    )
    split_mask = grouped_mask.copy()
    _, _, _, cells = split_component_hierarchy(
        split_mask,
        component_region,
        component_region,
        x,
        y,
        width,
        height,
    )
    return row_layout, cells


def build_cells_preview(image: np.ndarray, cells: list[dict]) -> np.ndarray:
    preview = image.copy()
    for cell in cells:
        top_left = (cell["x_start"], cell["y_start"])
        bottom_right = (cell["x_end"] - 1, cell["y_end"] - 1)
        cv2.rectangle(preview, top_left, bottom_right, (255, 255, 0), 1)
        cv2.putText(
            preview,
            f"R{cell['row_index']}C{cell['cell_index']}",
            (cell["x_start"] + 2, cell["y_start"] + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
    return preview


def validate_scene(scene_name: str, paths: dict) -> None:
    image = cv2.imread(str(paths["image"]))
    clean_mask = cv2.imread(str(paths["mask"]), cv2.IMREAD_GRAYSCALE)
    if image is None or clean_mask is None:
        raise FileNotFoundError(f"Could not load scene {scene_name}")
    if image.shape[:2] != clean_mask.shape:
        raise ValueError(f"Image and mask sizes differ for scene {scene_name}")

    component_count, component_labels, component_stats, _ = (
        cv2.connectedComponentsWithStats(clean_mask, connectivity=8)
    )
    grouping = group_stack_components(
        component_labels,
        component_stats,
        image.shape,
    )
    row_layout, cells = calculate_cells(grouping)

    output_directory = OUTPUT_DIRECTORY / f"bricks_{scene_name}"
    output_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(
        str(output_directory / "components.png"),
        build_component_preview(component_labels, component_stats),
    )
    cv2.imwrite(
        str(output_directory / "grouping.png"),
        build_grouping_preview(image, component_labels, grouping),
    )
    cv2.imwrite(str(output_directory / "grouped_mask.png"), grouping["grouped_mask"])
    cv2.imwrite(
        str(output_directory / "cells_preview.png"),
        build_cells_preview(image, cells),
    )

    report = {
        "scene": scene_name,
        "component_count": component_count - 1,
        "anchor_label": grouping["anchor_label"],
        "selected_labels": grouping["selected_labels"],
        "grouped_bbox": grouping["grouped_bbox"],
        "scaled_short_side": grouping["scaled_short_side"],
        "estimated_cell_count": len(cells),
        "row_layout": row_layout,
        "component_decisions": grouping["decisions"],
    }
    with (output_directory / "report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    accepted = len(grouping["selected_labels"])
    rejected = component_count - 1 - accepted
    print(
        f"Scene {scene_name}: accepted={accepted}, rejected={rejected}, "
        f"estimated_cells={len(cells)}"
    )


def main() -> None:
    for scene_name, paths in SCENES.items():
        validate_scene(scene_name, paths)
    print(f"Saved grouping validation to: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

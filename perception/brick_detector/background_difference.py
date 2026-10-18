import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from perception.inventory_manager.inventory import (
    build_partial_inventory,
    save_inventory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIRECTORY = PROJECT_ROOT / "data" / "images" / "zenodo_detection"

BACKGROUND_PATH = IMAGE_DIRECTORY / "background_empty.png"
CURRENT_PATH = IMAGE_DIRECTORY / "bricks_17.png"
DIFFERENCE_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "background_difference.png"
MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_raw.png"
CLEAN_MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_clean.png"
SPLIT_MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_split.png"
DETECTIONS_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "detections_preview.png"
INVENTORY_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "inventories" / "partial_inventory.json"
)
DIFFERENCE_THRESHOLD = 40.0
MORPH_KERNEL_SIZE = (3, 3)
MIN_COMPONENT_AREA = 100
REFERENCE_IMAGE_WIDTH = 812
REFERENCE_IMAGE_HEIGHT = 599
NOMINAL_BRICK_HEIGHT = 147.0
LOCAL_SEARCH_RADIUS_RATIO = 0.2
LOCAL_VALLEY_RATIO_THRESHOLD = 0.9
LAYOUT_SHORT_SIDE = 39.5
LAYOUT_HEIGHT_TOLERANCE = 0.10
LAYOUT_WIDTH_TOLERANCE = 0.25
MIN_COLUMN_COVERAGE = 0.15
COLUMN_SMOOTHING_WINDOW = 5
CUT_DISTANCE_WEIGHT = 0.2


def load_image(image_path: Path) -> np.ndarray:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return image


def find_occupied_columns(row_band: np.ndarray) -> np.ndarray:
    column_coverage = np.count_nonzero(row_band, axis=0) / row_band.shape[0]
    return np.flatnonzero(column_coverage >= MIN_COLUMN_COVERAGE)


def estimate_row_layout(
    component_region: np.ndarray,
    image_width: int,
    image_height: int,
) -> list[dict]:
    region_height = component_region.shape[0]
    row_counts = np.count_nonzero(component_region, axis=1)
    typical_row_width = max(1.0, float(np.percentile(row_counts, 90)))

    width_scale = image_width / REFERENCE_IMAGE_WIDTH
    height_scale = image_height / REFERENCE_IMAGE_HEIGHT
    dimensions = {
        "vertical": {
            "row_height": NOMINAL_BRICK_HEIGHT * height_scale,
            "brick_width": LAYOUT_SHORT_SIDE * width_scale,
        },
        "horizontal": {
            "row_height": LAYOUT_SHORT_SIDE * height_scale,
            "brick_width": NOMINAL_BRICK_HEIGHT * width_scale,
        },
    }

    @lru_cache(maxsize=None)
    def find_best_layout(
        row_start: int,
        previous_orientation: str,
    ) -> tuple[float, tuple] | None:
        if row_start == region_height:
            return 0.0, ()

        best_result = None
        for orientation, dimension in dimensions.items():
            expected_height = dimension["row_height"]
            expected_width = dimension["brick_width"]
            minimum_height = expected_height * (1.0 - LAYOUT_HEIGHT_TOLERANCE)
            maximum_height = expected_height * (1.0 + LAYOUT_HEIGHT_TOLERANCE)
            search_start = max(row_start + 1, round(row_start + minimum_height))
            search_end = min(region_height, round(row_start + maximum_height))

            for row_end in range(search_start, search_end + 1):
                row_band = component_region[row_start:row_end, :]
                occupied_columns = find_occupied_columns(row_band)
                if occupied_columns.size == 0:
                    continue

                row_width = int(occupied_columns[-1] - occupied_columns[0] + 1)
                brick_count = max(1, round(row_width / expected_width))
                expected_row_width = brick_count * expected_width
                width_error = abs(row_width - expected_row_width) / expected_row_width
                if width_error > LAYOUT_WIDTH_TOLERANCE:
                    continue

                remaining_layout = find_best_layout(row_end, orientation)
                if remaining_layout is None:
                    continue

                height_error = abs((row_end - row_start) - expected_height) / expected_height
                boundary_cost = (
                    0.0
                    if row_end == region_height
                    else row_counts[row_end] / typical_row_width
                )
                orientation_switch_cost = (
                    0.03
                    if previous_orientation and previous_orientation != orientation
                    else 0.0
                )
                row_cost = (
                    2.0 * height_error
                    + width_error
                    + 0.6 * boundary_cost
                    + orientation_switch_cost
                )
                total_cost = row_cost + remaining_layout[0]
                row_description = (
                    orientation,
                    row_start,
                    row_end,
                    brick_count,
                    round(row_cost, 3),
                )
                candidate = (total_cost, (row_description,) + remaining_layout[1])

                if best_result is None or total_cost < best_result[0]:
                    best_result = candidate

        return best_result

    result = find_best_layout(0, "")
    if result is None:
        return []

    return [
        {
            "orientation": orientation,
            "start_y": row_start,
            "end_y": row_end,
            "expected_bricks": brick_count,
            "score": row_cost,
        }
        for orientation, row_start, row_end, brick_count, row_cost in result[1]
    ]


def split_component_hierarchy(
    split_mask: np.ndarray,
    component_region: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[list[int], list[int], list[int], list[dict]]:
    image_height, image_width = split_mask.shape
    width_scale = image_width / REFERENCE_IMAGE_WIDTH
    row_layout = estimate_row_layout(
        component_region,
        image_width,
        image_height,
    )
    if not row_layout:
        return [], [], [], []

    horizontal_splits = []
    vertical_splits = []
    geometry_fallback_splits = []
    cells = []

    for row in row_layout[:-1]:
        split_y = y + row["end_y"]
        if split_y < y + height:
            split_mask[split_y, x : x + width] = 0
            horizontal_splits.append(split_y)

    for row_index, row in enumerate(row_layout, start=1):
        row_start = row["start_y"]
        row_end = row["end_y"]
        row_band = component_region[row_start:row_end, :]
        occupied_columns = find_occupied_columns(row_band)
        if occupied_columns.size == 0:
            continue

        column_start = int(occupied_columns[0])
        column_end = int(occupied_columns[-1]) + 1
        row_region = row_band[:, column_start:column_end]
        row_width = row_region.shape[1]
        column_count = row["expected_bricks"]
        brick_width = (
            LAYOUT_SHORT_SIDE
            if row["orientation"] == "vertical"
            else NOMINAL_BRICK_HEIGHT
        ) * width_scale
        column_radius = max(1, round(brick_width * LOCAL_SEARCH_RADIUS_RATIO))

        column_counts = np.count_nonzero(row_region, axis=0)
        smoothing_kernel = (
            np.ones(COLUMN_SMOOTHING_WINDOW) / COLUMN_SMOOTHING_WINDOW
        )
        smoothed_column_counts = np.convolve(
            column_counts,
            smoothing_kernel,
            mode="same",
        )
        typical_column_height = np.percentile(smoothed_column_counts, 90)
        row_vertical_splits = []

        for grid_column in range(1, column_count):
            expected_x = round(grid_column * row_width / column_count)
            search_start = max(0, expected_x - column_radius)
            search_end = min(row_width, expected_x + column_radius + 1)
            candidate_positions = np.arange(search_start, search_end)
            occupancy_cost = (
                smoothed_column_counts[search_start:search_end]
                / typical_column_height
            )
            distance_cost = (
                np.abs(candidate_positions - expected_x) / column_radius
            )
            combined_cost = (
                occupancy_cost + CUT_DISTANCE_WEIGHT * distance_cost
            )
            relative_x = search_start + int(np.argmin(combined_cost))

            visual_valley_found = (
                smoothed_column_counts[relative_x]
                < typical_column_height * LOCAL_VALLEY_RATIO_THRESHOLD
            )
            split_x = x + column_start + relative_x
            split_mask[y + row_start : y + row_end, split_x] = 0
            vertical_splits.append(split_x)
            row_vertical_splits.append(split_x)

            if not visual_valley_found:
                geometry_fallback_splits.append(split_x)

        cell_boundaries = (
            [x + column_start]
            + sorted(row_vertical_splits)
            + [x + column_end]
        )
        for cell_index in range(len(cell_boundaries) - 1):
            cells.append(
                {
                    "row_index": row_index,
                    "cell_index": cell_index + 1,
                    "orientation": row["orientation"],
                    "x_start": cell_boundaries[cell_index],
                    "x_end": cell_boundaries[cell_index + 1],
                    "y_start": y + row_start,
                    "y_end": y + row_end,
                }
            )

    return horizontal_splits, vertical_splits, geometry_fallback_splits, cells


def main() -> None:
    background = load_image(BACKGROUND_PATH)
    current = load_image(CURRENT_PATH)

    background_was_resized = background.shape[:2] != current.shape[:2]
    if background_was_resized:
        current_height, current_width = current.shape[:2]
        background = cv2.resize(
            background,
            (current_width, current_height),
            interpolation=cv2.INTER_LINEAR,
        )

    background_lab = cv2.cvtColor(background, cv2.COLOR_BGR2LAB).astype(np.float32)
    current_lab = cv2.cvtColor(current, cv2.COLOR_BGR2LAB).astype(np.float32)

    difference = np.linalg.norm(current_lab - background_lab, axis=2)
    difference_view = cv2.normalize(difference, None, 0, 255, cv2.NORM_MINMAX)
    difference_view = difference_view.astype(np.uint8)

    mask = np.where(difference > DIFFERENCE_THRESHOLD, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_KERNEL_SIZE)
    opened_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    component_count, component_labels, stats, _ = cv2.connectedComponentsWithStats(
        opened_mask,
        connectivity=8,
    )
    clean_mask = np.zeros_like(opened_mask)
    for label in range(1, component_count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area >= MIN_COMPONENT_AREA:
            clean_mask[component_labels == label] = 255

    clean_component_count, clean_component_labels, clean_stats, _ = (
        cv2.connectedComponentsWithStats(clean_mask, connectivity=8)
    )
    if clean_component_count == 1:
        raise ValueError("No foreground region found in clean mask")

    main_component_label = 1 + int(
        np.argmax(clean_stats[1:, cv2.CC_STAT_AREA])
    )
    main_x, main_y, main_width, main_height = clean_stats[
        main_component_label, :4
    ]
    main_component_region = (
        clean_component_labels[
            main_y : main_y + main_height,
            main_x : main_x + main_width,
        ]
        == main_component_label
    )
    estimated_row_layout = estimate_row_layout(
        main_component_region,
        current.shape[1],
        current.shape[0],
    )

    split_mask = clean_mask.copy()
    horizontal_splits = []
    vertical_splits = []
    geometry_fallback_splits = []
    detection_cells = []
    for label in range(1, clean_component_count):
        x, y, width, height = clean_stats[label, :4]
        component_region = (
            clean_component_labels[y : y + height, x : x + width] == label
        )
        (
            component_horizontal_splits,
            component_vertical_splits,
            component_geometry_fallback_splits,
            component_cells,
        ) = (
            split_component_hierarchy(
                split_mask,
                component_region,
                int(x),
                int(y),
                int(width),
                int(height),
            )
        )
        horizontal_splits.extend(component_horizontal_splits)
        vertical_splits.extend(component_vertical_splits)
        geometry_fallback_splits.extend(component_geometry_fallback_splits)
        for cell in component_cells:
            cell["component_label"] = label
        detection_cells.extend(component_cells)

    detections = []
    cell_occupancies = []
    for cell in detection_cells:
        cell_region = (
            clean_component_labels[
                cell["y_start"] : cell["y_end"],
                cell["x_start"] : cell["x_end"],
            ]
            == cell["component_label"]
        )
        foreground_y, foreground_x = np.nonzero(cell_region)
        area = foreground_x.size
        if area < MIN_COMPONENT_AREA:
            continue

        cell_area = cell_region.shape[0] * cell_region.shape[1]
        cell_occupancies.append(area / cell_area)
        box_x = cell["x_start"] + int(foreground_x.min())
        box_y = cell["y_start"] + int(foreground_y.min())
        box_width = int(foreground_x.max() - foreground_x.min() + 1)
        box_height = int(foreground_y.max() - foreground_y.min() + 1)
        center_x = cell["x_start"] + float(foreground_x.mean())
        center_y = cell["y_start"] + float(foreground_y.mean())
        detections.append(
            {
                "bbox_px": {
                    "x": int(box_x),
                    "y": int(box_y),
                    "width": int(box_width),
                    "height": int(box_height),
                },
                "center_px": {
                    "x": round(float(center_x), 2),
                    "y": round(float(center_y), 2),
                },
                "color_group": "unknown",
                "color_score": 0.0,
            }
        )

    detections.sort(key=lambda item: (item["bbox_px"]["y"], item["bbox_px"]["x"]))
    for index, detection in enumerate(detections, start=1):
        detection["id"] = f"brick_{index:03d}"

    inventory = build_partial_inventory(
        image_id=CURRENT_PATH.stem,
        image_shape=current.shape,
        detections=detections,
    )

    preview = current.copy()
    for detection in detections:
        box = detection["bbox_px"]
        center = detection["center_px"]
        top_left = (box["x"], box["y"])
        bottom_right = (
            box["x"] + box["width"] - 1,
            box["y"] + box["height"] - 1,
        )
        center_point = (round(center["x"]), round(center["y"]))

        cv2.rectangle(preview, top_left, bottom_right, (0, 255, 0), 2)
        cv2.circle(preview, center_point, 4, (0, 0, 255), -1)
        cv2.putText(
            preview,
            detection["id"],
            (box["x"], max(box["y"] - 8, 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 0),
            1,
            cv2.LINE_AA,
        )

    DIFFERENCE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(DIFFERENCE_OUTPUT_PATH), difference_view):
        raise OSError(f"Could not write image: {DIFFERENCE_OUTPUT_PATH}")
    if not cv2.imwrite(str(MASK_OUTPUT_PATH), mask):
        raise OSError(f"Could not write image: {MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(CLEAN_MASK_OUTPUT_PATH), clean_mask):
        raise OSError(f"Could not write image: {CLEAN_MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(SPLIT_MASK_OUTPUT_PATH), split_mask):
        raise OSError(f"Could not write image: {SPLIT_MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(DETECTIONS_OUTPUT_PATH), preview):
        raise OSError(f"Could not write image: {DETECTIONS_OUTPUT_PATH}")
    save_inventory(inventory, INVENTORY_OUTPUT_PATH)

    print(f"Saved difference image to: {DIFFERENCE_OUTPUT_PATH}")
    print(f"Saved raw mask to: {MASK_OUTPUT_PATH}")
    print(f"Saved clean mask to: {CLEAN_MASK_OUTPUT_PATH}")
    print(f"Saved split mask to: {SPLIT_MASK_OUTPUT_PATH}")
    print(f"Saved detection preview to: {DETECTIONS_OUTPUT_PATH}")
    print(f"Saved partial inventory to: {INVENTORY_OUTPUT_PATH}")
    print(f"Background resized to current image: {background_was_resized}")
    print(f"Detected horizontal splits at y={horizontal_splits}")
    print(f"Detected vertical splits at x={vertical_splits}")
    print(f"Geometry fallback splits at x={geometry_fallback_splits}")
    if cell_occupancies:
        print(
            "Cell occupancy: "
            f"min={min(cell_occupancies):.3f}, "
            f"mean={np.mean(cell_occupancies):.3f}, "
            f"max={max(cell_occupancies):.3f}"
        )
    print("Estimated row layout:")
    for row_index, row in enumerate(estimated_row_layout, start=1):
        global_start_y = int(main_y) + row["start_y"]
        global_end_y = int(main_y) + row["end_y"]
        print(
            f"  Row {row_index}: orientation={row['orientation']}, "
            f"y={global_start_y}:{global_end_y}, "
            f"expected_bricks={row['expected_bricks']}, "
            f"score={row['score']:.3f}"
        )
    print(json.dumps(inventory, indent=2))


if __name__ == "__main__":
    main()

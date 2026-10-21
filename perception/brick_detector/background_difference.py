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
CURRENT_PATH = IMAGE_DIRECTORY / "bricks_70.png"
ALIGNED_BACKGROUND_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "aligned_background.png"
DIFFERENCE_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "background_difference.png"
MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_raw.png"
CLEAN_MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_clean.png"
GROUPED_MASK_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "brick_mask_grouped.png"
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
LAYOUT_SHORT_SIDE = 37.0
LAYOUT_HEIGHT_TOLERANCE = 0.10
LAYOUT_WIDTH_TOLERANCE = 0.25
MIN_COLUMN_COVERAGE = 0.15
COLUMN_SMOOTHING_WINDOW = 5
CUT_DISTANCE_WEIGHT = 0.2
MIN_FOREGROUND_SPAN_RATIO = 0.5
LOCAL_RECOVERY_OCCUPANCY_THRESHOLD = 0.25
LOCAL_RECOVERY_DIFFERENCE_THRESHOLD = 25.0
MIN_NOMINAL_CELL_WIDTH_RATIO = 0.8
MIN_HORIZONTAL_OVERLAP = 0.5
ALIGNMENT_REFERENCE_WIDTH = 828
ALIGNMENT_REFERENCE_HEIGHT = 611
ALIGNMENT_LEFT_WIDTH = 330
ALIGNMENT_TOP_HEIGHT = 25
ALIGNMENT_BOTTOM_HEIGHT = 35
ALIGNMENT_RIGHT_WIDTH = 25
ALIGNMENT_BLUR_SIZE = (5, 5)
ALIGNMENT_MAX_ITERATIONS = 200
ALIGNMENT_EPSILON = 1e-6
GRADIENT_BLUR_SIZE = (5, 5)
GRADIENT_X_RADIUS_RATIO = 0.25
GRADIENT_Y_RADIUS_RATIO = 0.25
GRADIENT_MAX_X_RADIUS = 35
GRADIENT_MAX_Y_RADIUS = 15
GRADIENT_MIN_RADIUS = 3
GRADIENT_MIN_MEAN = 10.0
GRADIENT_MIN_PROMINENCE_RATIO = 1.5
GRADIENT_MIN_IMPROVEMENT_RATIO = 1.25
GRADIENT_MIN_SHIFT = 3
GRADIENT_MIN_SIZE_RATIO = 0.5
GRADIENT_MAX_SIZE_RATIO = 1.5
STACK_TOP_SEARCH_DISTANCE_RATIO = 1.5
STACK_TOP_MIN_SHIFT = 3
STACK_TOP_MIN_GRADIENT_MEAN = 10.0
STACK_TOP_MIN_PROMINENCE_RATIO = 1.5
STACK_TOP_MAX_BEFORE_COVERAGE = 0.25
STACK_TOP_MIN_AFTER_COVERAGE = 0.5
STACK_TOP_COVERAGE_WINDOW = 5


def load_image(image_path: Path) -> np.ndarray:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return image


def build_alignment_mask(image_shape: tuple[int, ...]) -> np.ndarray:
    image_height, image_width = image_shape[:2]
    left_width = round(
        ALIGNMENT_LEFT_WIDTH * image_width / ALIGNMENT_REFERENCE_WIDTH
    )
    top_height = round(
        ALIGNMENT_TOP_HEIGHT * image_height / ALIGNMENT_REFERENCE_HEIGHT
    )
    bottom_height = round(
        ALIGNMENT_BOTTOM_HEIGHT * image_height / ALIGNMENT_REFERENCE_HEIGHT
    )
    right_width = round(
        ALIGNMENT_RIGHT_WIDTH * image_width / ALIGNMENT_REFERENCE_WIDTH
    )

    alignment_mask = np.full((image_height, image_width), 255, dtype=np.uint8)
    alignment_mask[
        top_height : image_height - bottom_height,
        left_width : image_width - right_width,
    ] = 0
    return alignment_mask


def align_background(
    background: np.ndarray,
    current: np.ndarray,
) -> tuple[np.ndarray, float | None, np.ndarray]:
    current_height, current_width = current.shape[:2]
    resized_background = cv2.resize(
        background,
        (current_width, current_height),
        interpolation=cv2.INTER_LINEAR,
    )

    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    background_gray = cv2.cvtColor(resized_background, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.GaussianBlur(current_gray, ALIGNMENT_BLUR_SIZE, 0)
    background_gray = cv2.GaussianBlur(
        background_gray,
        ALIGNMENT_BLUR_SIZE,
        0,
    )
    alignment_mask = build_alignment_mask(current.shape)
    warp_matrix = np.eye(2, 3, dtype=np.float32)
    termination_criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        ALIGNMENT_MAX_ITERATIONS,
        ALIGNMENT_EPSILON,
    )

    try:
        correlation, warp_matrix = cv2.findTransformECC(
            current_gray,
            background_gray,
            warp_matrix,
            cv2.MOTION_AFFINE,
            termination_criteria,
            alignment_mask,
            5,
        )
    except cv2.error:
        return resized_background, None, warp_matrix

    aligned_background = cv2.warpAffine(
        resized_background,
        warp_matrix,
        (current_width, current_height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return aligned_background, float(correlation), warp_matrix


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
        "decisions": decisions,
    }


def calculate_local_search_bbox(
    cell: dict,
    image_width: int,
) -> tuple[int, int, int, int]:
    expected_width = (
        LAYOUT_SHORT_SIDE
        if cell["orientation"] == "vertical"
        else NOMINAL_BRICK_HEIGHT
    ) * image_width / REFERENCE_IMAGE_WIDTH
    current_width = cell["x_end"] - cell["x_start"]
    if current_width >= expected_width * MIN_NOMINAL_CELL_WIDTH_RATIO:
        return (
            cell["x_start"],
            cell["y_start"],
            cell["x_end"],
            cell["y_end"],
        )

    expected_width = round(expected_width)
    if cell["cell_index"] == 1:
        search_x_end = cell["x_end"]
        search_x_start = search_x_end - expected_width
    else:
        search_x_start = cell["x_start"]
        search_x_end = search_x_start + expected_width

    return (
        max(0, search_x_start),
        cell["y_start"],
        min(image_width, search_x_end),
        cell["y_end"],
    )


def recover_local_foreground(
    difference: np.ndarray,
    cell: dict,
    observed_bbox: tuple[int, int, int, int],
) -> dict | None:
    search_x0, search_y0, search_x1, search_y1 = calculate_local_search_bbox(
        cell,
        difference.shape[1],
    )
    local_difference = difference[search_y0:search_y1, search_x0:search_x1]
    low_mask = (
        local_difference > LOCAL_RECOVERY_DIFFERENCE_THRESHOLD
    ).astype(np.uint8)

    observed_x0, observed_y0, observed_x1, observed_y1 = observed_bbox
    seed_x0 = max(0, observed_x0 - search_x0)
    seed_y0 = max(0, observed_y0 - search_y0)
    seed_x1 = min(low_mask.shape[1], observed_x1 - search_x0)
    seed_y1 = min(low_mask.shape[0], observed_y1 - search_y0)
    seed_mask = np.zeros_like(low_mask)
    seed_mask[seed_y0:seed_y1, seed_x0:seed_x1] = (
        local_difference[seed_y0:seed_y1, seed_x0:seed_x1]
        > DIFFERENCE_THRESHOLD
    )
    if not np.any(seed_mask):
        return None

    component_count, component_labels, _, _ = cv2.connectedComponentsWithStats(
        low_mask,
        connectivity=8,
    )
    if component_count == 1:
        return None

    connected_labels = np.unique(component_labels[seed_mask > 0])
    connected_labels = connected_labels[connected_labels > 0]
    recovered_region = np.isin(component_labels, connected_labels)
    foreground_y, foreground_x = np.nonzero(recovered_region)
    if foreground_x.size < MIN_COMPONENT_AREA:
        return None

    return {
        "bbox": (
            search_x0 + int(foreground_x.min()),
            search_y0 + int(foreground_y.min()),
            int(foreground_x.max() - foreground_x.min() + 1),
            int(foreground_y.max() - foreground_y.min() + 1),
        ),
        "center": (
            search_x0 + float(foreground_x.mean()),
            search_y0 + float(foreground_y.mean()),
        ),
    }


def find_local_gradient_edge(
    gradient: np.ndarray,
    current_position: int,
    span_start: int,
    span_end: int,
    radius: int,
    axis: str,
) -> tuple[int, bool]:
    if span_end <= span_start:
        return current_position, False

    axis_limit = gradient.shape[1] if axis == "x" else gradient.shape[0]
    search_start = max(0, current_position - radius)
    search_end = min(axis_limit, current_position + radius + 1)
    if search_end <= search_start:
        return current_position, False

    if axis == "x":
        search_region = gradient[
            span_start:span_end,
            search_start:search_end,
        ]
        profile = search_region.mean(axis=0)
    elif axis == "y":
        search_region = gradient[
            search_start:search_end,
            span_start:span_end,
        ]
        profile = search_region.mean(axis=1)
    else:
        raise ValueError(f"Unsupported gradient axis: {axis}")

    if profile.size == 0:
        return current_position, False

    relative_position = int(np.argmax(profile))
    candidate_position = search_start + relative_position
    peak_strength = float(profile[relative_position])
    baseline_strength = max(float(np.median(profile)), 1.0)
    current_profile_index = current_position - search_start
    current_strength = max(float(profile[current_profile_index]), 1.0)
    confidence_is_sufficient = (
        abs(candidate_position - current_position) >= GRADIENT_MIN_SHIFT
        and peak_strength >= GRADIENT_MIN_MEAN
        and peak_strength / baseline_strength >= GRADIENT_MIN_PROMINENCE_RATIO
        and peak_strength / current_strength >= GRADIENT_MIN_IMPROVEMENT_RATIO
    )
    if not confidence_is_sufficient:
        return current_position, False

    return candidate_position, True


def refine_bbox_with_gradients(
    sobel_x: np.ndarray,
    sobel_y: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], int]:
    x0, y0, x1, y1 = bbox
    original_width = x1 - x0
    original_height = y1 - y0
    if original_width <= 0 or original_height <= 0:
        return bbox, 0

    image_height, image_width = sobel_x.shape
    scaled_max_x_radius = max(
        GRADIENT_MIN_RADIUS,
        round(GRADIENT_MAX_X_RADIUS * image_width / REFERENCE_IMAGE_WIDTH),
    )
    scaled_max_y_radius = max(
        GRADIENT_MIN_RADIUS,
        round(GRADIENT_MAX_Y_RADIUS * image_height / REFERENCE_IMAGE_HEIGHT),
    )
    x_radius = min(
        scaled_max_x_radius,
        max(GRADIENT_MIN_RADIUS, round(original_width * GRADIENT_X_RADIUS_RATIO)),
    )
    y_radius = min(
        scaled_max_y_radius,
        max(GRADIENT_MIN_RADIUS, round(original_height * GRADIENT_Y_RADIUS_RATIO)),
    )

    refined_x0, left_accepted = find_local_gradient_edge(
        sobel_x,
        x0,
        y0,
        y1,
        x_radius,
        "x",
    )
    refined_x1, right_accepted = find_local_gradient_edge(
        sobel_x,
        x1,
        y0,
        y1,
        x_radius,
        "x",
    )
    refined_width = refined_x1 - refined_x0
    if not (
        original_width * GRADIENT_MIN_SIZE_RATIO
        <= refined_width
        <= original_width * GRADIENT_MAX_SIZE_RATIO
    ):
        refined_x0 = x0
        refined_x1 = x1
        left_accepted = False
        right_accepted = False

    refined_y0, top_accepted = find_local_gradient_edge(
        sobel_y,
        y0,
        refined_x0,
        refined_x1,
        y_radius,
        "y",
    )
    refined_y1, bottom_accepted = find_local_gradient_edge(
        sobel_y,
        y1,
        refined_x0,
        refined_x1,
        y_radius,
        "y",
    )
    refined_height = refined_y1 - refined_y0
    if not (
        original_height * GRADIENT_MIN_SIZE_RATIO
        <= refined_height
        <= original_height * GRADIENT_MAX_SIZE_RATIO
    ):
        refined_y0 = y0
        refined_y1 = y1
        top_accepted = False
        bottom_accepted = False

    accepted_side_count = sum(
        (left_accepted, right_accepted, top_accepted, bottom_accepted)
    )
    return (
        refined_x0,
        refined_y0,
        refined_x1,
        refined_y1,
    ), accepted_side_count


def refine_stack_top(
    sobel_y: np.ndarray,
    grouped_mask: np.ndarray,
    grouped_bbox: dict,
) -> tuple[dict, bool]:
    x0 = grouped_bbox["x"]
    y0 = grouped_bbox["y"]
    x1 = x0 + grouped_bbox["width"]
    y1 = y0 + grouped_bbox["height"]
    scaled_short_side = (
        LAYOUT_SHORT_SIDE * grouped_mask.shape[0] / REFERENCE_IMAGE_HEIGHT
    )
    search_distance = round(
        scaled_short_side * STACK_TOP_SEARCH_DISTANCE_RATIO
    )
    search_end = min(y1, y0 + search_distance)
    if search_end <= y0:
        return grouped_bbox.copy(), False

    gradient_profile = sobel_y[y0:search_end, x0:x1].mean(axis=1)
    if gradient_profile.size == 0:
        return grouped_bbox.copy(), False

    relative_position = int(np.argmax(gradient_profile))
    candidate_y = y0 + relative_position
    peak_strength = float(gradient_profile[relative_position])
    baseline_strength = max(float(np.median(gradient_profile)), 1.0)

    row_coverage = np.count_nonzero(
        grouped_mask[y0:search_end, x0:x1],
        axis=1,
    ) / max(1, x1 - x0)
    before_start = 0
    before_end = max(0, relative_position - 1)
    after_start = min(row_coverage.size, relative_position + 1)
    after_end = min(
        row_coverage.size,
        after_start + STACK_TOP_COVERAGE_WINDOW,
    )
    if before_end <= before_start or after_end <= after_start:
        return grouped_bbox.copy(), False

    before_coverage = float(np.median(row_coverage[before_start:before_end]))
    after_coverage = float(np.median(row_coverage[after_start:after_end]))
    refinement_is_valid = (
        candidate_y - y0 >= STACK_TOP_MIN_SHIFT
        and peak_strength >= STACK_TOP_MIN_GRADIENT_MEAN
        and peak_strength / baseline_strength >= STACK_TOP_MIN_PROMINENCE_RATIO
        and before_coverage <= STACK_TOP_MAX_BEFORE_COVERAGE
        and after_coverage >= STACK_TOP_MIN_AFTER_COVERAGE
    )
    if not refinement_is_valid:
        return grouped_bbox.copy(), False

    refined_bbox = grouped_bbox.copy()
    refined_bbox["y"] = candidate_y
    refined_bbox["height"] = y1 - candidate_y
    return refined_bbox, True


def clamp_bbox_to_envelope(
    bbox: tuple[int, int, int, int],
    envelope: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], int]:
    x0, y0, x1, y1 = bbox
    envelope_x0, envelope_y0, envelope_x1, envelope_y1 = envelope
    clamped_bbox = (
        max(x0, envelope_x0),
        max(y0, envelope_y0),
        min(x1, envelope_x1),
        min(y1, envelope_y1),
    )
    clamped_side_count = sum(
        original != clamped
        for original, clamped in zip(bbox, clamped_bbox)
    )
    return clamped_bbox, clamped_side_count


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
    recovery_region: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    diagnostics: dict | None = None,
) -> tuple[list[int], list[int], list[int], list[dict]]:
    image_height, image_width = split_mask.shape
    width_scale = image_width / REFERENCE_IMAGE_WIDTH
    row_layout = estimate_row_layout(
        component_region,
        image_width,
        image_height,
    )
    if not row_layout:
        if diagnostics is not None:
            diagnostics["previous_row_geometry_fallbacks"] = 0
        return [], [], [], []

    horizontal_splits = []
    vertical_splits = []
    geometry_fallback_splits = []
    cells = []
    previous_row_geometry = None
    previous_row_geometry_fallback_count = 0

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
        column_count = row["expected_bricks"]
        brick_width = (
            LAYOUT_SHORT_SIDE
            if row["orientation"] == "vertical"
            else NOMINAL_BRICK_HEIGHT
        ) * width_scale
        if (
            previous_row_geometry is not None
            and previous_row_geometry["orientation"] == row["orientation"]
            and previous_row_geometry["column_count"] > column_count
            and abs(previous_row_geometry["column_end"] - column_end)
            <= brick_width * 0.25
        ):
            missing_region = recovery_region[
                row_start:row_end,
                previous_row_geometry["column_start"]:column_start,
            ]
            if np.count_nonzero(missing_region) >= MIN_COMPONENT_AREA:
                column_start = previous_row_geometry["column_start"]
                column_end = previous_row_geometry["column_end"]
                column_count = previous_row_geometry["column_count"]
                previous_row_geometry_fallback_count += 1

        row_region = recovery_region[row_start:row_end, column_start:column_end]
        row_width = row_region.shape[1]
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

        previous_row_geometry = {
            "orientation": row["orientation"],
            "column_start": column_start,
            "column_end": column_end,
            "column_count": column_count,
        }

    if diagnostics is not None:
        diagnostics["previous_row_geometry_fallbacks"] = (
            previous_row_geometry_fallback_count
        )
    return horizontal_splits, vertical_splits, geometry_fallback_splits, cells


def run_pallet_pipeline(
    current: np.ndarray,
    background: np.ndarray,
) -> tuple[list[dict], dict, dict[str, np.ndarray]]:
    """Run pallet detection in memory and return detections and diagnostics."""
    if current.size == 0 or background.size == 0:
        raise ValueError("Current and background images must not be empty")
    background_was_resized = background.shape[:2] != current.shape[:2]
    background, alignment_correlation, alignment_warp = align_background(
        background,
        current,
    )

    background_lab = cv2.cvtColor(background, cv2.COLOR_BGR2LAB).astype(np.float32)
    current_lab = cv2.cvtColor(current, cv2.COLOR_BGR2LAB).astype(np.float32)

    difference = np.linalg.norm(current_lab - background_lab, axis=2)
    difference_view = cv2.normalize(difference, None, 0, 255, cv2.NORM_MINMAX)
    difference_view = difference_view.astype(np.uint8)
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    gradient_input = cv2.GaussianBlur(current_gray, GRADIENT_BLUR_SIZE, 0)
    sobel_x = np.abs(cv2.Sobel(gradient_input, cv2.CV_64F, 1, 0, ksize=3))
    sobel_y = np.abs(cv2.Sobel(gradient_input, cv2.CV_64F, 0, 1, ksize=3))

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
        # A cleaned-away foreground or a failed alignment is not evidence of
        # an empty pallet. Preserve the error for those ambiguous cases.
        if np.any(mask) or alignment_correlation is None:
            raise ValueError("No foreground region found in clean mask")
        diagnostics = {
            "background_was_resized": background_was_resized,
            "alignment_correlation": float(alignment_correlation),
            "alignment_affine_matrix": alignment_warp.tolist(),
            "selected_component_labels": [],
            "anchor_component_label": None,
            "local_recovery_count": 0,
            "bbox_fallback_count": 0,
            "previous_row_geometry_fallbacks": 0,
            "gradient_refined_detection_count": 0,
            "gradient_refined_side_count": 0,
            "stack_top_original_y": None,
            "stack_top_refined_y": None,
            "stack_top_refinement_applied": False,
            "envelope_clamped_detection_count": 0,
            "envelope_clamped_side_count": 0,
            "horizontal_splits": [],
            "vertical_splits": [],
            "geometry_fallback_splits": [],
            "cell_occupancy": None,
            "estimated_row_layout": [],
            "detection_count": 0,
        }
        artifacts = {
            "aligned_background": background,
            "difference": difference_view,
            "raw_mask": mask,
            "clean_mask": clean_mask,
            "grouped_mask": clean_mask.copy(),
            "split_mask": clean_mask.copy(),
        }
        return [], diagnostics, artifacts

    grouping = group_stack_components(
        clean_component_labels,
        clean_stats,
        current.shape,
    )
    grouped_mask = grouping["grouped_mask"]
    original_grouped_bbox = grouping["grouped_bbox"]
    grouped_bbox, stack_top_refinement_applied = refine_stack_top(
        sobel_y,
        grouped_mask,
        original_grouped_bbox,
    )
    grouped_x = grouped_bbox["x"]
    grouped_y = grouped_bbox["y"]
    grouped_width = grouped_bbox["width"]
    grouped_height = grouped_bbox["height"]
    grouped_region = grouped_mask[
        grouped_y : grouped_y + grouped_height,
        grouped_x : grouped_x + grouped_width,
    ] > 0
    estimated_row_layout = estimate_row_layout(
        grouped_region,
        current.shape[1],
        current.shape[0],
    )

    split_mask = grouped_mask.copy()
    horizontal_splits = []
    vertical_splits = []
    geometry_fallback_splits = []
    detection_cells = []
    split_diagnostics = {}
    (
        horizontal_splits,
        vertical_splits,
        geometry_fallback_splits,
        detection_cells,
    ) = split_component_hierarchy(
        split_mask,
        grouped_region,
        grouped_region,
        grouped_x,
        grouped_y,
        grouped_width,
        grouped_height,
        diagnostics=split_diagnostics,
    )

    detections = []
    cell_occupancies = []
    local_recovery_count = 0
    bbox_fallback_count = 0
    gradient_refined_detection_count = 0
    gradient_refined_side_count = 0
    envelope_clamped_detection_count = 0
    envelope_clamped_side_count = 0
    stack_envelope = (
        grouped_x,
        grouped_y,
        grouped_x + grouped_width,
        grouped_y + grouped_height,
    )
    for cell in detection_cells:
        cell_region = grouped_mask[
            cell["y_start"] : cell["y_end"],
            cell["x_start"] : cell["x_end"],
        ] > 0
        foreground_y, foreground_x = np.nonzero(cell_region)
        area = foreground_x.size
        if area < MIN_COMPONENT_AREA:
            continue

        cell_area = cell_region.shape[0] * cell_region.shape[1]
        cell_occupancy = area / cell_area
        cell_occupancies.append(cell_occupancy)
        box_x = cell["x_start"] + int(foreground_x.min())
        box_y = cell["y_start"] + int(foreground_y.min())
        box_width = int(foreground_x.max() - foreground_x.min() + 1)
        box_height = int(foreground_y.max() - foreground_y.min() + 1)
        center_x = cell["x_start"] + float(foreground_x.mean())
        center_y = cell["y_start"] + float(foreground_y.mean())
        cell_width = cell["x_end"] - cell["x_start"]
        cell_height = cell["y_end"] - cell["y_start"]
        local_recovery_applied = False
        if cell_occupancy < LOCAL_RECOVERY_OCCUPANCY_THRESHOLD:
            local_recovery = recover_local_foreground(
                difference,
                cell,
                (
                    box_x,
                    box_y,
                    box_x + box_width,
                    box_y + box_height,
                ),
            )
            if local_recovery is not None:
                box_x, box_y, box_width, box_height = local_recovery["bbox"]
                center_x, center_y = local_recovery["center"]
                local_recovery_applied = True
                local_recovery_count += 1

        if not local_recovery_applied and (
            box_width / cell_width < MIN_FOREGROUND_SPAN_RATIO
            or box_height / cell_height < MIN_FOREGROUND_SPAN_RATIO
        ):
            bbox_fallback_count += 1
            box_x = cell["x_start"]
            box_y = cell["y_start"]
            box_width = cell_width
            box_height = cell_height
            center_x = box_x + box_width / 2.0
            center_y = box_y + box_height / 2.0

        refined_bbox, refined_side_count = refine_bbox_with_gradients(
            sobel_x,
            sobel_y,
            (
                box_x,
                box_y,
                box_x + box_width,
                box_y + box_height,
            ),
        )
        if refined_side_count > 0:
            gradient_refined_detection_count += 1
            gradient_refined_side_count += refined_side_count

        contained_bbox, clamped_side_count = clamp_bbox_to_envelope(
            refined_bbox,
            stack_envelope,
        )
        if clamped_side_count > 0:
            envelope_clamped_detection_count += 1
            envelope_clamped_side_count += clamped_side_count

        if refined_side_count > 0 or clamped_side_count > 0:
            refined_x0, refined_y0, refined_x1, refined_y1 = contained_bbox
            box_x = refined_x0
            box_y = refined_y0
            box_width = refined_x1 - refined_x0
            box_height = refined_y1 - refined_y0
            center_x = box_x + box_width / 2.0
            center_y = box_y + box_height / 2.0
        detections.append(
            {
                "_sort_row_y": cell["y_start"],
                "_sort_column_x": cell["x_start"],
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

    detections.sort(
        key=lambda item: (item["_sort_row_y"], item["_sort_column_x"])
    )
    for index, detection in enumerate(detections, start=1):
        detection.pop("_sort_row_y")
        detection.pop("_sort_column_x")
        detection["id"] = f"brick_{index:03d}"

    normalized_row_layout = [
        {
            "orientation": row["orientation"],
            "start_y": int(grouped_y + row["start_y"]),
            "end_y": int(grouped_y + row["end_y"]),
            "expected_bricks": int(row["expected_bricks"]),
            "score": float(row["score"]),
        }
        for row in estimated_row_layout
    ]
    diagnostics = {
        "background_was_resized": background_was_resized,
        "alignment_correlation": (
            None
            if alignment_correlation is None
            else float(alignment_correlation)
        ),
        "alignment_affine_matrix": alignment_warp.tolist(),
        "selected_component_labels": [
            int(label) for label in grouping["selected_labels"]
        ],
        "anchor_component_label": int(grouping["anchor_label"]),
        "local_recovery_count": int(local_recovery_count),
        "bbox_fallback_count": int(bbox_fallback_count),
        "previous_row_geometry_fallbacks": int(
            split_diagnostics["previous_row_geometry_fallbacks"]
        ),
        "gradient_refined_detection_count": int(
            gradient_refined_detection_count
        ),
        "gradient_refined_side_count": int(gradient_refined_side_count),
        "stack_top_original_y": int(original_grouped_bbox["y"]),
        "stack_top_refined_y": int(grouped_bbox["y"]),
        "stack_top_refinement_applied": bool(stack_top_refinement_applied),
        "envelope_clamped_detection_count": int(
            envelope_clamped_detection_count
        ),
        "envelope_clamped_side_count": int(envelope_clamped_side_count),
        "horizontal_splits": [int(value) for value in horizontal_splits],
        "vertical_splits": [int(value) for value in vertical_splits],
        "geometry_fallback_splits": [
            int(value) for value in geometry_fallback_splits
        ],
        "cell_occupancy": (
            None
            if not cell_occupancies
            else {
                "minimum": float(min(cell_occupancies)),
                "mean": float(np.mean(cell_occupancies)),
                "maximum": float(max(cell_occupancies)),
            }
        ),
        "estimated_row_layout": normalized_row_layout,
        "detection_count": int(len(detections)),
    }
    artifacts = {
        "aligned_background": background,
        "difference": difference_view,
        "raw_mask": mask,
        "clean_mask": clean_mask,
        "grouped_mask": grouped_mask,
        "split_mask": split_mask,
    }
    return detections, diagnostics, artifacts


def detect_pallet_bricks(
    current: np.ndarray,
    background: np.ndarray,
) -> tuple[list[dict], dict]:
    """Return pallet-brick detections and JSON-compatible diagnostics."""
    detections, diagnostics, _ = run_pallet_pipeline(current, background)
    return detections, diagnostics


def draw_detection_preview(
    image: np.ndarray,
    detections: list[dict],
) -> np.ndarray:
    """Draw pallet detections and their spatial IDs."""
    preview = image.copy()
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
    return preview


def main() -> None:
    background = load_image(BACKGROUND_PATH)
    current = load_image(CURRENT_PATH)
    detections, diagnostics, artifacts = run_pallet_pipeline(
        current,
        background,
    )
    inventory = build_partial_inventory(
        image_id=CURRENT_PATH.stem,
        image_shape=current.shape,
        detections=detections,
        source_detector="pallet_background_difference_v0.2",
    )
    preview = draw_detection_preview(current, detections)

    DIFFERENCE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(
        str(ALIGNED_BACKGROUND_OUTPUT_PATH),
        artifacts["aligned_background"],
    ):
        raise OSError(
            f"Could not write image: {ALIGNED_BACKGROUND_OUTPUT_PATH}"
        )
    if not cv2.imwrite(str(DIFFERENCE_OUTPUT_PATH), artifacts["difference"]):
        raise OSError(f"Could not write image: {DIFFERENCE_OUTPUT_PATH}")
    if not cv2.imwrite(str(MASK_OUTPUT_PATH), artifacts["raw_mask"]):
        raise OSError(f"Could not write image: {MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(CLEAN_MASK_OUTPUT_PATH), artifacts["clean_mask"]):
        raise OSError(f"Could not write image: {CLEAN_MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(GROUPED_MASK_OUTPUT_PATH), artifacts["grouped_mask"]):
        raise OSError(f"Could not write image: {GROUPED_MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(SPLIT_MASK_OUTPUT_PATH), artifacts["split_mask"]):
        raise OSError(f"Could not write image: {SPLIT_MASK_OUTPUT_PATH}")
    if not cv2.imwrite(str(DETECTIONS_OUTPUT_PATH), preview):
        raise OSError(f"Could not write image: {DETECTIONS_OUTPUT_PATH}")
    save_inventory(inventory, INVENTORY_OUTPUT_PATH)

    print(f"Saved aligned background to: {ALIGNED_BACKGROUND_OUTPUT_PATH}")
    print(f"Saved difference image to: {DIFFERENCE_OUTPUT_PATH}")
    print(f"Saved raw mask to: {MASK_OUTPUT_PATH}")
    print(f"Saved clean mask to: {CLEAN_MASK_OUTPUT_PATH}")
    print(f"Saved grouped mask to: {GROUPED_MASK_OUTPUT_PATH}")
    print(f"Saved split mask to: {SPLIT_MASK_OUTPUT_PATH}")
    print(f"Saved detection preview to: {DETECTIONS_OUTPUT_PATH}")
    print(f"Saved partial inventory to: {INVENTORY_OUTPUT_PATH}")
    print(
        "Background resized to current image: "
        f"{diagnostics['background_was_resized']}"
    )
    print(f"Alignment ECC correlation: {diagnostics['alignment_correlation']}")
    print(f"Alignment affine matrix: {diagnostics['alignment_affine_matrix']}")
    print(
        "Grouped component labels: "
        f"{diagnostics['selected_component_labels']} "
        f"(anchor={diagnostics['anchor_component_label']})"
    )
    print(
        "Local foreground recoveries used: "
        f"{diagnostics['local_recovery_count']}"
    )
    print(f"Cell bbox fallbacks used: {diagnostics['bbox_fallback_count']}")
    print(
        "Previous-row geometry fallbacks used: "
        f"{diagnostics['previous_row_geometry_fallbacks']}"
    )
    print(
        "Gradient refinements used: "
        f"{diagnostics['gradient_refined_detection_count']} detections, "
        f"{diagnostics['gradient_refined_side_count']} sides"
    )
    print(
        "Stack top refinement: "
        f"{diagnostics['stack_top_original_y']} -> "
        f"{diagnostics['stack_top_refined_y']} "
        f"(applied={diagnostics['stack_top_refinement_applied']})"
    )
    print(
        "Envelope clamps used: "
        f"{diagnostics['envelope_clamped_detection_count']} detections, "
        f"{diagnostics['envelope_clamped_side_count']} sides"
    )
    print(f"Detected horizontal splits at y={diagnostics['horizontal_splits']}")
    print(f"Detected vertical splits at x={diagnostics['vertical_splits']}")
    print(
        "Geometry fallback splits at x="
        f"{diagnostics['geometry_fallback_splits']}"
    )
    if diagnostics["cell_occupancy"] is not None:
        occupancy = diagnostics["cell_occupancy"]
        print(
            "Cell occupancy: "
            f"min={occupancy['minimum']:.3f}, "
            f"mean={occupancy['mean']:.3f}, "
            f"max={occupancy['maximum']:.3f}"
        )
    print("Estimated row layout:")
    for row_index, row in enumerate(
        diagnostics["estimated_row_layout"],
        start=1,
    ):
        print(
            f"  Row {row_index}: orientation={row['orientation']}, "
            f"y={row['start_y']}:{row['end_y']}, "
            f"expected_bricks={row['expected_bricks']}, "
            f"score={row['score']:.3f}"
        )
    print(json.dumps(inventory, indent=2))


if __name__ == "__main__":
    main()

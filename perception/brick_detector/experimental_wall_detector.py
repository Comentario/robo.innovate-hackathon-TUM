import copy
import json
import warnings
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from perception.inventory_manager.inventory import (
    build_partial_inventory,
    save_inventory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIRECTORY = PROJECT_ROOT / "data" / "images" / "color_estimation"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_detector_integrated"
INVENTORY_OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "inventories" / "wall"

CLUSTER_COUNT = 5
MORPH_KERNEL_SIZE = (3, 3)
KMEANS_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    50,
    0.2,
)

MIN_AREA_RATIO = 0.001
MIN_WIDTH_RATIO = 0.025
MIN_HEIGHT_RATIO = 0.015
MIN_ASPECT_RATIO = 0.8
MAX_ASPECT_RATIO = 6.5
MIN_FILL_RATIO = 0.35
LARGE_SIZE_RATIO = 1.8
VISUAL_MIN_AREA_FACTOR = 0.1

MIN_SPLIT_SIZE_RATIO = 1.50
MIN_JOINT_COVERAGE = 0.60
MIN_EDGE_DISTANCE_RATIO = 0.25
MIN_JOINT_SPACING_RATIO = 0.50
JOINT_THICKNESS = 3

BAND_RADIUS = 2
MIN_NEAR_LINE_COVERAGE = 0.50
MIN_BAND_COVERAGE = 0.70

MIN_SECONDARY_COVERAGE_GAIN = 0.15
MIN_BORDER_SEGMENT_RATIO = 0.30
MIN_INTERIOR_SEGMENT_RATIO = 0.45
MAX_FRAGMENT_TO_ACCEPTED_RATIO = 0.50
MAX_UNRESOLVED_TO_ACCEPTED_RATIO = 0.25

MIN_SHORT_HEIGHT_RATIO = 0.75
MAX_SHORT_HEIGHT_RATIO = 1.25
MIN_SHORT_INTERIOR_WIDTH_RATIO = 0.35
MIN_SHORT_BORDER_WIDTH_RATIO = 0.20
MAX_SHORT_WIDTH_RATIO = 0.70
MIN_SHORT_FILL_RATIO = 0.70

GRID_ROWS = 4
GRID_COLUMNS = 4
NORMALIZATION_PERCENTILES = (10, 90)
SCORE_WEIGHTS = {
    "validity": 0.20,
    "spatial_coverage": 0.15,
    "size_consistency": 0.15,
    "fragmentation": 0.15,
    "fill": 0.10,
    "cluster_simplicity": 0.10,
    "detection_count": 0.05,
    "unresolved_merges": 0.05,
    "mortar_structure": 0.05,
}

STATUS_COLORS = {
    "accepted": (0, 255, 0),
    "possible_merge": (0, 255, 255),
    "size": (0, 0, 255),
    "aspect": (0, 165, 255),
    "fill": (255, 0, 255),
}


def load_image(image_path: Path) -> np.ndarray:
    """Load one wall image in OpenCV BGR format."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return image


def cluster_lab_image(
    image: np.ndarray,
    cluster_count: int = CLUSTER_COUNT,
) -> tuple[np.ndarray, np.ndarray]:
    """Cluster Lab pixels and order their centers from dark to light."""
    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    pixels = lab_image.reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(42)
    _, labels, centers = cv2.kmeans(
        pixels,
        cluster_count,
        None,
        KMEANS_CRITERIA,
        5,
        cv2.KMEANS_PP_CENTERS,
    )
    lightness_order = np.argsort(centers[:, 0])
    ordered_centers = centers[lightness_order]
    label_mapping = np.empty(cluster_count, dtype=np.int32)
    label_mapping[lightness_order] = np.arange(cluster_count)
    ordered_labels = label_mapping[labels.ravel()].reshape(image.shape[:2])
    return ordered_labels, ordered_centers


def build_masks(
    labels: np.ndarray,
    mortar_clusters: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """Build a connected mortar mask and its cleaned brick complement."""
    mortar_mask = np.where(
        np.isin(labels, mortar_clusters),
        255,
        0,
    ).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_KERNEL_SIZE)
    mortar_mask = cv2.morphologyEx(mortar_mask, cv2.MORPH_CLOSE, kernel)
    mortar_mask = cv2.dilate(mortar_mask, kernel, iterations=1)
    brick_mask = cv2.bitwise_not(mortar_mask)
    brick_mask = cv2.morphologyEx(brick_mask, cv2.MORPH_OPEN, kernel)
    return mortar_mask, brick_mask


def classify_components(mask: np.ndarray) -> tuple[list[dict], dict]:
    """Classify every connected component and preserve rejection reasons."""
    image_height, image_width = mask.shape
    minimum_area = image_height * image_width * MIN_AREA_RATIO
    minimum_width = image_width * MIN_WIDTH_RATIO
    minimum_height = image_height * MIN_HEIGHT_RATIO
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask,
        connectivity=8,
    )
    components = []
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        aspect_ratio = width / height
        fill_ratio = area / (width * height)
        reasons = []
        if area < minimum_area:
            reasons.append("area")
        if width < minimum_width:
            reasons.append("width")
        if height < minimum_height:
            reasons.append("height")
        if not MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO:
            reasons.append("aspect")
        if fill_ratio < MIN_FILL_RATIO:
            reasons.append("fill")
        components.append(
            {
                "label": int(label),
                "bbox_px": {
                    "x": int(x),
                    "y": int(y),
                    "width": int(width),
                    "height": int(height),
                },
                "area_px": int(area),
                "aspect_ratio": round(float(aspect_ratio), 3),
                "fill_ratio": round(float(fill_ratio), 3),
                "reasons": reasons,
            }
        )

    accepted = [item for item in components if not item["reasons"]]
    median_width = (
        float(np.median([item["bbox_px"]["width"] for item in accepted]))
        if accepted
        else 0.0
    )
    median_height = (
        float(np.median([item["bbox_px"]["height"] for item in accepted]))
        if accepted
        else 0.0
    )
    for item in accepted:
        bbox = item["bbox_px"]
        item["possible_merge"] = (
            median_width > 0
            and median_height > 0
            and (
                bbox["width"] > LARGE_SIZE_RATIO * median_width
                or bbox["height"] > LARGE_SIZE_RATIO * median_height
            )
        )
    thresholds = {
        "minimum_area": round(float(minimum_area), 2),
        "minimum_width": round(float(minimum_width), 2),
        "minimum_height": round(float(minimum_height), 2),
        "median_accepted_width": round(median_width, 2),
        "median_accepted_height": round(median_height, 2),
    }
    return components, {"labels": labels, "thresholds": thresholds}


def touches_image_border(bbox: dict, image_shape: tuple[int, ...]) -> bool:
    """Return whether a bounding box reaches an image boundary."""
    image_height, image_width = image_shape[:2]
    return (
        bbox["x"] <= 0
        or bbox["y"] <= 0
        or bbox["x"] + bbox["width"] >= image_width
        or bbox["y"] + bbox["height"] >= image_height
    )


def joint_profiles(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Measure exact-line and narrow-band mortar support."""
    x = bbox["x"]
    y = bbox["y"]
    width = bbox["width"]
    height = bbox["height"]
    local_mask = mortar_mask[y : y + height, x : x + width] > 0
    if orientation == "vertical":
        line_coverage = np.mean(local_mask, axis=0)
        band_coverage = np.array(
            [
                np.mean(
                    np.any(
                        local_mask[
                            :,
                            max(0, position - BAND_RADIUS) : position
                            + BAND_RADIUS
                            + 1,
                        ],
                        axis=1,
                    )
                )
                for position in range(width)
            ],
            dtype=np.float32,
        )
    else:
        line_coverage = np.mean(local_mask, axis=1)
        band_coverage = np.array(
            [
                np.mean(
                    np.any(
                        local_mask[
                            max(0, position - BAND_RADIUS) : position
                            + BAND_RADIUS
                            + 1,
                            :,
                        ],
                        axis=0,
                    )
                )
                for position in range(height)
            ],
            dtype=np.float32,
        )
    return line_coverage, band_coverage


def find_supported_joints(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
    nominal_size: float,
    allow_band_rescue: bool,
) -> list[dict]:
    """Find separated mortar-supported cuts inside one component."""
    line_coverage, band_coverage = joint_profiles(mortar_mask, bbox, orientation)
    supported = line_coverage >= MIN_JOINT_COVERAGE
    if allow_band_rescue:
        supported |= (
            (line_coverage >= MIN_NEAR_LINE_COVERAGE)
            & (band_coverage >= MIN_BAND_COVERAGE)
        )
    edge_distance = max(2, round(nominal_size * MIN_EDGE_DISTANCE_RATIO))
    valid_indices = np.flatnonzero(supported)
    valid_indices = valid_indices[
        (valid_indices >= edge_distance)
        & (valid_indices < len(line_coverage) - edge_distance)
    ]
    if len(valid_indices) == 0:
        return []
    groups = np.split(valid_indices, np.where(np.diff(valid_indices) > 1)[0] + 1)
    candidates = []
    for group in groups:
        best_position = int(group[np.argmax(line_coverage[group])])
        candidates.append(
            {
                "local_position": best_position,
                "line_coverage": float(line_coverage[best_position]),
                "band_coverage": float(band_coverage[best_position]),
                "band_rescue": bool(
                    line_coverage[best_position] < MIN_JOINT_COVERAGE
                ),
            }
        )
    minimum_spacing = max(2, round(nominal_size * MIN_JOINT_SPACING_RATIO))
    selected = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item["line_coverage"], item["band_coverage"]),
        reverse=True,
    ):
        if all(
            abs(candidate["local_position"] - other["local_position"])
            >= minimum_spacing
            for other in selected
        ):
            selected.append(candidate)
    origin = bbox["x"] if orientation == "vertical" else bbox["y"]
    for candidate in selected:
        candidate["cut_position"] = origin + candidate["local_position"]
    return sorted(selected, key=lambda item: item["cut_position"])


def complete_primary_orientation(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
    orientation: str,
    allow_band_rescue: bool,
) -> tuple[np.ndarray, list[dict]]:
    """Complete primary mortar joints for one orientation."""
    repaired_mask = brick_mask.copy()
    actions = []
    nominal_size = (
        thresholds["median_accepted_width"]
        if orientation == "vertical"
        else thresholds["median_accepted_height"]
    )
    if nominal_size <= 0:
        return repaired_mask, actions
    for component in components:
        reasons = set(component["reasons"])
        if reasons and reasons != {"aspect"}:
            continue
        bbox = component["bbox_px"]
        dimension = bbox["width"] if orientation == "vertical" else bbox["height"]
        if dimension < MIN_SPLIT_SIZE_RATIO * nominal_size:
            continue
        joints = find_supported_joints(
            mortar_mask,
            bbox,
            orientation,
            nominal_size,
            allow_band_rescue,
        )
        if not joints:
            actions.append(
                {
                    "bbox_px": bbox,
                    "orientation": orientation,
                    "status": "skipped_no_strong_joint",
                    "border_component": touches_image_border(bbox, image_shape),
                }
            )
            continue
        for joint in joints:
            cut_position = joint["cut_position"]
            if orientation == "vertical":
                start = (cut_position, bbox["y"])
                end = (cut_position, bbox["y"] + bbox["height"] - 1)
            else:
                start = (bbox["x"], cut_position)
                end = (bbox["x"] + bbox["width"] - 1, cut_position)
            cv2.line(repaired_mask, start, end, 0, JOINT_THICKNESS)
            actions.append(
                {
                    "bbox_px": bbox,
                    "orientation": orientation,
                    "status": "completed",
                    "cut_position": cut_position,
                    "line_coverage": round(joint["line_coverage"], 3),
                    "band_coverage": round(joint["band_coverage"], 3),
                    "band_rescue": joint["band_rescue"],
                    "border_component": touches_image_border(bbox, image_shape),
                }
            )
    return repaired_mask, actions


def complete_primary_joints(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    image_shape: tuple[int, ...],
    allow_band_rescue: bool = True,
) -> tuple[np.ndarray, list[dict]]:
    """Separate rows first, then recompute components before vertical cuts."""
    components, details = classify_components(brick_mask)
    horizontal_mask, horizontal_actions = complete_primary_orientation(
        brick_mask,
        mortar_mask,
        components,
        details["thresholds"],
        image_shape,
        "horizontal",
        allow_band_rescue,
    )
    components, details = classify_components(horizontal_mask)
    repaired_mask, vertical_actions = complete_primary_orientation(
        horizontal_mask,
        mortar_mask,
        components,
        details["thresholds"],
        image_shape,
        "vertical",
        allow_band_rescue,
    )
    return repaired_mask, horizontal_actions + vertical_actions


def cluster_combinations(cluster_count: int) -> list[tuple[int, ...]]:
    """Return every non-empty proper subset of the available clusters."""
    return [
        selection
        for size in range(1, cluster_count)
        for selection in combinations(range(cluster_count), size)
    ]


def median_and_mad_ratio(values: list[int]) -> tuple[float, float]:
    """Return a robust median and normalized median absolute deviation."""
    if not values:
        return 0.0, 1.0
    array = np.asarray(values, dtype=np.float32)
    median = float(np.median(array))
    if median <= 0:
        return median, 1.0
    return median, float(np.median(np.abs(array - median)) / median)


def spatial_coverage(
    components: list[dict],
    image_shape: tuple[int, ...],
) -> float:
    """Measure how widely accepted components cover the image."""
    image_height, image_width = image_shape[:2]
    occupied_cells = set()
    for component in components:
        bbox = component["bbox_px"]
        center_x = bbox["x"] + bbox["width"] / 2
        center_y = bbox["y"] + bbox["height"] / 2
        column = min(GRID_COLUMNS - 1, int(center_x * GRID_COLUMNS / image_width))
        row = min(GRID_ROWS - 1, int(center_y * GRID_ROWS / image_height))
        occupied_cells.add((row, column))
    return len(occupied_cells) / (GRID_ROWS * GRID_COLUMNS)


def mortar_structure_metrics(
    mortar_mask: np.ndarray,
    nominal_width: float,
    nominal_height: float,
) -> tuple[float, float]:
    """Measure line support and approximate mortar thickness."""
    mortar_pixels = int(np.count_nonzero(mortar_mask))
    if mortar_pixels == 0 or nominal_width <= 0 or nominal_height <= 0:
        return 0.0, 1.0
    horizontal_length = max(3, round(nominal_width * 0.5))
    vertical_length = max(3, round(nominal_height * 0.5))
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (horizontal_length, 1),
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, vertical_length),
    )
    horizontal_lines = cv2.morphologyEx(
        mortar_mask,
        cv2.MORPH_OPEN,
        horizontal_kernel,
    )
    vertical_lines = cv2.morphologyEx(
        mortar_mask,
        cv2.MORPH_OPEN,
        vertical_kernel,
    )
    supported_lines = cv2.bitwise_and(
        cv2.bitwise_or(horizontal_lines, vertical_lines),
        mortar_mask,
    )
    line_support_ratio = int(np.count_nonzero(supported_lines)) / mortar_pixels
    distance = cv2.distanceTransform(mortar_mask, cv2.DIST_L2, 3)
    positive_distance = distance[distance > 0]
    median_diameter = 2.0 * float(np.median(positive_distance))
    return line_support_ratio, median_diameter / nominal_height


def evaluate_mortar_candidate(
    image: np.ndarray,
    labels: np.ndarray,
    mortar_clusters: tuple[int, ...],
) -> dict:
    """Calculate selector metrics for one possible mortar cluster set."""
    mortar_mask, brick_mask = build_masks(labels, mortar_clusters)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        repaired_mask, repair_actions = complete_primary_joints(
            brick_mask,
            mortar_mask,
            image.shape,
            allow_band_rescue=False,
        )
        components, details = classify_components(repaired_mask)
    minimum_area = details["thresholds"]["minimum_area"]
    meaningful = [
        item
        for item in components
        if item["area_px"] >= minimum_area * VISUAL_MIN_AREA_FACTOR
    ]
    accepted = [item for item in meaningful if not item["reasons"]]
    accepted_interior = [
        item
        for item in accepted
        if not touches_image_border(item["bbox_px"], image.shape)
    ]
    widths = [item["bbox_px"]["width"] for item in accepted_interior]
    heights = [item["bbox_px"]["height"] for item in accepted_interior]
    nominal_width, width_mad_ratio = median_and_mad_ratio(widths)
    nominal_height, height_mad_ratio = median_and_mad_ratio(heights)
    meaningful_area = sum(item["area_px"] for item in meaningful)
    accepted_area = sum(item["area_px"] for item in accepted)
    valid_count_ratio = len(accepted) / len(meaningful) if meaningful else 0.0
    valid_area_ratio = accepted_area / meaningful_area if meaningful_area else 0.0
    fragments = [
        item
        for item in meaningful
        if item["reasons"]
        and any(reason in item["reasons"] for reason in ("area", "width", "height"))
    ]
    image_area = image.shape[0] * image.shape[1]
    fragment_area_ratio = sum(item["area_px"] for item in fragments) / image_area
    fragments_per_megapixel = len(fragments) / (image_area / 1_000_000)
    unresolved_large = []
    if nominal_width > 0 and nominal_height > 0:
        for item in meaningful:
            reasons = set(item["reasons"])
            if reasons and reasons != {"aspect"}:
                continue
            bbox = item["bbox_px"]
            if (
                bbox["width"] >= MIN_SPLIT_SIZE_RATIO * nominal_width
                or bbox["height"] >= MIN_SPLIT_SIZE_RATIO * nominal_height
            ):
                unresolved_large.append(item)
    completed_repairs = [
        action for action in repair_actions if action["status"] == "completed"
    ]
    mean_repair_coverage = (
        float(np.mean([item["line_coverage"] for item in completed_repairs]))
        if completed_repairs
        else 0.0
    )
    line_support, thickness_ratio = mortar_structure_metrics(
        mortar_mask,
        nominal_width,
        nominal_height,
    )
    return {
        "mortar_clusters": list(mortar_clusters),
        "cluster_key": "+".join(f"C{value}" for value in mortar_clusters),
        "accepted_count": len(accepted),
        "accepted_interior_count": len(accepted_interior),
        "meaningful_component_count": len(meaningful),
        "valid_count_ratio": round(valid_count_ratio, 4),
        "valid_area_ratio": round(valid_area_ratio, 4),
        "spatial_coverage": round(spatial_coverage(accepted, image.shape), 4),
        "nominal_width_px": round(nominal_width, 2),
        "nominal_height_px": round(nominal_height, 2),
        "width_mad_ratio": round(width_mad_ratio, 4),
        "height_mad_ratio": round(height_mad_ratio, 4),
        "median_fill_ratio": round(
            float(np.median([item["fill_ratio"] for item in accepted_interior]))
            if accepted_interior
            else 0.0,
            4,
        ),
        "fragment_count": len(fragments),
        "fragments_per_megapixel": round(fragments_per_megapixel, 3),
        "fragment_area_ratio": round(fragment_area_ratio, 5),
        "unresolved_large_count": len(unresolved_large),
        "mortar_area_ratio": round(
            float(np.count_nonzero(mortar_mask) / image_area),
            4,
        ),
        "mortar_line_support_ratio": round(line_support, 4),
        "mortar_thickness_ratio": round(thickness_ratio, 4),
        "completed_repair_count": len(completed_repairs),
        "mean_repair_coverage": round(mean_repair_coverage, 4),
    }


def robust_normalize(
    values: list[float],
    higher_is_better: bool,
) -> np.ndarray:
    """Normalize one image's candidate values using clipped percentiles."""
    array = np.asarray(values, dtype=np.float32)
    lower, upper = np.percentile(array, NORMALIZATION_PERCENTILES)
    if upper <= lower:
        normalized = np.full_like(array, 0.5)
    else:
        normalized = np.clip((array - lower) / (upper - lower), 0.0, 1.0)
    return normalized if higher_is_better else 1.0 - normalized


def score_mortar_candidates(candidates: list[dict]) -> None:
    """Normalize candidate metrics and apply the validated provisional weights."""
    metric_directions = {
        "valid_area_ratio": True,
        "valid_count_ratio": True,
        "spatial_coverage": True,
        "accepted_count": True,
        "width_mad_ratio": False,
        "height_mad_ratio": False,
        "median_fill_ratio": True,
        "fragments_per_megapixel": False,
        "fragment_area_ratio": False,
        "unresolved_large_count": False,
        "mortar_line_support_ratio": True,
        "mortar_thickness_ratio": False,
    }
    normalized = {
        metric: robust_normalize(
            [float(item[metric]) for item in candidates],
            higher_is_better,
        )
        for metric, higher_is_better in metric_directions.items()
    }
    for index, item in enumerate(candidates):
        component_scores = {
            "validity": float(
                0.5
                * (
                    normalized["valid_area_ratio"][index]
                    + normalized["valid_count_ratio"][index]
                )
            ),
            "spatial_coverage": float(normalized["spatial_coverage"][index]),
            "size_consistency": float(
                0.5
                * (
                    normalized["width_mad_ratio"][index]
                    + normalized["height_mad_ratio"][index]
                )
            ),
            "fragmentation": float(
                0.5
                * (
                    normalized["fragments_per_megapixel"][index]
                    + normalized["fragment_area_ratio"][index]
                )
            ),
            "fill": float(normalized["median_fill_ratio"][index]),
            "cluster_simplicity": 1.0
            - (len(item["mortar_clusters"]) - 1) / (CLUSTER_COUNT - 2),
            "detection_count": float(normalized["accepted_count"][index]),
            "unresolved_merges": float(
                normalized["unresolved_large_count"][index]
            ),
            "mortar_structure": float(
                0.5
                * (
                    normalized["mortar_line_support_ratio"][index]
                    + normalized["mortar_thickness_ratio"][index]
                )
            ),
        }
        for name, value in component_scores.items():
            item[f"score_{name}"] = round(value, 4)
        item["selection_score"] = round(
            sum(
                SCORE_WEIGHTS[name] * value
                for name, value in component_scores.items()
            ),
            4,
        )
    ranked = sorted(
        candidates,
        key=lambda item: (
            -item["selection_score"],
            len(item["mortar_clusters"]),
            item["cluster_key"],
        ),
    )
    for rank, item in enumerate(ranked, start=1):
        item["selection_rank"] = rank
        item["is_selected"] = rank == 1


def select_mortar_clusters(
    image: np.ndarray,
    labels: np.ndarray,
) -> tuple[dict, list[dict]]:
    """Evaluate all Lab-cluster combinations and select the best mortar set."""
    candidates = [
        evaluate_mortar_candidate(image, labels, mortar_clusters)
        for mortar_clusters in cluster_combinations(CLUSTER_COUNT)
    ]
    score_mortar_candidates(candidates)
    return next(item for item in candidates if item["is_selected"]), candidates


def secondary_recovery_allowed(selection: dict) -> tuple[bool, dict]:
    """Reject secondary recovery when the primary selection is unstable."""
    accepted_count = max(1, selection["accepted_count"])
    fragment_ratio = selection["fragment_count"] / accepted_count
    unresolved_ratio = selection["unresolved_large_count"] / accepted_count
    allowed = (
        fragment_ratio <= MAX_FRAGMENT_TO_ACCEPTED_RATIO
        and unresolved_ratio <= MAX_UNRESOLVED_TO_ACCEPTED_RATIO
    )
    return allowed, {
        "fragment_to_accepted_ratio": round(fragment_ratio, 3),
        "unresolved_to_accepted_ratio": round(unresolved_ratio, 3),
        "maximum_fragment_ratio": MAX_FRAGMENT_TO_ACCEPTED_RATIO,
        "maximum_unresolved_ratio": MAX_UNRESOLVED_TO_ACCEPTED_RATIO,
    }


def choose_secondary_cluster(
    centers: np.ndarray,
    selected_clusters: tuple[int, ...],
) -> int:
    """Choose the nearest unselected Lab center to the selected mortar."""
    candidates = [
        index for index in range(len(centers)) if index not in selected_clusters
    ]
    return min(
        candidates,
        key=lambda candidate: min(
            np.linalg.norm(centers[candidate] - centers[selected])
            for selected in selected_clusters
        ),
    )


def line_coverage(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
    position: int,
) -> float:
    """Measure mortar support along one proposed cut."""
    x = bbox["x"]
    y = bbox["y"]
    width = bbox["width"]
    height = bbox["height"]
    line = (
        mortar_mask[y : y + height, position]
        if orientation == "vertical"
        else mortar_mask[position, x : x + width]
    )
    return float(np.mean(line > 0))


def complete_secondary_orientation(
    brick_mask: np.ndarray,
    primary_mortar: np.ndarray,
    combined_mortar: np.ndarray,
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
    orientation: str,
) -> tuple[np.ndarray, list[dict]]:
    """Use an adjacent Lab cluster only inside unresolved components."""
    repaired_mask = brick_mask.copy()
    actions = []
    nominal_size = (
        thresholds["median_accepted_width"]
        if orientation == "vertical"
        else thresholds["median_accepted_height"]
    )
    if nominal_size <= 0:
        return repaired_mask, actions
    for component in components:
        reasons = set(component["reasons"])
        if not (component.get("possible_merge", False) or reasons == {"aspect"}):
            continue
        bbox = component["bbox_px"]
        dimension = bbox["width"] if orientation == "vertical" else bbox["height"]
        if dimension < MIN_SPLIT_SIZE_RATIO * nominal_size:
            continue
        is_border = touches_image_border(bbox, image_shape)
        minimum_segment = nominal_size * (
            MIN_BORDER_SEGMENT_RATIO if is_border else MIN_INTERIOR_SEGMENT_RATIO
        )
        axis_origin = bbox["x"] if orientation == "vertical" else bbox["y"]
        axis_end = axis_origin + dimension
        joints = find_supported_joints(
            combined_mortar,
            bbox,
            orientation,
            nominal_size,
            allow_band_rescue=False,
        )
        for joint in joints:
            cut_position = joint["cut_position"]
            if (
                cut_position - axis_origin < minimum_segment
                or axis_end - cut_position < minimum_segment
            ):
                continue
            primary_coverage = line_coverage(
                primary_mortar,
                bbox,
                orientation,
                cut_position,
            )
            coverage_gain = joint["line_coverage"] - primary_coverage
            if coverage_gain < MIN_SECONDARY_COVERAGE_GAIN:
                continue
            if orientation == "vertical":
                start = (cut_position, bbox["y"])
                end = (cut_position, bbox["y"] + bbox["height"] - 1)
            else:
                start = (bbox["x"], cut_position)
                end = (bbox["x"] + bbox["width"] - 1, cut_position)
            cv2.line(repaired_mask, start, end, 0, JOINT_THICKNESS)
            actions.append(
                {
                    "bbox_px": bbox,
                    "orientation": orientation,
                    "cut_position": cut_position,
                    "primary_coverage": round(primary_coverage, 3),
                    "combined_coverage": round(joint["line_coverage"], 3),
                    "secondary_gain": round(coverage_gain, 3),
                    "border_component": is_border,
                    "minimum_segment_size": round(minimum_segment, 2),
                }
            )
    return repaired_mask, actions


def complete_secondary_joints(
    brick_mask: np.ndarray,
    primary_mortar: np.ndarray,
    combined_mortar: np.ndarray,
    image_shape: tuple[int, ...],
) -> tuple[np.ndarray, list[dict]]:
    """Apply secondary evidence horizontally and then vertically."""
    components, details = classify_components(brick_mask)
    horizontal_mask, horizontal_actions = complete_secondary_orientation(
        brick_mask,
        primary_mortar,
        combined_mortar,
        components,
        details["thresholds"],
        image_shape,
        "horizontal",
    )
    components, details = classify_components(horizontal_mask)
    repaired_mask, vertical_actions = complete_secondary_orientation(
        horizontal_mask,
        primary_mortar,
        combined_mortar,
        components,
        details["thresholds"],
        image_shape,
        "vertical",
    )
    return repaired_mask, horizontal_actions + vertical_actions


def recover_short_components(
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
) -> tuple[list[dict], list[dict]]:
    """Recover compact half bricks rejected only by aspect ratio."""
    reviewed_components = copy.deepcopy(components)
    recovered = []
    nominal_width = thresholds["median_accepted_width"]
    nominal_height = thresholds["median_accepted_height"]
    if nominal_width <= 0 or nominal_height <= 0:
        return reviewed_components, recovered
    for component in reviewed_components:
        if set(component["reasons"]) != {"aspect"}:
            continue
        bbox = component["bbox_px"]
        is_partial = touches_image_border(bbox, image_shape)
        width_ratio = bbox["width"] / nominal_width
        height_ratio = bbox["height"] / nominal_height
        minimum_width_ratio = (
            MIN_SHORT_BORDER_WIDTH_RATIO
            if is_partial
            else MIN_SHORT_INTERIOR_WIDTH_RATIO
        )
        if not minimum_width_ratio <= width_ratio <= MAX_SHORT_WIDTH_RATIO:
            continue
        if not MIN_SHORT_HEIGHT_RATIO <= height_ratio <= MAX_SHORT_HEIGHT_RATIO:
            continue
        if component["fill_ratio"] < MIN_SHORT_FILL_RATIO:
            continue
        component["reasons"] = []
        component["recovered_short_brick"] = True
        component["is_partial"] = is_partial
        component["eligible_for_color"] = not is_partial
        recovered.append(
            {
                "bbox_px": bbox,
                "width_ratio": round(width_ratio, 3),
                "height_ratio": round(height_ratio, 3),
                "fill_ratio": component["fill_ratio"],
                "is_partial": is_partial,
                "eligible_for_color": not is_partial,
            }
        )
    return reviewed_components, recovered


def assign_spatial_ids(components: list[dict]) -> list[dict]:
    """Order detections by visual rows and then from left to right."""
    accepted = [item for item in components if not item["reasons"]]
    if not accepted:
        return []

    nominal_height = float(
        np.median([item["bbox_px"]["height"] for item in accepted])
    )
    row_tolerance = max(2.0, nominal_height * 0.50)
    rows = []
    for component in sorted(
        accepted,
        key=lambda item: (
            item["bbox_px"]["y"] + item["bbox_px"]["height"] / 2,
            item["bbox_px"]["x"],
        ),
    ):
        bbox = component["bbox_px"]
        center_y = bbox["y"] + bbox["height"] / 2
        matching_row = min(
            rows,
            key=lambda row: abs(center_y - row["center_y"]),
            default=None,
        )
        if (
            matching_row is None
            or abs(center_y - matching_row["center_y"]) > row_tolerance
        ):
            rows.append({"center_y": center_y, "components": [component]})
        else:
            matching_row["components"].append(component)
            matching_row["center_y"] = float(
                np.median(
                    [
                        item["bbox_px"]["y"]
                        + item["bbox_px"]["height"] / 2
                        for item in matching_row["components"]
                    ]
                )
            )

    accepted = []
    for row in sorted(rows, key=lambda item: item["center_y"]):
        accepted.extend(
            sorted(row["components"], key=lambda item: item["bbox_px"]["x"])
        )
    detections = []
    for index, component in enumerate(accepted, start=1):
        is_partial = component.get("is_partial", False)
        possible_merge = component.get("possible_merge", False)
        detections.append(
            {
                "id": f"brick_{index:03d}",
                "bbox_px": component["bbox_px"],
                "area_px": component["area_px"],
                "fill_ratio": component["fill_ratio"],
                "is_partial": is_partial,
                "possible_merge": possible_merge,
                "recovered_short_brick": component.get(
                    "recovered_short_brick",
                    False,
                ),
                "eligible_for_color": not is_partial and not possible_merge,
            }
        )
    return detections


def run_wall_pipeline(
    image: np.ndarray,
) -> tuple[list[dict], dict, dict[str, np.ndarray], list[dict]]:
    """Run the integrated wall detector entirely in memory."""
    labels, centers = cluster_lab_image(image)
    selection, _ = select_mortar_clusters(image, labels)
    selected_clusters = tuple(selection["mortar_clusters"])
    secondary_cluster = choose_secondary_cluster(centers, selected_clusters)
    primary_mortar, brick_mask = build_masks(labels, selected_clusters)
    primary_mask, primary_actions = complete_primary_joints(
        brick_mask,
        primary_mortar,
        image.shape,
        allow_band_rescue=True,
    )
    recovery_allowed, quality_gate = secondary_recovery_allowed(selection)
    combined_clusters = tuple(sorted((*selected_clusters, secondary_cluster)))
    combined_mortar, _ = build_masks(labels, combined_clusters)
    if recovery_allowed:
        final_mask, secondary_actions = complete_secondary_joints(
            primary_mask,
            primary_mortar,
            combined_mortar,
            image.shape,
        )
    else:
        final_mask = primary_mask
        secondary_actions = []
    components, details = classify_components(final_mask)
    final_components, recovered_short = recover_short_components(
        components,
        details["thresholds"],
        image.shape,
    )
    for component in final_components:
        if not component["reasons"]:
            component["is_partial"] = touches_image_border(
                component["bbox_px"],
                image.shape,
            )
    detections = assign_spatial_ids(final_components)
    diagnostics = {
        "selected_clusters": list(selected_clusters),
        "selection_score": selection["selection_score"],
        "secondary_cluster": secondary_cluster,
        "quality_gate_passed": recovery_allowed,
        "quality_gate": quality_gate,
        "primary_repair_count": sum(
            action["status"] == "completed" for action in primary_actions
        ),
        "band_repair_count": sum(
            action.get("band_rescue", False) for action in primary_actions
        ),
        "secondary_repair_count": len(secondary_actions),
        "short_recovery_count": len(recovered_short),
        "detection_count": len(detections),
        "partial_count": sum(item["is_partial"] for item in detections),
        "color_eligible_count": sum(
            item["eligible_for_color"] for item in detections
        ),
        "possible_merge_count": sum(
            item["possible_merge"] for item in detections
        ),
        "thresholds": details["thresholds"],
        "primary_actions": primary_actions,
        "secondary_actions": secondary_actions,
        "recovered_short_components": recovered_short,
    }
    masks = {
        "primary_mortar": primary_mortar,
        "initial_bricks": brick_mask,
        "primary_repaired": primary_mask,
        "final_bricks": final_mask,
    }
    return detections, diagnostics, masks, final_components


def detect_wall_bricks(image: np.ndarray) -> tuple[list[dict], dict]:
    """Return wall-brick detections and JSON-compatible diagnostics."""
    detections, diagnostics, _, _ = run_wall_pipeline(image)
    return detections, diagnostics


def component_status(component: dict) -> str:
    """Reduce rejection details to one preview category."""
    if not component["reasons"]:
        return "possible_merge" if component.get("possible_merge", False) else "accepted"
    if any(reason in component["reasons"] for reason in ("area", "width", "height")):
        return "size"
    if "aspect" in component["reasons"]:
        return "aspect"
    return "fill"


def draw_diagnostics(
    image: np.ndarray,
    components: list[dict],
    minimum_area: float,
) -> np.ndarray:
    """Draw accepted, merged, and rejected component boxes."""
    preview = image.copy()
    visual_minimum_area = minimum_area * VISUAL_MIN_AREA_FACTOR
    for component in components:
        if component["area_px"] < visual_minimum_area:
            continue
        bbox = component["bbox_px"]
        color = STATUS_COLORS[component_status(component)]
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
            color,
            2,
        )
    return preview


def draw_detections(image: np.ndarray, detections: list[dict]) -> np.ndarray:
    """Draw final bounding boxes and spatial IDs."""
    preview = image.copy()
    font_scale = max(0.35, image.shape[1] / 2400)
    for detection in detections:
        bbox = detection["bbox_px"]
        color = (0, 255, 255) if detection["possible_merge"] else (0, 255, 0)
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
            color,
            2,
        )
        cv2.putText(
            preview,
            detection["id"].split("_")[-1],
            (bbox["x"] + 2, bbox["y"] + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return preview


def detect_brick_components(mask: np.ndarray) -> list[dict]:
    """Return accepted connected components from an existing brick mask."""
    components, _ = classify_components(mask)
    return assign_spatial_ids(components)


def process_image(image_path: Path) -> dict:
    """Run the integrated detector and save reproducible diagnostics."""
    image = load_image(image_path)
    detections, diagnostics, masks, components = run_wall_pipeline(image)
    preview = draw_detections(image, detections)
    diagnostic_preview = draw_diagnostics(
        image,
        components,
        diagnostics["thresholds"]["minimum_area"],
    )
    inventory = build_partial_inventory(
        image_id=image_path.stem,
        image_shape=image.shape,
        detections=detections,
        source_detector="wall_lab_kmeans_v0.1",
    )
    scene_directory = OUTPUT_DIRECTORY / image_path.stem
    scene_directory.mkdir(parents=True, exist_ok=True)
    for name, mask in masks.items():
        cv2.imwrite(str(scene_directory / f"{name}.png"), mask)
    cv2.imwrite(str(scene_directory / "detections_preview.png"), preview)
    cv2.imwrite(str(scene_directory / "diagnostics_preview.png"), diagnostic_preview)
    (scene_directory / "detections.json").write_text(
        json.dumps(detections, indent=2) + "\n",
        encoding="utf-8",
    )
    (scene_directory / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2) + "\n",
        encoding="utf-8",
    )
    inventory_path = INVENTORY_OUTPUT_DIRECTORY / f"{image_path.stem}.partial.json"
    save_inventory(inventory, inventory_path)
    return {
        "image": image_path.name,
        **diagnostics,
        "output_directory": str(scene_directory),
        "inventory_path": str(inventory_path),
    }


def main() -> None:
    image_paths = sorted(IMAGE_DIRECTORY.glob("*.jpg"))
    if not image_paths:
        raise FileNotFoundError(f"No JPG images found in: {IMAGE_DIRECTORY}")
    print("Image                                  mortar  score   boxes  merges  band")
    for image_path in image_paths:
        result = process_image(image_path)
        clusters = "+".join(f"C{i}" for i in result["selected_clusters"])
        print(
            f'{result["image"]:<38} '
            f"{clusters:<7} "
            f'{result["selection_score"]:>5.3f} '
            f'{result["detection_count"]:>7} '
            f'{result["possible_merge_count"]:>7} '
            f'{result["band_repair_count"]:>5}'
        )
    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

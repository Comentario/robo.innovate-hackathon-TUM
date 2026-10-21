import csv
import json
import sys
import warnings
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diagnose_wall_components import (
    VISUAL_MIN_AREA_FACTOR,
    classify_components,
    draw_diagnostics,
)
from validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    IMAGE_DIRECTORY,
    cluster_lab_image,
    load_image,
)
from validate_wall_local_joint_completion import (
    MIN_SPLIT_SIZE_RATIO,
    complete_local_joints,
    touches_image_border,
)
from validate_wall_mortar_clusters import build_masks


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_cluster_selection_metrics"
DESIGN_SCENE_NAMES = (
    "wall_exposure_dark",
    "wall_mixed_colors",
    "wall_stylized",
    "wall_textured",
)
VALIDATION_SCENE_NAMES = (
    "validation_dark_uneven",
    "validation_gray_dark_mortar",
    "validation_irregular_old_wall",
    "validation_low_contrast_perspective",
    "validation_rough_texture",
)
SCENE_NAMES = DESIGN_SCENE_NAMES + VALIDATION_SCENE_NAMES
MANUAL_REFERENCES = {
    "wall_exposure_dark": (3, 4),
    "wall_mixed_colors": (4,),
    "wall_stylized": (0,),
    "wall_textured": (4,),
}
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


def cluster_combinations(cluster_count: int) -> list[tuple[int, ...]]:
    """Return every non-empty proper subset of the available clusters."""
    return [
        selection
        for size in range(1, cluster_count)
        for selection in combinations(range(cluster_count), size)
    ]


def median_and_mad_ratio(values: list[int]) -> tuple[float, float]:
    """Return a robust median and its normalized absolute deviation."""
    if not values:
        return 0.0, 1.0
    array = np.asarray(values, dtype=np.float32)
    median = float(np.median(array))
    if median <= 0:
        return median, 1.0
    mad_ratio = float(np.median(np.abs(array - median)) / median)
    return median, mad_ratio


def spatial_coverage(
    components: list[dict],
    image_shape: tuple[int, ...],
) -> float:
    """Measure how widely accepted detections are distributed over the wall."""
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
    """Measure line support and approximate thickness of the mortar network."""
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
    line_pixels = int(np.count_nonzero(supported_lines))
    line_support_ratio = line_pixels / mortar_pixels

    distance = cv2.distanceTransform(mortar_mask, cv2.DIST_L2, 3)
    positive_distance = distance[distance > 0]
    median_diameter = 2.0 * float(np.median(positive_distance))
    thickness_ratio = median_diameter / nominal_height
    return line_support_ratio, thickness_ratio


def evaluate_candidate(
    scene_name: str,
    image: np.ndarray,
    labels: np.ndarray,
    mortar_clusters: tuple[int, ...],
) -> dict:
    """Calculate independent diagnostic metrics for one mortar candidate."""
    mortar_mask, brick_mask = build_masks(labels, mortar_clusters)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        before_components, before_details = classify_components(brick_mask)
    thresholds = before_details["thresholds"]
    nominal_values = (
        thresholds["median_accepted_width"],
        thresholds["median_accepted_height"],
    )

    if all(np.isfinite(value) and value > 0 for value in nominal_values):
        repaired_mask, repair_actions = complete_local_joints(
            brick_mask,
            mortar_mask,
            before_components,
            thresholds,
            image.shape,
        )
    else:
        repaired_mask = brick_mask
        repair_actions = []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        components, details = classify_components(repaired_mask)
    minimum_area = details["thresholds"]["minimum_area"]
    visual_minimum_area = minimum_area * VISUAL_MIN_AREA_FACTOR
    meaningful = [
        item for item in components if item["area_px"] >= visual_minimum_area
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
        and any(
            reason in item["reasons"]
            for reason in ("area", "width", "height")
        )
    ]
    image_area = image.shape[0] * image.shape[1]
    fragment_area_ratio = (
        sum(item["area_px"] for item in fragments) / image_area
    )
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
        action
        for action in repair_actions
        if action["status"] == "completed"
    ]
    mean_repair_coverage = (
        float(np.mean([item["coverage"] for item in completed_repairs]))
        if completed_repairs
        else 0.0
    )
    line_support_ratio, mortar_thickness_ratio = mortar_structure_metrics(
        mortar_mask,
        nominal_width,
        nominal_height,
    )

    return {
        "scene": scene_name,
        "evaluation_split": (
            "weight_design"
            if scene_name in DESIGN_SCENE_NAMES
            else "held_out_validation"
        ),
        "mortar_clusters": list(mortar_clusters),
        "cluster_key": "+".join(f"C{value}" for value in mortar_clusters),
        "is_manual_reference": (
            scene_name in MANUAL_REFERENCES
            and mortar_clusters == MANUAL_REFERENCES[scene_name]
        ),
        "before_component_count": len(before_components),
        "after_component_count": len(components),
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
        "mortar_line_support_ratio": round(line_support_ratio, 4),
        "mortar_thickness_ratio": round(mortar_thickness_ratio, 4),
        "completed_repair_count": len(completed_repairs),
        "mean_repair_coverage": round(mean_repair_coverage, 4),
        "component_gain_after_repair": len(components) - len(before_components),
    }


def robust_normalize(
    values: list[float],
    higher_is_better: bool,
) -> np.ndarray:
    """Scale one scene's candidate values to 0-1 using clipped percentiles."""
    array = np.asarray(values, dtype=np.float32)
    lower, upper = np.percentile(array, NORMALIZATION_PERCENTILES)
    if upper <= lower:
        normalized = np.full_like(array, 0.5)
    else:
        normalized = np.clip((array - lower) / (upper - lower), 0.0, 1.0)
    return normalized if higher_is_better else 1.0 - normalized


def score_scene_candidates(scene_results: list[dict]) -> None:
    """Normalize one scene and add provisional component and total scores."""
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
            [float(item[metric]) for item in scene_results],
            higher_is_better,
        )
        for metric, higher_is_better in metric_directions.items()
    }

    for index, item in enumerate(scene_results):
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
        scene_results,
        key=lambda item: (
            -item["selection_score"],
            len(item["mortar_clusters"]),
            item["cluster_key"],
        ),
    )
    for rank, item in enumerate(ranked, start=1):
        item["selection_rank"] = rank
        item["is_selected"] = rank == 1


def score_all_candidates(results: list[dict]) -> None:
    """Apply scene-relative normalization and scoring to every candidate."""
    for scene_name in SCENE_NAMES:
        scene_results = [
            item for item in results if item["scene"] == scene_name
        ]
        score_scene_candidates(scene_results)


def write_reports(results: list[dict]) -> None:
    """Save the candidate table in machine-readable and spreadsheet formats."""
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIRECTORY / "candidate_metrics.json").write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUTPUT_DIRECTORY / "candidate_metrics.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    ranking_report = {
        "normalization_percentiles": list(NORMALIZATION_PERCENTILES),
        "score_weights": SCORE_WEIGHTS,
        "scenes": [],
    }
    for scene_name in SCENE_NAMES:
        scene_results = sorted(
            (item for item in results if item["scene"] == scene_name),
            key=lambda item: item["selection_rank"],
        )
        manual_reference = next(
            (
                item
                for item in scene_results
                if item["is_manual_reference"]
            ),
            None,
        )
        ranking_report["scenes"].append(
            {
                "scene": scene_name,
                "evaluation_split": scene_results[0]["evaluation_split"],
                "selected_clusters": scene_results[0]["mortar_clusters"],
                "selected_cluster_key": scene_results[0]["cluster_key"],
                "selected_score": scene_results[0]["selection_score"],
                "manual_reference_key": (
                    manual_reference["cluster_key"]
                    if manual_reference is not None
                    else None
                ),
                "manual_reference_rank": (
                    manual_reference["selection_rank"]
                    if manual_reference is not None
                    else None
                ),
                "top_five": [
                    {
                        "rank": item["selection_rank"],
                        "cluster_key": item["cluster_key"],
                        "score": item["selection_score"],
                    }
                    for item in scene_results[:5]
                ],
            }
        )
    (OUTPUT_DIRECTORY / "selection_ranking.json").write_text(
        json.dumps(ranking_report, indent=2) + "\n",
        encoding="utf-8",
    )


def save_selected_outputs(
    results: list[dict],
    scene_data: dict[str, tuple[np.ndarray, np.ndarray]],
) -> None:
    """Save masks and component previews for each automatically selected candidate."""
    selected_root = OUTPUT_DIRECTORY / "selected"
    for scene_name in SCENE_NAMES:
        selected = next(
            item
            for item in results
            if item["scene"] == scene_name and item["is_selected"]
        )
        image, labels = scene_data[scene_name]
        mortar_clusters = tuple(selected["mortar_clusters"])
        mortar_mask, brick_mask = build_masks(labels, mortar_clusters)
        before_components, before_details = classify_components(brick_mask)
        thresholds = before_details["thresholds"]
        nominal_values = (
            thresholds["median_accepted_width"],
            thresholds["median_accepted_height"],
        )
        if all(np.isfinite(value) and value > 0 for value in nominal_values):
            repaired_mask, _ = complete_local_joints(
                brick_mask,
                mortar_mask,
                before_components,
                thresholds,
                image.shape,
            )
        else:
            repaired_mask = brick_mask

        components, details = classify_components(repaired_mask)
        preview = draw_diagnostics(
            image,
            components,
            details["thresholds"]["minimum_area"],
        )
        scene_directory = selected_root / scene_name
        scene_directory.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(scene_directory / "selected_mortar_mask.png"), mortar_mask)
        cv2.imwrite(str(scene_directory / "selected_brick_mask.png"), repaired_mask)
        cv2.imwrite(str(scene_directory / "selected_preview.png"), preview)
        (scene_directory / "selection.json").write_text(
            json.dumps(selected, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    results = []
    scene_data = {}
    candidates = cluster_combinations(CLUSTER_COUNT)
    for scene_name in SCENE_NAMES:
        image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
        labels, _ = cluster_lab_image(image, CLUSTER_COUNT)
        scene_data[scene_name] = (image, labels)
        for mortar_clusters in candidates:
            results.append(
                evaluate_candidate(
                    scene_name,
                    image,
                    labels,
                    mortar_clusters,
                )
            )

    score_all_candidates(results)
    write_reports(results)
    save_selected_outputs(results, scene_data)
    print("Provisional automatic mortar selection:")
    print(
        "Scene                                split       selected   score   "
        "reference   ref.rank"
    )
    for scene_name in SCENE_NAMES:
        scene_results = [item for item in results if item["scene"] == scene_name]
        selected = next(item for item in scene_results if item["is_selected"])
        reference = next(
            (
                item
                for item in scene_results
                if item["is_manual_reference"]
            ),
            None,
        )
        reference_key = reference["cluster_key"] if reference else "-"
        reference_rank = str(reference["selection_rank"]) if reference else "-"
        print(
            f"{scene_name:<36} "
            f'{selected["evaluation_split"]:<11} '
            f'{selected["cluster_key"]:<10} '
            f'{selected["selection_score"]:>6.3f} '
            f'{reference_key:<11} '
            f'{reference_rank:>8}'
        )
    print(f"\nCandidates evaluated: {len(results)}")
    print(f"Outputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

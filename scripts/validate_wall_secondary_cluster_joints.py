import json
import sys
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diagnose_wall_components import classify_components, draw_diagnostics
from validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    IMAGE_DIRECTORY,
    cluster_lab_image,
    load_image,
)
from validate_wall_local_joint_completion import (
    JOINT_THICKNESS,
    MIN_JOINT_COVERAGE,
    MIN_SPLIT_SIZE_RATIO,
    complete_local_joints,
    find_supported_joints,
    touches_image_border,
)
from validate_wall_mortar_clusters import build_masks


SELECTION_DIRECTORY = (
    PROJECT_ROOT / "outputs" / "wall_cluster_selection_metrics" / "selected"
)
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_secondary_cluster_joints"
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
MIN_SECONDARY_COVERAGE_GAIN = 0.15
MIN_BORDER_SEGMENT_RATIO = 0.30
MIN_INTERIOR_SEGMENT_RATIO = 0.45
MAX_FRAGMENT_TO_ACCEPTED_RATIO = 0.50
MAX_UNRESOLVED_TO_ACCEPTED_RATIO = 0.25


def load_selection(scene_name: str) -> dict:
    """Read the frozen automatic selection and its quality metrics."""
    selection_path = SELECTION_DIRECTORY / scene_name / "selection.json"
    return json.loads(selection_path.read_text(encoding="utf-8"))


def secondary_recovery_allowed(selection: dict) -> tuple[bool, dict]:
    """Reject secondary recovery when the primary mask is globally unstable."""
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
    """Choose the unselected Lab center nearest to the selected mortar centers."""
    candidates = [
        index
        for index in range(len(centers))
        if index not in selected_clusters
    ]
    return min(
        candidates,
        key=lambda candidate: min(
            np.linalg.norm(centers[candidate] - centers[selected])
            for selected in selected_clusters
        ),
    )


def is_unresolved_merge(component: dict) -> bool:
    """Return whether a component is a known or aspect-rejected merge."""
    reasons = set(component["reasons"])
    return component.get("possible_merge", False) or reasons == {"aspect"}


def line_coverage(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
    position: int,
) -> float:
    """Measure mortar support along one proposed local cut."""
    x = bbox["x"]
    y = bbox["y"]
    width = bbox["width"]
    height = bbox["height"]
    if orientation == "vertical":
        line = mortar_mask[y : y + height, position]
    else:
        line = mortar_mask[position, x : x + width]
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
    """Complete joints supported locally by an adjacent secondary cluster."""
    repaired_mask = brick_mask.copy()
    actions = []
    nominal_size = (
        thresholds["median_accepted_width"]
        if orientation == "vertical"
        else thresholds["median_accepted_height"]
    )

    for component in components:
        if not is_unresolved_merge(component):
            continue
        bbox = component["bbox_px"]
        dimension = bbox["width"] if orientation == "vertical" else bbox["height"]
        if dimension < MIN_SPLIT_SIZE_RATIO * nominal_size:
            continue

        is_border_component = touches_image_border(bbox, image_shape)
        minimum_segment_size = nominal_size * (
            MIN_BORDER_SEGMENT_RATIO
            if is_border_component
            else MIN_INTERIOR_SEGMENT_RATIO
        )
        axis_origin = bbox["x"] if orientation == "vertical" else bbox["y"]
        axis_end = axis_origin + dimension
        for cut_position, combined_coverage in find_supported_joints(
            combined_mortar,
            bbox,
            orientation,
            nominal_size,
        ):
            if (
                cut_position - axis_origin < minimum_segment_size
                or axis_end - cut_position < minimum_segment_size
            ):
                continue
            primary_coverage = line_coverage(
                primary_mortar,
                bbox,
                orientation,
                cut_position,
            )
            coverage_gain = combined_coverage - primary_coverage
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
                    "combined_coverage": round(combined_coverage, 3),
                    "secondary_gain": round(coverage_gain, 3),
                    "border_component": is_border_component,
                    "minimum_segment_size": round(minimum_segment_size, 2),
                }
            )

    return repaired_mask, actions


def complete_secondary_joints(
    brick_mask: np.ndarray,
    primary_mortar: np.ndarray,
    combined_mortar: np.ndarray,
    image_shape: tuple[int, ...],
) -> tuple[np.ndarray, list[dict]]:
    """Apply secondary evidence hierarchically: horizontal, then vertical."""
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


def process_scene(scene_name: str) -> dict:
    """Validate local secondary-cluster evidence for one scene."""
    image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
    labels, centers = cluster_lab_image(image, CLUSTER_COUNT)
    selection = load_selection(scene_name)
    selected_clusters = tuple(selection["mortar_clusters"])
    recovery_allowed, quality_gate = secondary_recovery_allowed(selection)
    secondary_cluster = choose_secondary_cluster(centers, selected_clusters)
    primary_mortar, brick_mask = build_masks(labels, selected_clusters)
    combined_clusters = tuple(sorted((*selected_clusters, secondary_cluster)))
    combined_mortar, _ = build_masks(labels, combined_clusters)

    before_components, before_details = classify_components(brick_mask)
    primary_repaired_mask, _ = complete_local_joints(
        brick_mask,
        primary_mortar,
        before_components,
        before_details["thresholds"],
        image.shape,
    )
    if recovery_allowed:
        repaired_mask, actions = complete_secondary_joints(
            primary_repaired_mask,
            primary_mortar,
            combined_mortar,
            image.shape,
        )
    else:
        repaired_mask = primary_repaired_mask
        actions = []
    before_components, before_details = classify_components(primary_repaired_mask)
    after_components, after_details = classify_components(repaired_mask)
    before_preview = draw_diagnostics(
        image,
        before_components,
        before_details["thresholds"]["minimum_area"],
    )
    after_preview = draw_diagnostics(
        image,
        after_components,
        after_details["thresholds"]["minimum_area"],
    )
    comparison = cv2.hconcat([before_preview, after_preview])

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(scene_directory / "secondary_repaired_mask.png"), repaired_mask)
    cv2.imwrite(
        str(scene_directory / "secondary_repair_comparison.png"),
        comparison,
    )
    report = {
        "scene": scene_name,
        "selected_clusters": list(selected_clusters),
        "secondary_cluster": secondary_cluster,
        "quality_gate_passed": recovery_allowed,
        "quality_gate": quality_gate,
        "minimum_combined_coverage": MIN_JOINT_COVERAGE,
        "minimum_secondary_gain": MIN_SECONDARY_COVERAGE_GAIN,
        "before_component_count": len(before_components),
        "after_component_count": len(after_components),
        "before_accepted_count": sum(
            not item["reasons"] for item in before_components
        ),
        "after_accepted_count": sum(
            not item["reasons"] for item in after_components
        ),
        "actions": actions,
    }
    (scene_directory / "secondary_repair_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print("Scene                                gate  primary  secondary  cuts  accepted")
    for scene_name in SCENE_NAMES:
        report = process_scene(scene_name)
        primary = "+".join(f"C{value}" for value in report["selected_clusters"])
        print(
            f'{scene_name:<36} '
            f'{("pass" if report["quality_gate_passed"] else "skip"):<5} '
            f'{primary:<8} '
            f'C{report["secondary_cluster"]:<8} '
            f'{len(report["actions"]):>4} '
            f'{report["before_accepted_count"]:>3}'
            f'->{report["after_accepted_count"]:<3}'
        )
    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

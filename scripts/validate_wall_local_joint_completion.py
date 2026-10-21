import json
import sys
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diagnose_wall_components import (
    classify_components,
    draw_diagnostics,
)
from validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    IMAGE_DIRECTORY,
    cluster_lab_image,
    load_image,
)
from validate_wall_mortar_clusters import build_masks


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_local_joint_completion"
SCENE_VARIANTS = {
    "wall_exposure_dark": (3, 4),
    "wall_stylized": (0,),
    "wall_textured": (4,),
}
MIN_SPLIT_SIZE_RATIO = 1.50
MIN_JOINT_COVERAGE = 0.60
MIN_EDGE_DISTANCE_RATIO = 0.25
MIN_JOINT_SPACING_RATIO = 0.50
JOINT_THICKNESS = 3


def touches_image_border(bbox: dict, image_shape: tuple[int, ...]) -> bool:
    """Return whether a component reaches any image boundary."""
    image_height, image_width = image_shape[:2]
    return (
        bbox["x"] <= 0
        or bbox["y"] <= 0
        or bbox["x"] + bbox["width"] >= image_width
        or bbox["y"] + bbox["height"] >= image_height
    )


def find_supported_joints(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
    nominal_size: float,
) -> list[tuple[int, float]]:
    """Find strong internal mortar traces without extending across row bands."""
    x = bbox["x"]
    y = bbox["y"]
    width = bbox["width"]
    height = bbox["height"]
    local_mask = mortar_mask[y : y + height, x : x + width]

    if orientation == "vertical":
        coverage = np.mean(local_mask > 0, axis=0)
    else:
        coverage = np.mean(local_mask > 0, axis=1)

    edge_distance = max(2, round(nominal_size * MIN_EDGE_DISTANCE_RATIO))
    valid_indices = np.flatnonzero(coverage >= MIN_JOINT_COVERAGE)
    valid_indices = valid_indices[
        (valid_indices >= edge_distance)
        & (valid_indices < len(coverage) - edge_distance)
    ]
    if len(valid_indices) == 0:
        return []

    groups = np.split(valid_indices, np.where(np.diff(valid_indices) > 1)[0] + 1)
    candidates = []
    for group in groups:
        best_local_position = int(group[np.argmax(coverage[group])])
        candidates.append(
            (best_local_position, float(coverage[best_local_position]))
        )

    minimum_spacing = max(2, round(nominal_size * MIN_JOINT_SPACING_RATIO))
    selected = []
    for position, joint_coverage in sorted(
        candidates,
        key=lambda item: item[1],
        reverse=True,
    ):
        if all(abs(position - other[0]) >= minimum_spacing for other in selected):
            selected.append((position, joint_coverage))

    selected.sort(key=lambda item: item[0])
    origin = x if orientation == "vertical" else y
    return [
        (origin + position, joint_coverage)
        for position, joint_coverage in selected
    ]


def is_repair_candidate(component: dict) -> bool:
    """Accept valid components and components rejected only by aspect ratio."""
    reasons = set(component["reasons"])
    return not reasons or reasons == {"aspect"}


def complete_orientation(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
    orientation: str,
) -> tuple[np.ndarray, list[dict]]:
    """Complete supported joints for one orientation."""
    repaired_mask = brick_mask.copy()
    actions = []
    nominal_size = (
        thresholds["median_accepted_width"]
        if orientation == "vertical"
        else thresholds["median_accepted_height"]
    )

    for component in components:
        if not is_repair_candidate(component):
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
        )
        if not joints:
            actions.append(
                {
                    "bbox_px": bbox,
                    "orientation": orientation,
                    "status": "skipped_no_strong_joint",
                    "border_component": touches_image_border(bbox, image_shape),
                    "minimum_coverage": MIN_JOINT_COVERAGE,
                }
            )
            continue

        for cut_position, coverage in joints:
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
                    "border_component": touches_image_border(bbox, image_shape),
                    "minimum_coverage": MIN_JOINT_COVERAGE,
                    "cut_position": cut_position,
                    "coverage": round(coverage, 3),
                }
            )

    return repaired_mask, actions


def complete_local_joints(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
) -> tuple[np.ndarray, list[dict]]:
    """Repair row separation first, then joints inside the resulting rows."""
    horizontal_mask, horizontal_actions = complete_orientation(
        brick_mask,
        mortar_mask,
        components,
        thresholds,
        image_shape,
        "horizontal",
    )
    horizontal_components, horizontal_details = classify_components(horizontal_mask)
    repaired_mask, vertical_actions = complete_orientation(
        horizontal_mask,
        mortar_mask,
        horizontal_components,
        horizontal_details["thresholds"],
        image_shape,
        "vertical",
    )
    return repaired_mask, horizontal_actions + vertical_actions


def process_scene(scene_name: str, mortar_clusters: tuple[int, ...]) -> dict:
    """Validate local joint completion for one scene."""
    image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
    labels, _ = cluster_lab_image(image, CLUSTER_COUNT)
    mortar_mask, brick_mask = build_masks(labels, mortar_clusters)
    before_components, before_details = classify_components(brick_mask)
    repaired_mask, actions = complete_local_joints(
        brick_mask,
        mortar_mask,
        before_components,
        before_details["thresholds"],
        image.shape,
    )
    after_components, after_details = classify_components(repaired_mask)
    for component in after_components:
        component["is_partial"] = touches_image_border(
            component["bbox_px"],
            image.shape,
        )

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
    cv2.imwrite(str(scene_directory / "repaired_brick_mask.png"), repaired_mask)
    cv2.imwrite(str(scene_directory / "repair_comparison.png"), comparison)
    report = {
        "scene": scene_name,
        "mortar_clusters": list(mortar_clusters),
        "before_component_count": len(before_components),
        "after_component_count": len(after_components),
        "after_partial_component_count": sum(
            component["is_partial"] for component in after_components
        ),
        "after_components": after_components,
        "actions": actions,
    }
    (scene_directory / "repair_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print("Scene                     before   after   completed   skipped")
    for scene_name, mortar_clusters in SCENE_VARIANTS.items():
        report = process_scene(scene_name, mortar_clusters)
        completed = sum(
            action["status"] == "completed" for action in report["actions"]
        )
        skipped = len(report["actions"]) - completed
        print(
            f'{report["scene"]:<25} '
            f'{report["before_component_count"]:>6} '
            f'{report["after_component_count"]:>7} '
            f'{completed:>11} '
            f'{skipped:>9}'
        )

    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

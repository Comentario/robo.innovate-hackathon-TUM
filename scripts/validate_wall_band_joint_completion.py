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
    MIN_EDGE_DISTANCE_RATIO,
    MIN_JOINT_COVERAGE,
    MIN_JOINT_SPACING_RATIO,
    MIN_SPLIT_SIZE_RATIO,
    complete_local_joints,
    is_repair_candidate,
    touches_image_border,
)
from validate_wall_mortar_clusters import build_masks
from validate_wall_secondary_cluster_joints import (
    DESIGN_SCENE_NAMES,
    VALIDATION_SCENE_NAMES,
    choose_secondary_cluster,
    complete_secondary_joints,
    secondary_recovery_allowed,
)
from validate_wall_short_components import recover_short_components


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_band_joint_completion"
DEFAULT_SELECTION_DIRECTORY = (
    PROJECT_ROOT / "outputs" / "wall_cluster_selection_metrics" / "selected"
)
HD_SELECTION_DIRECTORY = (
    PROJECT_ROOT / "outputs" / "wall_high_resolution_selection" / "selected"
)
SCENE_NAMES = DESIGN_SCENE_NAMES + VALIDATION_SCENE_NAMES + (
    "wall_high_resolution",
)

BAND_RADIUS = 2
MIN_NEAR_LINE_COVERAGE = 0.50
MIN_BAND_COVERAGE = 0.70


def load_selection(scene_name: str) -> dict:
    """Load the frozen selector result used by this isolated experiment."""
    root = (
        HD_SELECTION_DIRECTORY
        if scene_name == "wall_high_resolution"
        else DEFAULT_SELECTION_DIRECTORY
    )
    selection_path = root / scene_name / "selection.json"
    return json.loads(selection_path.read_text(encoding="utf-8"))


def joint_profiles(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Measure exact-line and narrow-band support for each local position."""
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


def find_band_supported_joints(
    mortar_mask: np.ndarray,
    bbox: dict,
    orientation: str,
    nominal_size: float,
) -> list[dict]:
    """Find strong straight joints and near-threshold joints supported by a band."""
    line_coverage, band_coverage = joint_profiles(
        mortar_mask,
        bbox,
        orientation,
    )
    supported = (line_coverage >= MIN_JOINT_COVERAGE) | (
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


def complete_band_orientation(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
    orientation: str,
) -> tuple[np.ndarray, list[dict]]:
    """Complete joints while retaining the existing geometric safeguards."""
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

        joints = find_band_supported_joints(
            mortar_mask,
            bbox,
            orientation,
            nominal_size,
        )
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
                    "cut_position": cut_position,
                    "line_coverage": round(joint["line_coverage"], 3),
                    "band_coverage": round(joint["band_coverage"], 3),
                    "band_rescue": joint["band_rescue"],
                    "border_component": touches_image_border(
                        bbox,
                        image_shape,
                    ),
                }
            )
    return repaired_mask, actions


def complete_band_joints(
    brick_mask: np.ndarray,
    mortar_mask: np.ndarray,
    image_shape: tuple[int, ...],
) -> tuple[np.ndarray, list[dict]]:
    """Separate rows first, then recompute components before vertical cuts."""
    components, details = classify_components(brick_mask)
    horizontal_mask, horizontal_actions = complete_band_orientation(
        brick_mask,
        mortar_mask,
        components,
        details["thresholds"],
        image_shape,
        "horizontal",
    )
    components, details = classify_components(horizontal_mask)
    repaired_mask, vertical_actions = complete_band_orientation(
        horizontal_mask,
        mortar_mask,
        components,
        details["thresholds"],
        image_shape,
        "vertical",
    )
    return repaired_mask, horizontal_actions + vertical_actions


def finish_pipeline(
    primary_mask: np.ndarray,
    primary_mortar: np.ndarray,
    combined_mortar: np.ndarray,
    selection: dict,
    image_shape: tuple[int, ...],
) -> tuple[np.ndarray, list[dict], list[dict], list[dict]]:
    """Apply unchanged secondary and short-component recovery stages."""
    recovery_allowed, _ = secondary_recovery_allowed(selection)
    if recovery_allowed:
        secondary_mask, secondary_actions = complete_secondary_joints(
            primary_mask,
            primary_mortar,
            combined_mortar,
            image_shape,
        )
    else:
        secondary_mask = primary_mask
        secondary_actions = []

    components, details = classify_components(secondary_mask)
    final_components, recovered_short = recover_short_components(
        components,
        details["thresholds"],
        image_shape,
    )
    return secondary_mask, final_components, secondary_actions, recovered_short


def component_summary(components: list[dict]) -> dict:
    """Summarize accepted boxes and unresolved merged components."""
    accepted = [component for component in components if not component["reasons"]]
    unresolved = [
        component
        for component in accepted
        if component.get("possible_merge", False)
    ]
    return {
        "accepted": len(accepted),
        "unresolved_merges": len(unresolved),
        "unresolved_bboxes": [item["bbox_px"] for item in unresolved],
    }


def process_scene(scene_name: str) -> dict:
    """Compare the current and band-aware pipelines on one scene."""
    image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
    labels, centers = cluster_lab_image(image, CLUSTER_COUNT)
    selection = load_selection(scene_name)
    selected_clusters = tuple(selection["mortar_clusters"])
    secondary_cluster = choose_secondary_cluster(centers, selected_clusters)

    primary_mortar, brick_mask = build_masks(labels, selected_clusters)
    combined_mortar, _ = build_masks(
        labels,
        tuple(sorted((*selected_clusters, secondary_cluster))),
    )

    raw_components, raw_details = classify_components(brick_mask)
    current_primary, _ = complete_local_joints(
        brick_mask,
        primary_mortar,
        raw_components,
        raw_details["thresholds"],
        image.shape,
    )
    current_mask, current_components, current_secondary, _ = finish_pipeline(
        current_primary,
        primary_mortar,
        combined_mortar,
        selection,
        image.shape,
    )

    band_primary, band_actions = complete_band_joints(
        brick_mask,
        primary_mortar,
        image.shape,
    )
    band_mask, band_components, band_secondary, band_short = finish_pipeline(
        band_primary,
        primary_mortar,
        combined_mortar,
        selection,
        image.shape,
    )

    current_details = classify_components(current_mask)[1]
    band_details = classify_components(band_mask)[1]
    current_preview = draw_diagnostics(
        image,
        current_components,
        current_details["thresholds"]["minimum_area"],
    )
    band_preview = draw_diagnostics(
        image,
        band_components,
        band_details["thresholds"]["minimum_area"],
    )

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(scene_directory / "band_primary_mask.png"), band_primary)
    cv2.imwrite(str(scene_directory / "band_final_mask.png"), band_mask)
    cv2.imwrite(str(scene_directory / "band_preview.png"), band_preview)
    cv2.imwrite(
        str(scene_directory / "current_vs_band.png"),
        cv2.hconcat([current_preview, band_preview]),
    )

    report = {
        "scene": scene_name,
        "selected_clusters": list(selected_clusters),
        "secondary_cluster": secondary_cluster,
        "current": component_summary(current_components),
        "band": component_summary(band_components),
        "band_rescue_count": sum(
            action["band_rescue"] for action in band_actions
        ),
        "band_actions": band_actions,
        "current_secondary_actions": current_secondary,
        "band_secondary_actions": band_secondary,
        "short_recovery_count": len(band_short),
    }
    (scene_directory / "band_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print("Scene                                current  band  merges  rescued")
    reports = []
    for scene_name in SCENE_NAMES:
        report = process_scene(scene_name)
        reports.append(report)
        print(
            f"{scene_name:<36} "
            f'{report["current"]["accepted"]:>7} '
            f'{report["band"]["accepted"]:>5} '
            f'{report["band"]["unresolved_merges"]:>7} '
            f'{report["band_rescue_count"]:>8}'
        )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIRECTORY / "band_summary.json").write_text(
        json.dumps(reports, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

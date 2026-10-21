import copy
import json
import sys
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from diagnose_wall_components import classify_components, draw_diagnostics
from validate_wall_lab_clusters import IMAGE_DIRECTORY, load_image
from validate_wall_local_joint_completion import touches_image_border


SELECTION_DIRECTORY = (
    PROJECT_ROOT / "outputs" / "wall_cluster_selection_metrics" / "selected"
)
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_short_component_recovery"
VALIDATION_SCENE_NAMES = (
    "validation_dark_uneven",
    "validation_gray_dark_mortar",
    "validation_irregular_old_wall",
    "validation_low_contrast_perspective",
    "validation_rough_texture",
)
MIN_HEIGHT_RATIO = 0.75
MAX_HEIGHT_RATIO = 1.25
MIN_INTERIOR_WIDTH_RATIO = 0.35
MIN_BORDER_WIDTH_RATIO = 0.20
MAX_WIDTH_RATIO = 0.70
MIN_FILL_RATIO = 0.70


def recover_short_components(
    components: list[dict],
    thresholds: dict,
    image_shape: tuple[int, ...],
) -> tuple[list[dict], list[dict]]:
    """Recover compact half bricks rejected only by their narrow aspect ratio."""
    reviewed_components = copy.deepcopy(components)
    recovered = []
    nominal_width = thresholds["median_accepted_width"]
    nominal_height = thresholds["median_accepted_height"]

    for component in reviewed_components:
        if set(component["reasons"]) != {"aspect"}:
            continue

        bbox = component["bbox_px"]
        is_partial = touches_image_border(bbox, image_shape)
        width_ratio = bbox["width"] / nominal_width
        height_ratio = bbox["height"] / nominal_height
        minimum_width_ratio = (
            MIN_BORDER_WIDTH_RATIO
            if is_partial
            else MIN_INTERIOR_WIDTH_RATIO
        )
        if not minimum_width_ratio <= width_ratio <= MAX_WIDTH_RATIO:
            continue
        if not MIN_HEIGHT_RATIO <= height_ratio <= MAX_HEIGHT_RATIO:
            continue
        if component["fill_ratio"] < MIN_FILL_RATIO:
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


def process_scene(scene_name: str) -> dict:
    """Validate short-component recovery on one selected wall mask."""
    image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
    mask_path = SELECTION_DIRECTORY / scene_name / "selected_brick_mask.png"
    brick_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if brick_mask is None:
        raise FileNotFoundError(f"Could not read selected mask: {mask_path}")

    components, details = classify_components(brick_mask)
    reviewed_components, recovered = recover_short_components(
        components,
        details["thresholds"],
        image.shape,
    )
    before_preview = draw_diagnostics(
        image,
        components,
        details["thresholds"]["minimum_area"],
    )
    after_preview = draw_diagnostics(
        image,
        reviewed_components,
        details["thresholds"]["minimum_area"],
    )
    comparison = cv2.hconcat([before_preview, after_preview])

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(scene_directory / "short_recovery_comparison.png"), comparison)
    report = {
        "scene": scene_name,
        "accepted_before": sum(not item["reasons"] for item in components),
        "recovered_count": len(recovered),
        "accepted_after": sum(
            not item["reasons"] for item in reviewed_components
        ),
        "recovered": recovered,
    }
    (scene_directory / "short_recovery_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print("Scene                                before   recovered   after")
    for scene_name in VALIDATION_SCENE_NAMES:
        report = process_scene(scene_name)
        print(
            f'{scene_name:<36} '
            f'{report["accepted_before"]:>6} '
            f'{report["recovered_count"]:>11} '
            f'{report["accepted_after"]:>7}'
        )
    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

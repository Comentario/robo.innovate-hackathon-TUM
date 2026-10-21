import json
import sys
from pathlib import Path

import cv2


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
    complete_local_joints,
    touches_image_border,
)
from validate_wall_mortar_clusters import build_masks
from validate_wall_secondary_cluster_joints import (
    DESIGN_SCENE_NAMES,
    VALIDATION_SCENE_NAMES,
    choose_secondary_cluster,
    complete_secondary_joints,
    load_selection,
    secondary_recovery_allowed,
)
from validate_wall_short_components import recover_short_components


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_combined_pipeline"
SCENE_NAMES = DESIGN_SCENE_NAMES + VALIDATION_SCENE_NAMES


def accepted_count(components: list[dict]) -> int:
    """Count components that pass the current filters."""
    return sum(not component["reasons"] for component in components)


def process_scene(scene_name: str) -> dict:
    """Run the complete experimental wall post-processing sequence."""
    image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
    labels, centers = cluster_lab_image(image, CLUSTER_COUNT)
    selection = load_selection(scene_name)
    selected_clusters = tuple(selection["mortar_clusters"])
    secondary_cluster = choose_secondary_cluster(centers, selected_clusters)

    primary_mortar, brick_mask = build_masks(labels, selected_clusters)
    raw_components, raw_details = classify_components(brick_mask)
    primary_mask, primary_actions = complete_local_joints(
        brick_mask,
        primary_mortar,
        raw_components,
        raw_details["thresholds"],
        image.shape,
    )
    primary_components, primary_details = classify_components(primary_mask)

    recovery_allowed, quality_gate = secondary_recovery_allowed(selection)
    combined_clusters = tuple(sorted((*selected_clusters, secondary_cluster)))
    combined_mortar, _ = build_masks(labels, combined_clusters)
    if recovery_allowed:
        secondary_mask, secondary_actions = complete_secondary_joints(
            primary_mask,
            primary_mortar,
            combined_mortar,
            image.shape,
        )
    else:
        secondary_mask = primary_mask
        secondary_actions = []

    secondary_components, secondary_details = classify_components(secondary_mask)
    final_components, recovered_short = recover_short_components(
        secondary_components,
        secondary_details["thresholds"],
        image.shape,
    )
    final_accepted = [item for item in final_components if not item["reasons"]]
    partial_count = sum(
        touches_image_border(item["bbox_px"], image.shape)
        for item in final_accepted
    )
    color_eligible_count = sum(
        not touches_image_border(item["bbox_px"], image.shape)
        for item in final_accepted
    )

    primary_preview = draw_diagnostics(
        image,
        primary_components,
        primary_details["thresholds"]["minimum_area"],
    )
    final_preview = draw_diagnostics(
        image,
        final_components,
        secondary_details["thresholds"]["minimum_area"],
    )
    comparison = cv2.hconcat([primary_preview, final_preview])

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(scene_directory / "combined_brick_mask.png"), secondary_mask)
    cv2.imwrite(str(scene_directory / "combined_preview.png"), final_preview)
    cv2.imwrite(str(scene_directory / "combined_comparison.png"), comparison)
    report = {
        "scene": scene_name,
        "evaluation_split": selection["evaluation_split"],
        "selected_clusters": list(selected_clusters),
        "selection_score": selection["selection_score"],
        "primary_repair_count": len(
            [action for action in primary_actions if action["status"] == "completed"]
        ),
        "quality_gate_passed": recovery_allowed,
        "quality_gate": quality_gate,
        "secondary_cluster": secondary_cluster,
        "secondary_repair_count": len(secondary_actions),
        "short_recovery_count": len(recovered_short),
        "accepted_after_primary": accepted_count(primary_components),
        "accepted_after_secondary": accepted_count(secondary_components),
        "accepted_final": len(final_accepted),
        "partial_final": partial_count,
        "color_eligible_final": color_eligible_count,
        "secondary_actions": secondary_actions,
        "recovered_short_components": recovered_short,
    }
    (scene_directory / "combined_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print(
        "Scene                                gate  primary  secondary  short  final"
    )
    reports = []
    for scene_name in SCENE_NAMES:
        report = process_scene(scene_name)
        reports.append(report)
        print(
            f'{scene_name:<36} '
            f'{("pass" if report["quality_gate_passed"] else "skip"):<5} '
            f'{report["accepted_after_primary"]:>7} '
            f'{report["accepted_after_secondary"]:>10} '
            f'{report["short_recovery_count"]:>6} '
            f'{report["accepted_final"]:>6}'
        )

    (OUTPUT_DIRECTORY / "combined_summary.json").write_text(
        json.dumps(reports, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

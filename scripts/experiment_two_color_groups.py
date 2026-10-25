"""Validate a forced two-group color estimate on reliable brick detections."""

import json
from pathlib import Path
import sys

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from perception.color_estimator.measure_lab import (
    GROUP_COLORS,
    INNER_MARGIN_RATIO,
    MEMBERSHIP_SCORE_WEIGHT,
    UNIFORMITY_SCORE_WEIGHT,
    calculate_silhouette,
    calculate_uniformity_scores,
    convert_to_standard_lab,
    draw_classification_preview,
    draw_sampling_preview,
    measure_brick_colors,
    minimum_center_distance,
    run_kmeans,
)


IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
DETECTION_ROOT = PROJECT_ROOT / "outputs" / "hackathon_isolated_bricks_experiment"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "hackathon_two_color_groups"

# These scenes were visually accepted after the latest detector experiment.
VALID_SCENES = (
    "1B_L0_NS",
    "1B_L100_NS",
    "1B_L50_NS",
    "3B_L0_NS",
    "3B_L100_NS",
    "3B_L20_NS",
    "3B_L60_NS",
    "4B_NL_NS",
    "5B_L20_NS",
    "5B_L80_NS",
    "5B_NL_NS",
    "6B_L0_NS",
    "6B_L100_NS",
    "6B_L20_NS",
    "6B_L60_NS",
)


def load_scene(scene: str) -> tuple[np.ndarray, list[dict]]:
    """Load one source image and its accepted experimental detections."""
    image_path = IMAGE_ROOT / f"{scene}.jpg"
    diagnostics_path = DETECTION_ROOT / scene / "diagnostics.json"
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    bricks = []
    for index, detection in enumerate(diagnostics["detections"], start=1):
        bricks.append(
            {
                "id": f"brick_{index:03d}",
                "bbox_px": detection["bbox_px"],
            }
        )
    return image, bricks


def force_two_groups(measurements: list[dict]) -> dict:
    """Assign all samples to exactly two Lab groups ordered dark to light."""
    features = convert_to_standard_lab(measurements)
    labels, centers = run_kmeans(features, 2)
    uniformity_scores = calculate_uniformity_scores(measurements)
    assignments = []

    for index, measurement in enumerate(measurements):
        distances = np.linalg.norm(features[index] - centers, axis=1)
        nearest_distances = np.sort(distances)
        membership_score = 1.0 - float(
            nearest_distances[0] / max(nearest_distances[1], 1e-6)
        )
        membership_score = float(np.clip(membership_score, 0.0, 1.0))
        uniformity_score = uniformity_scores[measurement["id"]]
        color_score = (
            MEMBERSHIP_SCORE_WEIGHT * membership_score
            + UNIFORMITY_SCORE_WEIGHT * uniformity_score
        )
        group_index = int(labels[index])
        assignments.append(
            {
                "id": measurement["id"],
                "group_index": group_index,
                "color_group": f"color_group_{group_index + 1}",
                "color_score": round(color_score, 3),
                "membership_score": round(membership_score, 3),
                "uniformity_score": round(uniformity_score, 3),
            }
        )

    return {
        "status": "accepted_forced_k2",
        "selected_k": 2,
        "group_meaning": {
            "color_group_1": "darker relative Lab group",
            "color_group_2": "lighter relative Lab group",
        },
        "counts": [int(np.count_nonzero(labels == value)) for value in range(2)],
        "centers_lab": [
            [round(float(value), 2) for value in center] for center in centers
        ],
        "minimum_center_delta_e": round(float(minimum_center_distance(centers)), 3),
        "silhouette": round(calculate_silhouette(features, labels), 3),
        "assignments": assignments,
    }


def main() -> None:
    """Run the isolated experiment and save one diagnostic set per scene."""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary = []

    for scene in VALID_SCENES:
        image, bricks = load_scene(scene)
        measurements = measure_brick_colors(image, bricks, INNER_MARGIN_RATIO)
        scene_output = OUTPUT_ROOT / scene
        scene_output.mkdir(parents=True, exist_ok=True)

        sampling_preview = draw_sampling_preview(image, bricks, measurements)
        cv2.imwrite(str(scene_output / "sampling_preview.png"), sampling_preview)
        (scene_output / "lab_measurements.json").write_text(
            json.dumps(measurements, indent=2) + "\n",
            encoding="utf-8",
        )

        if len(measurements) < 2:
            result = {
                "status": "insufficient_samples",
                "selected_k": None,
                "reason": "A two-group estimate requires at least two bricks.",
                "assignments": [],
            }
        else:
            result = force_two_groups(measurements)
            preview = draw_classification_preview(image, bricks, result)
            cv2.imwrite(str(scene_output / "classification_preview.png"), preview)

        (scene_output / "color_classification.json").write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
        summary.append(
            {
                "scene": scene,
                "brick_count": len(bricks),
                "status": result["status"],
                "counts": result.get("counts"),
                "minimum_center_delta_e": result.get("minimum_center_delta_e"),
                "silhouette": result.get("silhouette"),
            }
        )

    (OUTPUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    print("Scene          bricks  groups   deltaE  silhouette  status")
    for item in summary:
        counts = "-" if item["counts"] is None else "/".join(map(str, item["counts"]))
        delta_e = "-" if item["minimum_center_delta_e"] is None else f'{item["minimum_center_delta_e"]:.2f}'
        silhouette = "-" if item["silhouette"] is None else f'{item["silhouette"]:.3f}'
        print(
            f'{item["scene"]:<14} {item["brick_count"]:>6}  {counts:>6}  '
            f'{delta_e:>7}  {silhouette:>10}  {item["status"]}'
        )
    print(f"\nOutputs: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from perception.inventory_manager.inventory import build_color_inventory, save_inventory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "color_estimator"
INNER_MARGIN_RATIO = 0.12
MIN_CLUSTER_SAMPLES = 3
MIN_CLUSTER_RATIO = 0.05
MIN_CENTER_DELTA_E = 6.0
MIN_SILHOUETTE = 0.35
MIN_SPLIT_GAIN = 0.30
MAX_UNIFORM_P90_DELTA_E = 12.0
SILHOUETTE_TIE_MARGIN = 0.03
RNG_SEED = 42
MEMBERSHIP_SCORE_WEIGHT = 0.75
UNIFORMITY_SCORE_WEIGHT = 0.25
GROUP_COLORS = {
    "uniform": (0, 180, 0),
    "color_group_1": (180, 70, 20),
    "color_group_2": (0, 140, 255),
    "color_group_3": (0, 255, 255),
    "unknown": (150, 150, 150),
}


def load_inputs(image_path: Path, inventory_path: Path) -> tuple[np.ndarray, dict]:
    """Load the source image and the detector inventory."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    required_keys = {"image_id", "image_size_px", "bricks"}
    missing_keys = required_keys - inventory.keys()
    if missing_keys:
        raise ValueError(f"Inventory is missing fields: {sorted(missing_keys)}")

    if inventory["image_id"] != image_path.stem:
        raise ValueError(
            "Image ID does not match the inventory: "
            f'{image_path.stem} != {inventory["image_id"]}'
        )

    expected_size = inventory["image_size_px"]
    image_height, image_width = image.shape[:2]
    if (
        image_width != expected_size["width"]
        or image_height != expected_size["height"]
    ):
        raise ValueError("Image size does not match the inventory image size")

    for brick in inventory["bricks"]:
        bbox = brick["bbox_px"]
        if bbox["width"] <= 0 or bbox["height"] <= 0:
            raise ValueError(f'Invalid bbox size for {brick["id"]}')
        if (
            bbox["x"] < 0
            or bbox["y"] < 0
            or bbox["x"] + bbox["width"] > image_width
            or bbox["y"] + bbox["height"] > image_height
        ):
            raise ValueError(f'BBox outside image for {brick["id"]}')

    return image, inventory


def select_color_eligible_bricks(bricks: list[dict]) -> list[dict]:
    """Keep reliable detections while supporting older pallet inventories."""
    return [
        brick
        for brick in bricks
        if brick.get("eligible_for_color", True)
        and not brick.get("is_partial", False)
        and not brick.get("possible_merge", False)
    ]


def calculate_inner_bbox(bbox: dict, margin_ratio: float) -> dict:
    """Shrink a detector bbox to sample only its central region."""
    margin_x = round(bbox["width"] * margin_ratio)
    margin_y = round(bbox["height"] * margin_ratio)

    return {
        "x": bbox["x"] + margin_x,
        "y": bbox["y"] + margin_y,
        "width": bbox["width"] - 2 * margin_x,
        "height": bbox["height"] - 2 * margin_y,
    }


def measure_brick_colors(
    image: np.ndarray,
    bricks: list[dict],
    margin_ratio: float,
) -> list[dict]:
    """Measure robust Lab statistics inside every detected brick."""
    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    measurements = []

    for brick in bricks:
        inner_bbox = calculate_inner_bbox(brick["bbox_px"], margin_ratio)
        x = inner_bbox["x"]
        y = inner_bbox["y"]
        width = inner_bbox["width"]
        height = inner_bbox["height"]
        roi = lab_image[y : y + height, x : x + width]

        median_l, median_a, median_b = np.median(roi, axis=(0, 1))
        l_spread = np.percentile(roi[:, :, 0], 75) - np.percentile(
            roi[:, :, 0], 25
        )

        measurements.append(
            {
                "id": brick["id"],
                "inner_bbox_px": inner_bbox,
                "median_l": round(float(median_l), 2),
                "median_a": round(float(median_a), 2),
                "median_b": round(float(median_b), 2),
                "l_spread": round(float(l_spread), 2),
            }
        )

    return measurements


def convert_to_standard_lab(measurements: list[dict]) -> np.ndarray:
    """Convert OpenCV 8-bit Lab medians to standard CIELAB coordinates."""
    return np.asarray(
        [
            [
                item["median_l"] * 100.0 / 255.0,
                item["median_a"] - 128.0,
                item["median_b"] - 128.0,
            ]
            for item in measurements
        ],
        dtype=np.float32,
    )


def run_kmeans(features: np.ndarray, cluster_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Run deterministic K-means and order clusters by center lightness."""
    if cluster_count == 1:
        return np.zeros(len(features), dtype=np.int32), np.mean(
            features, axis=0, keepdims=True
        )

    cv2.setRNGSeed(RNG_SEED)
    _, raw_labels, raw_centers = cv2.kmeans(
        features,
        cluster_count,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.01),
        10,
        cv2.KMEANS_PP_CENTERS,
    )
    center_order = np.argsort(raw_centers[:, 0])
    label_mapping = {
        int(original_label): ordered_label
        for ordered_label, original_label in enumerate(center_order)
    }
    labels = np.asarray(
        [label_mapping[int(label)] for label in raw_labels.ravel()],
        dtype=np.int32,
    )
    return labels, raw_centers[center_order]


def calculate_silhouette(features: np.ndarray, labels: np.ndarray) -> float:
    """Calculate the mean silhouette without an external ML dependency."""
    cluster_count = len(np.unique(labels))
    if cluster_count == 1:
        return 0.0

    distances = np.linalg.norm(features[:, None, :] - features[None, :, :], axis=2)
    sample_scores = []
    for index, label in enumerate(labels):
        same_cluster = np.flatnonzero(labels == label)
        same_cluster = same_cluster[same_cluster != index]
        if len(same_cluster) == 0:
            sample_scores.append(0.0)
            continue

        intra_distance = float(np.mean(distances[index, same_cluster]))
        other_distances = [
            float(np.mean(distances[index, labels == other_label]))
            for other_label in range(cluster_count)
            if other_label != label
        ]
        nearest_cluster_distance = min(other_distances)
        denominator = max(intra_distance, nearest_cluster_distance)
        sample_scores.append(
            0.0
            if denominator == 0.0
            else (nearest_cluster_distance - intra_distance) / denominator
        )
    return float(np.mean(sample_scores))


def minimum_center_distance(centers: np.ndarray) -> float | None:
    """Return the smallest CIELAB distance between any two centers."""
    if len(centers) == 1:
        return None
    return min(
        float(np.linalg.norm(centers[first] - centers[second]))
        for first in range(len(centers))
        for second in range(first + 1, len(centers))
    )


def evaluate_candidate(
    features: np.ndarray,
    cluster_count: int,
    baseline_inertia: float | None = None,
) -> dict:
    """Fit and score one candidate cluster count."""
    labels, centers = run_kmeans(features, cluster_count)
    point_distances = np.linalg.norm(features - centers[labels], axis=1)
    inertia = float(np.sum(point_distances**2))
    counts = [int(np.count_nonzero(labels == index)) for index in range(cluster_count)]
    minimum_group_size = max(
        MIN_CLUSTER_SAMPLES,
        math.ceil(len(features) * MIN_CLUSTER_RATIO),
    )
    center_distance = minimum_center_distance(centers)
    silhouette = calculate_silhouette(features, labels)
    split_gain = (
        0.0
        if baseline_inertia is None or baseline_inertia <= 1e-9
        else 1.0 - inertia / baseline_inertia
    )
    uniform_p90 = float(np.percentile(point_distances, 90))

    reasons = []
    if cluster_count == 1:
        if uniform_p90 > MAX_UNIFORM_P90_DELTA_E:
            reasons.append("uniform_group_too_dispersed")
    else:
        if min(counts) < minimum_group_size:
            reasons.append("cluster_too_small")
        if center_distance is not None and center_distance < MIN_CENTER_DELTA_E:
            reasons.append("centers_too_close")
        if silhouette < MIN_SILHOUETTE:
            reasons.append("low_silhouette")
        if split_gain < MIN_SPLIT_GAIN:
            reasons.append("insufficient_split_gain")

    return {
        "k": cluster_count,
        "valid": not reasons,
        "reasons": reasons,
        "counts": counts,
        "centers_lab": [
            [round(float(value), 2) for value in center] for center in centers
        ],
        "minimum_center_delta_e": (
            None if center_distance is None else round(center_distance, 3)
        ),
        "silhouette": round(silhouette, 3),
        "split_gain_from_k1": round(split_gain, 3),
        "inertia": round(inertia, 3),
        "uniform_p90_delta_e": round(uniform_p90, 3),
        "labels": labels.tolist(),
    }


def choose_candidate(candidates: list[dict]) -> tuple[dict | None, str]:
    """Prefer real separated groups, otherwise accept a compact uniform group."""
    separated = [candidate for candidate in candidates[1:] if candidate["valid"]]
    if separated:
        best_silhouette = max(candidate["silhouette"] for candidate in separated)
        near_best = [
            candidate
            for candidate in separated
            if candidate["silhouette"] >= best_silhouette - SILHOUETTE_TIE_MARGIN
        ]
        selected = min(near_best, key=lambda candidate: candidate["k"])
        return selected, "meaningful_separated_groups"

    if candidates[0]["valid"]:
        return candidates[0], "compact_uniform_group"
    return None, "no_reliable_cluster_count"


def calculate_uniformity_scores(measurements: list[dict]) -> dict[str, float]:
    """Score low within-brick lightness spread as more reliable."""
    spreads = np.asarray(
        [item["l_spread"] for item in measurements],
        dtype=np.float32,
    )
    lower = float(np.percentile(spreads, 25))
    upper = float(np.percentile(spreads, 95))
    if upper <= lower:
        return {item["id"]: 1.0 for item in measurements}
    return {
        item["id"]: float(
            np.clip((upper - item["l_spread"]) / (upper - lower), 0.0, 1.0)
        )
        for item in measurements
    }


def build_relative_lab_classification(measurements: list[dict]) -> dict:
    """Select one, two, or three relative CIELAB groups."""
    if len(measurements) < MIN_CLUSTER_SAMPLES:
        raise ValueError("At least three Lab measurements are required")

    features = convert_to_standard_lab(measurements)
    k1 = evaluate_candidate(features, 1)
    candidates = [
        k1,
        evaluate_candidate(features, 2, k1["inertia"]),
        evaluate_candidate(features, 3, k1["inertia"]),
    ]
    selected, selection_reason = choose_candidate(candidates)
    selected_k = None if selected is None else selected["k"]
    uniformity_scores = calculate_uniformity_scores(measurements)
    assignments = []
    for index, measurement in enumerate(measurements):
        if selected is None:
            group_index = None
            group_name = "unknown"
            membership_score = 0.0
            uniformity_score = 0.0
            color_score = 0.0
        else:
            group_index = selected["labels"][index]
            group_name = (
                "uniform" if selected_k == 1 else f"color_group_{group_index + 1}"
            )
            centers = np.asarray(selected["centers_lab"], dtype=np.float32)
            distances = np.linalg.norm(features[index] - centers, axis=1)
            if selected_k == 1:
                membership_score = 1.0 - float(
                    distances[0] / MAX_UNIFORM_P90_DELTA_E
                )
            else:
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
        assignments.append(
            {
                "id": measurement["id"],
                "group_index": group_index,
                "color_group": group_name,
                "color_score": round(float(color_score), 3),
                "membership_score": round(float(membership_score), 3),
                "uniformity_score": round(float(uniformity_score), 3),
            }
        )

    public_candidates = []
    for candidate in candidates:
        public_candidate = dict(candidate)
        del public_candidate["labels"]
        public_candidates.append(public_candidate)

    return {
        "status": "accepted" if selected is not None else "inconclusive",
        "selected_k": selected_k,
        "selection_reason": selection_reason,
        "feature_space": "CIELAB",
        "thresholds": {
            "minimum_cluster_samples": MIN_CLUSTER_SAMPLES,
            "minimum_cluster_ratio": MIN_CLUSTER_RATIO,
            "minimum_center_delta_e": MIN_CENTER_DELTA_E,
            "minimum_silhouette": MIN_SILHOUETTE,
            "minimum_split_gain": MIN_SPLIT_GAIN,
            "maximum_uniform_p90_delta_e": MAX_UNIFORM_P90_DELTA_E,
        },
        "candidates": public_candidates,
        "assignments": assignments,
    }


def draw_sampling_preview(
    image: np.ndarray,
    bricks: list[dict],
    measurements: list[dict],
) -> np.ndarray:
    """Draw detector bboxes in blue and sampled regions in green."""
    preview = image.copy()

    for brick, measurement in zip(bricks, measurements):
        bbox = brick["bbox_px"]
        inner_bbox = measurement["inner_bbox_px"]
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
            (255, 0, 0),
            1,
        )
        cv2.rectangle(
            preview,
            (inner_bbox["x"], inner_bbox["y"]),
            (
                inner_bbox["x"] + inner_bbox["width"],
                inner_bbox["y"] + inner_bbox["height"],
            ),
            (0, 255, 0),
            1,
        )

    return preview


def draw_classification_preview(
    image: np.ndarray,
    all_bricks: list[dict],
    classification: dict,
) -> np.ndarray:
    """Draw classified boxes and leave excluded detections in gray."""
    preview = image.copy()
    assignments = {
        item["id"]: item for item in classification["assignments"]
    }
    for brick in all_bricks:
        bbox = brick["bbox_px"]
        assignment = assignments.get(
            brick["id"],
            {"color_group": "unknown", "color_score": 0.0},
        )
        group = assignment["color_group"]
        color = GROUP_COLORS[group]
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
            color,
            2,
        )
        if group != "unknown":
            label = (
                "U" if group == "uniform" else f"G{assignment['group_index'] + 1}"
            )
            label = f"{label} {assignment['color_score']:.2f}"
            cv2.putText(
                preview,
                label,
                (bbox["x"] + 2, bbox["y"] + 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.35, image.shape[1] / 3000),
                color,
                1,
                cv2.LINE_AA,
            )
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure robust Lab color statistics for detected bricks."
    )
    parser.add_argument("image", type=Path, help="Source image path")
    parser.add_argument("inventory", type=Path, help="Matching partial inventory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (defaults to outputs/color_estimator/<image_id>)",
    )
    parser.add_argument(
        "--inventory-output",
        type=Path,
        help="Optional separate path for the enriched color inventory",
    )
    args = parser.parse_args()

    image, inventory = load_inputs(args.image, args.inventory)
    all_bricks = inventory["bricks"]
    bricks = select_color_eligible_bricks(all_bricks)
    if not bricks:
        raise ValueError("Inventory has no detections eligible for color estimation")

    output_directory = args.output_dir or DEFAULT_OUTPUT_ROOT / inventory["image_id"]
    measurements_path = output_directory / "lab_measurements.json"
    preview_path = output_directory / "sampling_preview.png"
    classification_path = output_directory / "color_classification.json"
    classification_preview_path = output_directory / "classification_preview.png"
    colored_inventory_path = (
        args.inventory_output
        if args.inventory_output is not None
        else output_directory / "inventory_with_color.json"
    )
    measurements = measure_brick_colors(image, bricks, INNER_MARGIN_RATIO)
    preview = draw_sampling_preview(image, bricks, measurements)
    classification = build_relative_lab_classification(measurements)
    colored_inventory = build_color_inventory(inventory, classification)
    classification_preview = draw_classification_preview(
        image,
        all_bricks,
        classification,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    measurements_path.write_text(
        json.dumps(measurements, indent=2) + "\n",
        encoding="utf-8",
    )
    classification_path.write_text(
        json.dumps(classification, indent=2) + "\n",
        encoding="utf-8",
    )
    save_inventory(colored_inventory, colored_inventory_path)
    if not cv2.imwrite(str(preview_path), preview):
        raise OSError(f"Could not write preview: {preview_path}")
    if not cv2.imwrite(str(classification_preview_path), classification_preview):
        raise OSError(
            f"Could not write preview: {classification_preview_path}"
        )

    print("ID         median L   median a   median b   L spread")
    for item in measurements:
        print(
            f'{item["id"]:<10} '
            f'{item["median_l"]:>8.2f} '
            f'{item["median_a"]:>10.2f} '
            f'{item["median_b"]:>10.2f} '
            f'{item["l_spread"]:>10.2f}'
        )

    print(f"\nInventory bricks: {len(all_bricks)}")
    print(f"Eligible bricks: {len(measurements)}")
    print(f"Skipped bricks: {len(all_bricks) - len(measurements)}")
    print(f"Classification status: {classification['status']}")
    print(f"Selected K: {classification['selected_k']}")
    print(f"Selection reason: {classification['selection_reason']}")
    print(f"Measurements: {measurements_path}")
    print(f"Preview: {preview_path}")
    print(f"Classification: {classification_path}")
    print(f"Classification preview: {classification_preview_path}")
    print(f"Color inventory: {colored_inventory_path}")


if __name__ == "__main__":
    main()

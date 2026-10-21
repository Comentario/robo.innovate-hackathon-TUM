import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


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

GROUP_COLORS = (
    (180, 70, 20),
    (0, 140, 255),
    (0, 255, 255),
)
UNKNOWN_COLOR = (150, 150, 150)


def load_json(path: Path):
    """Load one JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


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


def build_result(measurements: list[dict]) -> dict:
    """Evaluate K=1, K=2, and K=3 using standard CIELAB features."""
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


def draw_preview(
    image: np.ndarray,
    inventory: dict,
    result: dict,
) -> np.ndarray:
    """Draw the selected experimental groups over detector boxes."""
    preview = image.copy()
    assignment_by_id = {
        assignment["id"]: assignment for assignment in result["assignments"]
    }
    selected_k = result["selected_k"]
    for brick in inventory["bricks"]:
        bbox = brick["bbox_px"]
        assignment = assignment_by_id.get(brick["id"])
        if assignment is None or assignment["group_index"] is None:
            color = UNKNOWN_COLOR
            label = "X"
        else:
            group_index = assignment["group_index"]
            color = GROUP_COLORS[0 if selected_k == 1 else group_index]
            label = "U" if selected_k == 1 else f"G{group_index + 1}"
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
            color,
            2,
        )
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


def build_candidate_preview_result(
    measurements: list[dict],
    cluster_count: int,
) -> dict:
    """Build the minimal result structure needed to preview one candidate K."""
    features = convert_to_standard_lab(measurements)
    labels, _ = run_kmeans(features, cluster_count)
    return {
        "selected_k": cluster_count,
        "assignments": [
            {"id": item["id"], "group_index": int(label)}
            for item, label in zip(measurements, labels)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare K=1, K=2, and K=3 using full CIELAB measurements."
    )
    parser.add_argument("image", type=Path, help="Source image path")
    parser.add_argument("inventory", type=Path, help="Matching detector inventory")
    parser.add_argument("measurements", type=Path, help="Lab measurements JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {args.image}")
    inventory = load_json(args.inventory)
    measurements = load_json(args.measurements)
    if inventory["image_id"] != args.image.stem:
        raise ValueError("Image ID does not match the inventory")

    result = build_result(measurements)
    preview = draw_preview(image, inventory, result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "lab_cluster_count_experiment.json"
    preview_path = args.output_dir / "selected_k_preview.png"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not cv2.imwrite(str(preview_path), preview):
        raise OSError(f"Could not write preview: {preview_path}")
    for cluster_count in (1, 2, 3):
        candidate_result = build_candidate_preview_result(
            measurements,
            cluster_count,
        )
        candidate_preview = draw_preview(image, inventory, candidate_result)
        candidate_preview_path = args.output_dir / f"k{cluster_count}_preview.png"
        if not cv2.imwrite(str(candidate_preview_path), candidate_preview):
            raise OSError(f"Could not write preview: {candidate_preview_path}")

    print(f"Status: {result['status']}")
    print(f"Selected K: {result['selected_k']}")
    print(f"Reason: {result['selection_reason']}")
    for candidate in result["candidates"]:
        print(
            f"K={candidate['k']}: valid={candidate['valid']}, "
            f"counts={candidate['counts']}, "
            f"min_delta_e={candidate['minimum_center_delta_e']}, "
            f"silhouette={candidate['silhouette']}, "
            f"split_gain={candidate['split_gain_from_k1']}, "
            f"uniform_p90={candidate['uniform_p90_delta_e']}, "
            f"reasons={candidate['reasons']}"
        )
    print(f"Metrics: {result_path}")
    print(f"Preview: {preview_path}")
    print(f"Candidate previews: {args.output_dir / 'kN_preview.png'}")


if __name__ == "__main__":
    main()

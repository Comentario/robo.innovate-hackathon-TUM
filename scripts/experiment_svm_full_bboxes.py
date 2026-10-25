"""Evaluate safety-biased SVM color classification on paired clean images."""

import json
from pathlib import Path

import cv2
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
DETECTION_ROOT = PROJECT_ROOT / "outputs" / "hackathon_isolated_bricks_experiment"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "hackathon_svm_full_bboxes"
INNER_MARGIN_RATIO = 0.12
MIN_GOOD_RECALL_FOR_THRESHOLD = 0.50

# Labels come from the matching image with signs. The clean image preserves the
# same arrangement. A count limit removes the extra shadow detection in 5B.
PAIRED_SCENES = {
    "1B_L0_NS": {"labels": ["good"]},
    "1B_L100_NS": {"labels": ["good"]},
    "3B_L100_NS": {"labels": ["bad", "bad", "good"]},
    "4B_NL_NS": {"labels": ["bad", "bad", "bad", "good"]},
    "5B_L100_NS": {"labels": ["bad", "bad", "bad", "good", "good"]},
    "6B_L100_NS": {
        "labels": ["bad", "bad", "bad", "bad", "good", "good"]
    },
}


def shrink_bbox(bbox: dict) -> dict:
    """Remove borders where neighboring objects or background may appear."""
    margin_x = round(bbox["width"] * INNER_MARGIN_RATIO)
    margin_y = round(bbox["height"] * INNER_MARGIN_RATIO)
    return {
        "x": bbox["x"] + margin_x,
        "y": bbox["y"] + margin_y,
        "width": bbox["width"] - 2 * margin_x,
        "height": bbox["height"] - 2 * margin_y,
    }


def color_arrays(roi: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create Lab, circular HSV, and normalized RGB pixel arrays."""
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    lab[:, 0] *= 100.0 / 255.0
    lab[:, 1:] -= 128.0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    angle = hsv[:, 0] * (2.0 * np.pi / 180.0)
    hsv_chroma = np.column_stack(
        (np.cos(angle), np.sin(angle), hsv[:, 1] / 255.0)
    )

    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.float32)
    normalized_rgb = rgb / np.maximum(np.sum(rgb, axis=1, keepdims=True), 1.0)
    return lab, hsv_chroma, normalized_rgb


def quantile_features(values: np.ndarray) -> list[float]:
    """Describe distribution tails as well as its center."""
    return np.percentile(values, [10, 25, 50, 75, 90], axis=0).ravel().tolist()


def normalized_histogram(values: np.ndarray, bins: int, limits: tuple[float, float]) -> list[float]:
    """Build a fixed-range probability histogram."""
    clipped = np.clip(values, limits[0], limits[1])
    histogram, _ = np.histogram(clipped, bins=bins, range=limits)
    return (histogram / max(np.sum(histogram), 1)).astype(float).tolist()


def extract_features(roi: np.ndarray) -> dict[str, list[float]]:
    """Extract global and spatial color-distribution descriptors."""
    lab, hsv, rgb = color_arrays(roi)
    lab_median = np.median(lab, axis=0).astype(float).tolist()
    chromatic_distribution = (
        quantile_features(lab[:, 1:])
        + quantile_features(hsv)
        + quantile_features(rgb)
    )
    full_distribution = quantile_features(lab) + quantile_features(hsv) + quantile_features(rgb)
    histograms = (
        normalized_histogram(lab[:, 1], 12, (-5.0, 25.0))
        + normalized_histogram(lab[:, 2], 12, (-10.0, 30.0))
        + normalized_histogram(hsv[:, 2], 10, (0.0, 1.0))
        + normalized_histogram(rgb[:, 0], 10, (0.0, 1.0))
        + normalized_histogram(rgb[:, 1], 10, (0.0, 1.0))
    )

    spatial = []
    height, width = roi.shape[:2]
    for row in range(3):
        for column in range(3):
            cell = roi[
                row * height // 3 : (row + 1) * height // 3,
                column * width // 3 : (column + 1) * width // 3,
            ]
            cell_lab, cell_hsv, cell_rgb = color_arrays(cell)
            spatial.extend(np.median(cell_lab[:, 1:], axis=0).astype(float).tolist())
            spatial.extend(np.median(cell_hsv[:, 2:], axis=0).astype(float).tolist())
            spatial.extend(np.median(cell_rgb, axis=0).astype(float).tolist())

    return {
        "lab_median": lab_median,
        "chromatic_distribution": chromatic_distribution,
        "full_distribution": full_distribution,
        "chromatic_histograms": histograms,
        "spatial_chroma": chromatic_distribution + spatial,
    }


def load_samples() -> list[dict]:
    """Pair signed-image labels with full clean-image detector boxes."""
    samples = []
    for scene, metadata in PAIRED_SCENES.items():
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        diagnostics = json.loads(
            (DETECTION_ROOT / scene / "diagnostics.json").read_text(encoding="utf-8")
        )
        detections = diagnostics["detections"][: len(metadata["labels"])]
        if len(detections) != len(metadata["labels"]):
            raise ValueError(f"Not enough detections in {scene}")

        for index, (detection, label) in enumerate(
            zip(detections, metadata["labels"]), start=1
        ):
            bbox = detection["bbox_px"]
            inner = shrink_bbox(bbox)
            roi = image[
                inner["y"] : inner["y"] + inner["height"],
                inner["x"] : inner["x"] + inner["width"],
            ]
            samples.append(
                {
                    "scene": scene,
                    "sample_id": f"brick_{index:03d}",
                    "label": label,
                    "bbox_px": bbox,
                    "inner_bbox_px": inner,
                    "features": extract_features(roi),
                }
            )
    return samples


def create_svm(model_name: str, feature_count: int) -> SVC:
    """Create a balanced linear or nonlinear binary SVM."""
    if model_name == "linear":
        return SVC(kernel="linear", C=1.0, class_weight="balanced")
    return SVC(
        kernel="rbf",
        C=1.0 if model_name == "rbf_c1" else 10.0,
        gamma=1.0 / feature_count,
        class_weight="balanced",
    )


def binary_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict:
    """Report both error directions explicitly."""
    bad_count = max(int(np.sum(labels == 0)), 1)
    good_count = max(int(np.sum(labels == 1)), 1)
    bad_as_bad = int(np.sum((labels == 0) & (predictions == 0)))
    bad_as_good = int(np.sum((labels == 0) & (predictions == 1)))
    good_as_bad = int(np.sum((labels == 1) & (predictions == 0)))
    good_as_good = int(np.sum((labels == 1) & (predictions == 1)))
    bad_recall = bad_as_bad / bad_count
    good_recall = good_as_good / good_count
    return {
        "accuracy": round(float(np.mean(labels == predictions)), 3),
        "balanced_accuracy": round((bad_recall + good_recall) / 2.0, 3),
        "bad_recall": round(bad_recall, 3),
        "good_recall": round(good_recall, 3),
        "bad_as_bad": bad_as_bad,
        "bad_as_good": bad_as_good,
        "good_as_bad": good_as_bad,
        "good_as_good": good_as_good,
    }


def choose_safety_threshold(labels: np.ndarray, scores: np.ndarray) -> float:
    """Prefer fewer Bad-to-Good errors while retaining usable Good recall."""
    unique_scores = np.unique(scores)
    candidates = [float(unique_scores[0] - 1.0)]
    candidates.extend(
        float((left + right) / 2.0)
        for left, right in zip(unique_scores[:-1], unique_scores[1:])
    )
    candidates.append(float(unique_scores[-1] + 1.0))

    ranked = []
    for threshold in candidates:
        predictions = (scores >= threshold).astype(np.int32)
        result = binary_metrics(labels, predictions)
        if result["good_recall"] >= MIN_GOOD_RECALL_FOR_THRESHOLD:
            ranked.append(
                (
                    result["bad_recall"],
                    result["balanced_accuracy"],
                    result["good_recall"],
                    threshold,
                )
            )
    return max(ranked)[-1] if ranked else 0.0


def inner_threshold(
    features: np.ndarray,
    labels: np.ndarray,
    scenes: np.ndarray,
    model_name: str,
) -> float:
    """Select a safety threshold without using the outer test scene."""
    scores = np.zeros(len(labels), dtype=np.float32)
    for held_out_scene in sorted(set(scenes)):
        validation = scenes == held_out_scene
        training = ~validation
        scaler = StandardScaler().fit(features[training])
        train_x = scaler.transform(features[training])
        validation_x = scaler.transform(features[validation])
        svm = create_svm(model_name, features.shape[1])
        svm.fit(train_x, labels[training])
        scores[validation] = svm.decision_function(validation_x)
    return choose_safety_threshold(labels, scores)


def cross_validate(samples: list[dict], feature_name: str, model_name: str) -> dict:
    """Leave one paired scene out and calibrate threshold inside training only."""
    scenes = np.asarray([sample["scene"] for sample in samples])
    labels = np.asarray([1 if sample["label"] == "good" else 0 for sample in samples])
    features = np.asarray(
        [sample["features"][feature_name] for sample in samples], dtype=np.float32
    )
    predictions = np.zeros(len(samples), dtype=np.int32)
    thresholds = {}

    for held_out_scene in sorted(set(scenes)):
        test = scenes == held_out_scene
        train = ~test
        threshold = inner_threshold(
            features[train], labels[train], scenes[train], model_name
        )
        scaler = StandardScaler().fit(features[train])
        train_x = scaler.transform(features[train])
        test_x = scaler.transform(features[test])
        svm = create_svm(model_name, features.shape[1])
        svm.fit(train_x, labels[train])
        predictions[test] = (svm.decision_function(test_x) >= threshold).astype(np.int32)
        thresholds[held_out_scene] = round(float(threshold), 4)

    return {
        "feature": feature_name,
        "model": model_name,
        **binary_metrics(labels, predictions),
        "thresholds_by_held_out_scene": thresholds,
        "predictions": predictions.tolist(),
    }


def draw_predictions(samples: list[dict], result: dict) -> None:
    """Save clean-image previews for cross-validated predictions."""
    for scene in PAIRED_SCENES:
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        for index, sample in enumerate(samples):
            if sample["scene"] != scene:
                continue
            predicted = "good" if result["predictions"][index] == 1 else "bad"
            correct = predicted == sample["label"]
            color = (0, 180, 0) if correct else (0, 0, 255)
            bbox = sample["bbox_px"]
            cv2.rectangle(
                image,
                (bbox["x"], bbox["y"]),
                (bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]),
                color,
                3,
            )
            cv2.putText(
                image,
                f'{sample["label"]}->{predicted}',
                (bbox["x"] + 3, bbox["y"] + 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_preview.png"), image)


def main() -> None:
    """Run full-bbox feature and SVM comparisons."""
    samples = load_samples()
    feature_names = list(samples[0]["features"])
    results = [
        cross_validate(samples, feature_name, model_name)
        for feature_name in feature_names
        for model_name in ("linear", "rbf_c1", "rbf_c10")
    ]
    results.sort(
        key=lambda item: (
            item["bad_recall"],
            item["balanced_accuracy"],
            item["good_recall"],
        ),
        reverse=True,
    )
    best = results[0]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "comparison.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_ROOT / "labeled_samples.json").write_text(
        json.dumps(samples, indent=2) + "\n", encoding="utf-8"
    )
    draw_predictions(samples, best)

    print("Feature                    SVM       bad_rec good_rec bal_acc accuracy BG GB")
    for result in results:
        print(
            f'{result["feature"]:<26} {result["model"]:<8} '
            f'{result["bad_recall"]:>7.3f} {result["good_recall"]:>8.3f} '
            f'{result["balanced_accuracy"]:>7.3f} {result["accuracy"]:>8.3f} '
            f'{result["bad_as_good"]:>2} {result["good_as_bad"]:>2}'
        )
    print(f"\nBest: {best['feature']} + {best['model']}")
    print(f"Outputs: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()

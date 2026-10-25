"""Compare background-independent color features on labeled brick ROIs."""

import json
from pathlib import Path
import sys

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from perception.color_estimator.measure_lab import calculate_inner_bbox


IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
DETECTION_ROOT = PROJECT_ROOT / "outputs" / "hackathon_isolated_bricks_experiment"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "hackathon_labeled_color_features"
INNER_MARGIN_RATIO = 0.12

# Labels were read from the matching images with signs. Measurements always use
# the sign-free image so the paper does not contaminate the brick color.
LABELED_SCENES = {
    "1B_L0_NS": {"condition": "L0", "labels": ["good"]},
    "1B_L100_NS": {"condition": "L100", "labels": ["good"]},
    "1B_L50_NS": {"condition": "L50", "labels": ["good"]},
    "3B_L0_NS": {"condition": "L0", "labels": ["bad", "bad", "good"]},
    "3B_L100_NS": {"condition": "L100", "labels": ["bad", "bad", "good"]},
    "3B_L20_NS": {"condition": "L20", "labels": ["bad", "bad", "good"]},
    "3B_L60_NS": {"condition": "L60", "labels": ["bad", "bad", "good"]},
    "4B_NL_NS": {"condition": "NL", "labels": ["bad", "bad", "bad", "good"]},
    "5B_L20_NS": {
        "condition": "L20",
        "labels": ["bad", "bad", "bad", "good", "good"],
    },
    "5B_L80_NS": {
        "condition": "L80",
        "labels": ["bad", "bad", "bad", "good", "good"],
    },
    "5B_NL_NS": {
        "condition": "NL",
        "labels": ["bad", "bad", "bad", "good", "good"],
    },
    "6B_L0_NS": {
        "condition": "L0",
        "labels": ["bad", "bad", "bad", "bad", "good", "good"],
    },
    "6B_L100_NS": {
        "condition": "L100",
        "labels": ["bad", "bad", "bad", "bad", "good", "good"],
    },
    "6B_L20_NS": {
        "condition": "L20",
        "labels": ["bad", "bad", "bad", "bad", "good", "good"],
    },
    "6B_L60_NS": {
        "condition": "L60",
        "labels": ["bad", "bad", "bad", "bad", "good", "good"],
    },
}


def robust_summary(values: np.ndarray) -> list[float]:
    """Return a median and interquartile range for every channel."""
    medians = np.median(values, axis=0)
    spreads = np.percentile(values, 75, axis=0) - np.percentile(values, 25, axis=0)
    return np.concatenate((medians, spreads)).astype(float).tolist()


def extract_features(image: np.ndarray, bbox: dict) -> dict[str, list[float]]:
    """Extract several color descriptions using only pixels inside one brick."""
    inner = calculate_inner_bbox(bbox, INNER_MARGIN_RATIO)
    x, y = inner["x"], inner["y"]
    roi = image[y : y + inner["height"], x : x + inner["width"]]

    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    lab[:, 0] *= 100.0 / 255.0
    lab[:, 1:] -= 128.0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    hue_angle = hsv[:, 0] * (2.0 * np.pi / 180.0)
    hsv_chroma = np.column_stack(
        (
            np.cos(hue_angle),
            np.sin(hue_angle),
            hsv[:, 1] / 255.0,
        )
    )

    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.float32)
    channel_sum = np.maximum(np.sum(rgb, axis=1, keepdims=True), 1.0)
    normalized_rgb = rgb / channel_sum

    lab_summary = robust_summary(lab)
    ab_summary = robust_summary(lab[:, 1:])
    hsv_summary = robust_summary(hsv_chroma)
    rgb_summary = robust_summary(normalized_rgb)

    return {
        "lab_median": lab_summary[:3],
        "lab_ab": ab_summary[:2],
        "hsv_hs": hsv_summary,
        "normalized_rgb": rgb_summary,
        "combined_chroma": ab_summary + hsv_summary + rgb_summary,
        "combined_full": lab_summary + hsv_summary + rgb_summary,
    }


def load_samples() -> list[dict]:
    """Build the labeled table from accepted detector outputs."""
    samples = []
    for scene, metadata in LABELED_SCENES.items():
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        diagnostics = json.loads(
            (DETECTION_ROOT / scene / "diagnostics.json").read_text(encoding="utf-8")
        )
        detections = diagnostics["detections"]
        if len(detections) != len(metadata["labels"]):
            raise ValueError(f"Detection/label count mismatch in {scene}")

        for index, (detection, label) in enumerate(
            zip(detections, metadata["labels"]), start=1
        ):
            samples.append(
                {
                    "scene": scene,
                    "condition": metadata["condition"],
                    "brick_id": f"brick_{index:03d}",
                    "bbox_px": detection["bbox_px"],
                    "label": label,
                    "features": extract_features(image, detection["bbox_px"]),
                }
            )
    return samples


def standardize(train: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scale features using training statistics only."""
    center = np.mean(train, axis=0)
    scale = np.std(train, axis=0)
    scale[scale < 1e-6] = 1.0
    return (train - center) / scale, (test - center) / scale


def predict_centroid(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    """Predict the nearest labeled class center."""
    centers = np.asarray([np.mean(train_x[train_y == label], axis=0) for label in (0, 1)])
    distances = np.linalg.norm(test_x[:, None, :] - centers[None, :, :], axis=2)
    return np.argmin(distances, axis=1)


def predict_one_nearest(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    """Predict the class of the closest labeled training sample."""
    distances = np.linalg.norm(test_x[:, None, :] - train_x[None, :, :], axis=2)
    return train_y[np.argmin(distances, axis=1)]


def calculate_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict:
    """Calculate accuracy and class-balanced accuracy."""
    recalls = []
    confusion = {"bad_as_bad": 0, "bad_as_good": 0, "good_as_bad": 0, "good_as_good": 0}
    for expected, predicted in zip(labels, predictions):
        confusion[f"{'good' if expected else 'bad'}_as_{'good' if predicted else 'bad'}"] += 1
    for label in (0, 1):
        mask = labels == label
        if np.any(mask):
            recalls.append(float(np.mean(predictions[mask] == labels[mask])))
    return {
        "accuracy": round(float(np.mean(predictions == labels)), 3),
        "balanced_accuracy": round(float(np.mean(recalls)), 3),
        "confusion": confusion,
    }


def cross_validate(samples: list[dict], feature_name: str, method: str) -> dict:
    """Leave one complete lighting condition out at a time."""
    labels = np.asarray([1 if item["label"] == "good" else 0 for item in samples])
    conditions = np.asarray([item["condition"] for item in samples])
    features = np.asarray([item["features"][feature_name] for item in samples], dtype=np.float32)
    predictions = np.full(len(samples), -1, dtype=np.int32)
    folds = []

    for condition in sorted(set(conditions)):
        test_mask = conditions == condition
        train_mask = ~test_mask
        train_x, test_x = standardize(features[train_mask], features[test_mask])
        train_y = labels[train_mask]
        if method == "nearest_centroid":
            fold_predictions = predict_centroid(train_x, train_y, test_x)
        else:
            fold_predictions = predict_one_nearest(train_x, train_y, test_x)
        predictions[test_mask] = fold_predictions
        fold_metrics = calculate_metrics(labels[test_mask], fold_predictions)
        folds.append({"held_out_condition": condition, **fold_metrics})

    return {
        "feature": feature_name,
        "method": method,
        **calculate_metrics(labels, predictions),
        "folds": folds,
        "predictions": predictions.tolist(),
    }


def draw_predictions(samples: list[dict], result: dict) -> None:
    """Save cross-validated predictions with green correct and red incorrect boxes."""
    for scene in LABELED_SCENES:
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        scene_samples = [
            (index, sample) for index, sample in enumerate(samples) if sample["scene"] == scene
        ]
        for sample_index, sample in scene_samples:
            predicted = "good" if result["predictions"][sample_index] == 1 else "bad"
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
                f'{sample["label"]} -> {predicted}',
                (bbox["x"] + 3, bbox["y"] + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_prediction.png"), image)


def main() -> None:
    """Run the comparison and save diagnostics for the best configuration."""
    samples = load_samples()
    feature_names = list(samples[0]["features"])
    results = [
        cross_validate(samples, feature_name, method)
        for feature_name in feature_names
        for method in ("nearest_centroid", "one_nearest")
    ]
    results.sort(
        key=lambda item: (item["balanced_accuracy"], item["accuracy"]),
        reverse=True,
    )
    best = results[0]

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    public_samples = []
    for sample in samples:
        public_samples.append(
            {
                "scene": sample["scene"],
                "condition": sample["condition"],
                "brick_id": sample["brick_id"],
                "label": sample["label"],
                "features": sample["features"],
            }
        )
    (OUTPUT_ROOT / "labeled_features.json").write_text(
        json.dumps(public_samples, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_ROOT / "comparison.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    draw_predictions(samples, best)

    print("Feature             method              bal_acc  accuracy")
    for result in results:
        print(
            f'{result["feature"]:<20} {result["method"]:<19} '
            f'{result["balanced_accuracy"]:>7.3f}  {result["accuracy"]:>8.3f}'
        )
    print(f'\nBest: {best["feature"]} + {best["method"]}')
    print(f'Confusion: {best["confusion"]}')
    print(f"Outputs: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()

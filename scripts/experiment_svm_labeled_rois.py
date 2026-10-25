"""Evaluate OpenCV SVM classifiers on directly labeled brick regions."""

import json
from pathlib import Path

import cv2
import numpy as np
from sklearn.svm import SVC


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "hackathon_svm_labeled_rois"

# Rectangles use only visible brick material above the paper labels.
# Each tuple is (x, y, width, height, class).
LABELED_ROIS = {
    "1B_L0_S": [(625, 340, 165, 390, "good")],
    "1B_L100_S": [(625, 340, 160, 390, "good")],
    "3B_L100_S": [
        (620, 340, 170, 420, "bad"),
        (835, 340, 160, 420, "bad"),
        (1070, 340, 165, 420, "good"),
    ],
    "3B_NL_S": [
        (450, 335, 190, 90, "bad"),
        (800, 335, 160, 90, "bad"),
        (1150, 335, 160, 90, "good"),
    ],
    "4B_NL_S": [
        (395, 335, 190, 85, "bad"),
        (650, 335, 165, 85, "bad"),
        (895, 335, 155, 85, "bad"),
        (1150, 335, 155, 85, "good"),
    ],
    "5B_L100_S": [
        (480, 335, 155, 410, "bad"),
        (680, 335, 150, 410, "bad"),
        (875, 335, 145, 410, "bad"),
        (1070, 335, 145, 410, "good"),
        (1265, 335, 150, 410, "good"),
    ],
    "6B_L100_S": [
        (310, 335, 155, 410, "bad"),
        (500, 335, 145, 410, "bad"),
        (685, 335, 145, 410, "bad"),
        (890, 335, 140, 410, "bad"),
        (1080, 335, 140, 410, "good"),
        (1280, 335, 145, 410, "good"),
    ],
}


def robust_summary(values: np.ndarray) -> list[float]:
    """Return channel medians and interquartile ranges."""
    median = np.median(values, axis=0)
    spread = np.percentile(values, 75, axis=0) - np.percentile(values, 25, axis=0)
    return np.concatenate((median, spread)).astype(float).tolist()


def chromatic_arrays(roi: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert one ROI to Lab chroma, HSV chroma, and normalized RGB."""
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


def extract_features(roi: np.ndarray) -> dict[str, list[float]]:
    """Describe brick color without using surrounding pixels or absolute position."""
    lab, hsv_chroma, normalized_rgb = chromatic_arrays(roi)
    lab_summary = robust_summary(lab)
    ab_summary = robust_summary(lab[:, 1:])
    hsv_summary = robust_summary(hsv_chroma)
    rgb_summary = robust_summary(normalized_rgb)

    spatial = []
    height, width = roi.shape[:2]
    for row in range(2):
        for column in range(2):
            cell = roi[
                row * height // 2 : (row + 1) * height // 2,
                column * width // 2 : (column + 1) * width // 2,
            ]
            cell_lab, _, cell_rgb = chromatic_arrays(cell)
            spatial.extend(np.median(cell_lab[:, 1:], axis=0).astype(float).tolist())
            spatial.extend(np.median(cell_rgb, axis=0).astype(float).tolist())

    return {
        "lab_median": lab_summary[:3],
        "lab_ab": ab_summary,
        "hsv_hs": hsv_summary,
        "normalized_rgb": rgb_summary,
        "combined_chroma": ab_summary + hsv_summary + rgb_summary,
        "spatial_chroma": ab_summary + hsv_summary + rgb_summary + spatial,
    }


def load_samples() -> list[dict]:
    """Measure every manually verified labeled region."""
    samples = []
    for scene, regions in LABELED_ROIS.items():
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        if image is None:
            raise FileNotFoundError(scene)
        for index, (x, y, width, height, label) in enumerate(regions, start=1):
            roi = image[y : y + height, x : x + width]
            samples.append(
                {
                    "scene": scene,
                    "sample_id": f"brick_{index:03d}",
                    "label": label,
                    "roi_px": {"x": x, "y": y, "width": width, "height": height},
                    "features": extract_features(roi),
                }
            )
    return samples


def standardize(train: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scale features using only the current training folds."""
    center = np.mean(train, axis=0)
    scale = np.std(train, axis=0)
    scale[scale < 1e-6] = 1.0
    return (train - center) / scale, (test - center) / scale


def train_svm(features: np.ndarray, labels: np.ndarray, model: str):
    """Train one deterministic scikit-learn support-vector machine."""
    if model == "linear":
        svm = SVC(kernel="linear", C=1.0, class_weight="balanced")
    else:
        svm = SVC(
            kernel="rbf",
            C=1.0 if model == "rbf_c1" else 10.0,
            gamma=1.0 / features.shape[1],
            class_weight="balanced",
        )
    svm.fit(features, labels)
    return svm


def metrics(labels: np.ndarray, predictions: np.ndarray) -> dict:
    """Calculate overall and class-balanced accuracy."""
    recalls = [float(np.mean(predictions[labels == value] == value)) for value in (0, 1)]
    return {
        "accuracy": round(float(np.mean(labels == predictions)), 3),
        "balanced_accuracy": round(float(np.mean(recalls)), 3),
        "bad_as_bad": int(np.sum((labels == 0) & (predictions == 0))),
        "bad_as_good": int(np.sum((labels == 0) & (predictions == 1))),
        "good_as_bad": int(np.sum((labels == 1) & (predictions == 0))),
        "good_as_good": int(np.sum((labels == 1) & (predictions == 1))),
    }


def cross_validate(samples: list[dict], feature_name: str, model: str) -> dict:
    """Predict each sample with an SVM that never saw its source scene."""
    scenes = np.asarray([sample["scene"] for sample in samples])
    labels = np.asarray([1 if sample["label"] == "good" else 0 for sample in samples])
    features = np.asarray([sample["features"][feature_name] for sample in samples], dtype=np.float32)
    predictions = np.full(len(samples), -1, dtype=np.int32)

    for scene in sorted(set(scenes)):
        test_mask = scenes == scene
        train_mask = ~test_mask
        train_x, test_x = standardize(features[train_mask], features[test_mask])
        svm = train_svm(train_x, labels[train_mask], model)
        predictions[test_mask] = svm.predict(test_x).astype(np.int32)

    return {
        "feature": feature_name,
        "model": model,
        **metrics(labels, predictions),
        "predictions": predictions.tolist(),
    }


def draw_result(samples: list[dict], result: dict) -> None:
    """Draw verified regions and cross-validated predictions."""
    for scene in LABELED_ROIS:
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        for sample_index, sample in enumerate(samples):
            if sample["scene"] != scene:
                continue
            predicted = "good" if result["predictions"][sample_index] == 1 else "bad"
            correct = predicted == sample["label"]
            color = (0, 180, 0) if correct else (0, 0, 255)
            roi = sample["roi_px"]
            cv2.rectangle(
                image,
                (roi["x"], roi["y"]),
                (roi["x"] + roi["width"], roi["y"] + roi["height"]),
                color,
                3,
            )
            cv2.putText(
                image,
                f'{sample["label"]}->{predicted}',
                (roi["x"], roi["y"] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_preview.png"), image)


def main() -> None:
    """Run all feature/model combinations and save the comparison."""
    samples = load_samples()
    feature_names = list(samples[0]["features"])
    results = [
        cross_validate(samples, feature, model)
        for feature in feature_names
        for model in ("linear", "rbf_c1", "rbf_c10")
    ]
    results.sort(
        key=lambda result: (result["balanced_accuracy"], result["accuracy"]),
        reverse=True,
    )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "comparison.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT_ROOT / "labeled_samples.json").write_text(
        json.dumps(samples, indent=2) + "\n", encoding="utf-8"
    )
    draw_result(samples, results[0])

    print("Feature             SVM       bal_acc  accuracy")
    for result in results:
        print(
            f'{result["feature"]:<20} {result["model"]:<8} '
            f'{result["balanced_accuracy"]:>7.3f}  {result["accuracy"]:>8.3f}'
        )
    print(f"\nBest: {results[0]['feature']} + {results[0]['model']}")
    print(
        "Confusion: "
        f"BB={results[0]['bad_as_bad']} BG={results[0]['bad_as_good']} "
        f"GB={results[0]['good_as_bad']} GG={results[0]['good_as_good']}"
    )
    print(f"Outputs: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()

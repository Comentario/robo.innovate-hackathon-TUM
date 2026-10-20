import contextlib
import io
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import perception.brick_detector.background_difference as detector
from validate_local_recovery import calculate_iou, load_brick_boxes
from validate_local_recovery_regression import match_boxes


DATASET_ROOT = (
    PROJECT_ROOT
    / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
    / "Bricks_Detection_Dataset/OBB/dataset_all"
)
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs/alignment_mask_experiment"

SCENES = {
    "02": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_02.png", DATASET_ROOT / "labels/train/c9706302-image_275.txt"),
    "06": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_06.png", DATASET_ROOT / "labels/train/74831553-image_271.txt"),
    "10": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_10.png", DATASET_ROOT / "labels/train/bcff4c6b-image_267.txt"),
    "17": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_17.png", DATASET_ROOT / "labels/train/cc710eab-image_260.txt"),
    "22": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_22.png", DATASET_ROOT / "labels/val/6ba46c8c-image_255.txt"),
    "25": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_25.png", DATASET_ROOT / "labels/train/d7ff9b9a-image_252.txt"),
    "32": (PROJECT_ROOT / "data/images/zenodo_detection/bricks_32.png", DATASET_ROOT / "labels/val/1f38648d-image_245.txt"),
    "37": (DATASET_ROOT / "images/train/2716974e-image_240.png", DATASET_ROOT / "labels/train/2716974e-image_240.txt"),
    "51": (DATASET_ROOT / "images/test/52a7b304-image_226.png", DATASET_ROOT / "labels/test/52a7b304-image_226.txt"),
    "70": (DATASET_ROOT / "images/test/34c1881b-image_205.png", DATASET_ROOT / "labels/test/34c1881b-image_205.txt"),
}


def scaled_border_sizes(image_shape: tuple[int, ...]) -> tuple[int, int, int]:
    image_height, image_width = image_shape[:2]
    top_height = round(
        detector.ALIGNMENT_TOP_HEIGHT
        * image_height
        / detector.ALIGNMENT_REFERENCE_HEIGHT
    )
    bottom_height = round(
        detector.ALIGNMENT_BOTTOM_HEIGHT
        * image_height
        / detector.ALIGNMENT_REFERENCE_HEIGHT
    )
    side_width = round(
        detector.ALIGNMENT_RIGHT_WIDTH
        * image_width
        / detector.ALIGNMENT_REFERENCE_WIDTH
    )
    return top_height, bottom_height, side_width


def build_thin_frame_mask(image_shape: tuple[int, ...]) -> np.ndarray:
    image_height, image_width = image_shape[:2]
    top_height, bottom_height, side_width = scaled_border_sizes(image_shape)
    mask = np.zeros((image_height, image_width), dtype=np.uint8)
    mask[:top_height, :] = 255
    mask[image_height - bottom_height :, :] = 255
    mask[:, :side_width] = 255
    mask[:, image_width - side_width :] = 255
    return mask


def build_no_left_mask(image_shape: tuple[int, ...]) -> np.ndarray:
    image_height, image_width = image_shape[:2]
    top_height, bottom_height, side_width = scaled_border_sizes(image_shape)
    mask = np.zeros((image_height, image_width), dtype=np.uint8)
    mask[:top_height, :] = 255
    mask[image_height - bottom_height :, :] = 255
    mask[:, image_width - side_width :] = 255
    return mask


MASK_BUILDERS = {
    "current": detector.build_alignment_mask,
    "thin_frame": build_thin_frame_mask,
    "no_left": build_no_left_mask,
}


def align_with_mask(
    background: np.ndarray,
    current: np.ndarray,
    mask_builder,
) -> tuple[np.ndarray, float | None, np.ndarray]:
    current_height, current_width = current.shape[:2]
    resized_background = cv2.resize(
        background,
        (current_width, current_height),
        interpolation=cv2.INTER_LINEAR,
    )
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    background_gray = cv2.cvtColor(resized_background, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.GaussianBlur(current_gray, detector.ALIGNMENT_BLUR_SIZE, 0)
    background_gray = cv2.GaussianBlur(
        background_gray,
        detector.ALIGNMENT_BLUR_SIZE,
        0,
    )
    alignment_mask = mask_builder(current.shape)
    warp_matrix = np.eye(2, 3, dtype=np.float32)
    termination_criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        detector.ALIGNMENT_MAX_ITERATIONS,
        detector.ALIGNMENT_EPSILON,
    )

    try:
        correlation, warp_matrix = cv2.findTransformECC(
            current_gray,
            background_gray,
            warp_matrix,
            cv2.MOTION_AFFINE,
            termination_criteria,
            alignment_mask,
            5,
        )
    except cv2.error:
        return resized_background, None, warp_matrix

    aligned_background = cv2.warpAffine(
        resized_background,
        warp_matrix,
        (current_width, current_height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return aligned_background, float(correlation), warp_matrix


def load_prediction_boxes(inventory_path: Path) -> list[tuple[int, int, int, int]]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    return [
        (
            brick["bbox_px"]["x"],
            brick["bbox_px"]["y"],
            brick["bbox_px"]["x"] + brick["bbox_px"]["width"],
            brick["bbox_px"]["y"] + brick["bbox_px"]["height"],
        )
        for brick in inventory["bricks"]
    ]


def calculate_stable_residual(
    current: np.ndarray,
    aligned_background: np.ndarray,
) -> float:
    evaluation_mask = build_no_left_mask(current.shape) > 0
    current_lab = cv2.cvtColor(current, cv2.COLOR_BGR2LAB).astype(np.float32)
    background_lab = cv2.cvtColor(
        aligned_background,
        cv2.COLOR_BGR2LAB,
    ).astype(np.float32)
    difference = np.linalg.norm(current_lab - background_lab, axis=2)
    return float(np.mean(difference[evaluation_mask]))


def read_log_value(log: str, prefix: str) -> str:
    for line in log.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def run_scene(
    scene_name: str,
    image_path: Path,
    label_path: Path,
    mask_name: str,
    mask_builder,
) -> dict:
    scene_directory = OUTPUT_DIRECTORY / f"bricks_{scene_name}" / mask_name
    scene_directory.mkdir(parents=True, exist_ok=True)

    detector.CURRENT_PATH = image_path
    detector.ALIGNED_BACKGROUND_OUTPUT_PATH = scene_directory / "aligned_background.png"
    detector.DIFFERENCE_OUTPUT_PATH = scene_directory / "difference.png"
    detector.MASK_OUTPUT_PATH = scene_directory / "raw_mask.png"
    detector.CLEAN_MASK_OUTPUT_PATH = scene_directory / "clean_mask.png"
    detector.GROUPED_MASK_OUTPUT_PATH = scene_directory / "grouped_mask.png"
    detector.SPLIT_MASK_OUTPUT_PATH = scene_directory / "split_mask.png"
    detector.DETECTIONS_OUTPUT_PATH = scene_directory / "detections_preview.png"
    detector.INVENTORY_OUTPUT_PATH = scene_directory / "inventory.json"
    detector.align_background = lambda background, current: align_with_mask(
        background,
        current,
        mask_builder,
    )

    captured_output = io.StringIO()
    with contextlib.redirect_stdout(captured_output):
        detector.main()
    log = captured_output.getvalue()
    (scene_directory / "run_log.txt").write_text(log, encoding="utf-8")

    current = cv2.imread(str(image_path))
    aligned_background = cv2.imread(
        str(scene_directory / "aligned_background.png")
    )
    predictions = load_prediction_boxes(scene_directory / "inventory.json")
    targets = load_brick_boxes(label_path, current.shape)
    matches = match_boxes(predictions, targets)
    matched_ious = [
        calculate_iou(predictions[index], targets[target_index])
        for index, target_index in matches.items()
    ]
    valid_matches = int(sum(iou >= 0.5 for iou in matched_ious))

    alignment_mask = mask_builder(current.shape)
    cv2.imwrite(str(scene_directory / "alignment_mask.png"), alignment_mask)

    return {
        "scene": scene_name,
        "mask": mask_name,
        "expected_count": len(targets),
        "detected_count": len(predictions),
        "mean_iou": round(float(np.mean(matched_ious)), 3),
        "minimum_iou": round(float(np.min(matched_ious)), 3),
        "iou_50_matches": valid_matches,
        "precision_at_50": round(float(valid_matches / len(predictions)), 3),
        "recall_at_50": round(float(valid_matches / len(targets)), 3),
        "stable_border_residual": round(
            calculate_stable_residual(current, aligned_background),
            3,
        ),
        "ecc_correlation": read_log_value(log, "Alignment ECC correlation:"),
        "previous_row_fallbacks": read_log_value(
            log,
            "Previous-row geometry fallbacks used:",
        ),
        "estimated_rows": [
            line.strip()
            for line in log.splitlines()
            if line.strip().startswith("Row ")
        ],
    }


def main() -> None:
    reports = []
    for scene_name, (image_path, label_path) in SCENES.items():
        for mask_name, mask_builder in MASK_BUILDERS.items():
            report = run_scene(
                scene_name,
                image_path,
                label_path,
                mask_name,
                mask_builder,
            )
            reports.append(report)
            print(
                f"Scene {scene_name} {mask_name}: "
                f"count={report['detected_count']}/{report['expected_count']}, "
                f"mean IoU={report['mean_iou']:.3f}, "
                f"residual={report['stable_border_residual']:.3f}"
            )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIRECTORY / "report.json").open("w", encoding="utf-8") as file:
        json.dump(reports, file, indent=2)
    print(f"Saved report to: {OUTPUT_DIRECTORY / 'report.json'}")


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "local_recovery_experiment"
HIGH_THRESHOLD = 40.0
LOW_THRESHOLDS = (20.0, 25.0, 30.0, 35.0)

SCENES = {
    "32": {
        "image": PROJECT_ROOT / "data/images/zenodo_detection/bricks_32.png",
        "aligned_background": PROJECT_ROOT
        / "outputs/integration_validation/bricks_32/aligned_background.png",
        "labels": PROJECT_ROOT
        / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
        / "Bricks_Detection_Dataset/OBB/dataset_all/labels/val"
        / "1f38648d-image_245.txt",
        "observed_bbox": (517, 507, 605, 545),
        "search_bbox": (457, 507, 605, 545),
    },
    "37": {
        "image": PROJECT_ROOT
        / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
        / "Bricks_Detection_Dataset/OBB/dataset_all/images/train"
        / "2716974e-image_240.png",
        "aligned_background": PROJECT_ROOT
        / "outputs/integration_validation/bricks_37/aligned_background.png",
        "labels": PROJECT_ROOT
        / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
        / "Bricks_Detection_Dataset/OBB/dataset_all/labels/train"
        / "2716974e-image_240.txt",
        "observed_bbox": (470, 531, 564, 551),
        "search_bbox": (470, 513, 610, 551),
    },
}


def calculate_iou(box_a: tuple, box_b: tuple) -> float:
    intersection_width = max(
        0.0,
        min(box_a[2], box_b[2]) - max(box_a[0], box_b[0]),
    )
    intersection_height = max(
        0.0,
        min(box_a[3], box_b[3]) - max(box_a[1], box_b[1]),
    )
    intersection = intersection_width * intersection_height
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return intersection / (area_a + area_b - intersection)


def load_brick_boxes(label_path: Path, image_shape: tuple[int, ...]) -> list[tuple]:
    image_height, image_width = image_shape[:2]
    boxes = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        values = line.split()
        if values[0] != "2":
            continue
        coordinates = list(map(float, values[1:]))
        points = np.array(
            [
                (
                    coordinates[index] * image_width,
                    coordinates[index + 1] * image_height,
                )
                for index in range(0, 8, 2)
            ]
        )
        minimum = points.min(axis=0)
        maximum = points.max(axis=0)
        boxes.append((*minimum, *maximum))
    return boxes


def recover_connected_low_threshold(
    difference: np.ndarray,
    observed_bbox: tuple[int, int, int, int],
    search_bbox: tuple[int, int, int, int],
    low_threshold: float,
) -> tuple[np.ndarray, tuple[int, int, int, int] | None]:
    search_x0, search_y0, search_x1, search_y1 = search_bbox
    observed_x0, observed_y0, observed_x1, observed_y1 = observed_bbox
    local_difference = difference[search_y0:search_y1, search_x0:search_x1]
    low_mask = (local_difference > low_threshold).astype(np.uint8)

    seed_mask = np.zeros_like(low_mask)
    seed_x0 = max(0, observed_x0 - search_x0)
    seed_y0 = max(0, observed_y0 - search_y0)
    seed_x1 = min(low_mask.shape[1], observed_x1 - search_x0)
    seed_y1 = min(low_mask.shape[0], observed_y1 - search_y0)
    seed_mask[seed_y0:seed_y1, seed_x0:seed_x1] = (
        local_difference[seed_y0:seed_y1, seed_x0:seed_x1] > HIGH_THRESHOLD
    )

    component_count, component_labels, _, _ = cv2.connectedComponentsWithStats(
        low_mask,
        connectivity=8,
    )
    if component_count == 1:
        return np.zeros_like(low_mask), None

    connected_labels = np.unique(component_labels[seed_mask > 0])
    connected_labels = connected_labels[connected_labels > 0]
    recovered_mask = np.isin(component_labels, connected_labels)
    foreground_y, foreground_x = np.nonzero(recovered_mask)
    if foreground_x.size == 0:
        return recovered_mask.astype(np.uint8), None

    recovered_bbox = (
        search_x0 + int(foreground_x.min()),
        search_y0 + int(foreground_y.min()),
        search_x0 + int(foreground_x.max()) + 1,
        search_y0 + int(foreground_y.max()) + 1,
    )
    return recovered_mask.astype(np.uint8), recovered_bbox


def draw_box(image: np.ndarray, box: tuple, color: tuple) -> None:
    x0, y0, x1, y1 = map(round, box)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, 2)


def draw_legend(image: np.ndarray, low_threshold: float) -> None:
    entries = (
        ("Search region", (0, 255, 255)),
        ("Observed bbox", (0, 0, 255)),
        ("Recovered bbox", (255, 255, 0)),
        ("Ground truth", (255, 255, 255)),
    )
    cv2.rectangle(image, (8, 8), (190, 106), (30, 30, 30), -1)
    for index, (label, color) in enumerate(entries):
        cv2.putText(
            image,
            label,
            (16, 28 + 20 * index),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        image,
        f"Low threshold: {low_threshold:.0f}",
        (16, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )


def validate_scene(scene_name: str, scene: dict) -> None:
    image = cv2.imread(str(scene["image"]))
    aligned_background = cv2.imread(str(scene["aligned_background"]))
    if image is None or aligned_background is None:
        raise FileNotFoundError(f"Could not load scene {scene_name}")

    image_lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    background_lab = cv2.cvtColor(
        aligned_background,
        cv2.COLOR_BGR2LAB,
    ).astype(np.float32)
    difference = np.linalg.norm(image_lab - background_lab, axis=2)
    ground_truth_boxes = load_brick_boxes(scene["labels"], image.shape)
    target_box = max(
        ground_truth_boxes,
        key=lambda box: calculate_iou(scene["observed_bbox"], box),
    )

    output_directory = OUTPUT_DIRECTORY / f"bricks_{scene_name}"
    output_directory.mkdir(parents=True, exist_ok=True)
    results = []
    for low_threshold in LOW_THRESHOLDS:
        recovered_mask, recovered_bbox = recover_connected_low_threshold(
            difference,
            scene["observed_bbox"],
            scene["search_bbox"],
            low_threshold,
        )
        preview = image.copy()
        search_x0, search_y0, search_x1, search_y1 = scene["search_bbox"]
        color_layer = np.zeros_like(image)
        local_layer = color_layer[search_y0:search_y1, search_x0:search_x1]
        local_layer[recovered_mask > 0] = (0, 180, 0)
        preview = cv2.addWeighted(preview, 0.75, color_layer, 0.25, 0)

        draw_box(preview, scene["search_bbox"], (0, 255, 255))
        draw_box(preview, scene["observed_bbox"], (0, 0, 255))
        draw_box(preview, target_box, (255, 255, 255))
        recovered_iou = None
        if recovered_bbox is not None:
            draw_box(preview, recovered_bbox, (255, 255, 0))
            recovered_iou = calculate_iou(recovered_bbox, target_box)
        draw_legend(preview, low_threshold)

        cv2.imwrite(
            str(output_directory / f"threshold_{round(low_threshold):02d}.png"),
            preview,
        )
        results.append(
            {
                "low_threshold": low_threshold,
                "recovered_bbox": recovered_bbox,
                "recovered_iou": (
                    None if recovered_iou is None else round(recovered_iou, 3)
                ),
                "recovered_pixels": int(np.count_nonzero(recovered_mask)),
            }
        )

    report = {
        "scene": scene_name,
        "observed_bbox": scene["observed_bbox"],
        "search_bbox": scene["search_bbox"],
        "ground_truth_bbox": [round(value, 2) for value in target_box],
        "observed_iou": round(
            calculate_iou(scene["observed_bbox"], target_box),
            3,
        ),
        "results": results,
    }
    with (output_directory / "report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    best_result = max(
        (result for result in results if result["recovered_iou"] is not None),
        key=lambda result: result["recovered_iou"],
    )
    print(
        f"Scene {scene_name}: observed_iou={report['observed_iou']:.3f}, "
        f"best_threshold={best_result['low_threshold']:.0f}, "
        f"best_iou={best_result['recovered_iou']:.3f}"
    )


def main() -> None:
    for scene_name, scene in SCENES.items():
        validate_scene(scene_name, scene)
    print(f"Saved local recovery experiment to: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

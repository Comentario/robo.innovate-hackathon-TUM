import json
from pathlib import Path

import cv2
import numpy as np

from validate_local_recovery import calculate_iou, load_brick_boxes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENE_DIRECTORY = PROJECT_ROOT / "outputs/new_scene_validation/bricks_51"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs/gradient_cut_experiment/bricks_51"
IMAGE_PATH = (
    PROJECT_ROOT
    / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
    / "Bricks_Detection_Dataset/OBB/dataset_all/images/test"
    / "52a7b304-image_226.png"
)
LABEL_PATH = (
    PROJECT_ROOT
    / "2026-03-17_CIDET_VO3_BricksDetectionDataset"
    / "Bricks_Detection_Dataset/OBB/dataset_all/labels/test"
    / "52a7b304-image_226.txt"
)

# These bounds come from the current detector output. They define local searches,
# not fixed brick dimensions.
CURRENT_ROW_4_X = [327, 470, 605, 759]
CURRENT_ROW_5_X = [346, 488, 610, 756]
CURRENT_HORIZONTAL_Y = [483, 520]
X_SEARCH_RADIUS = 25
Y_SEARCH_RADIUS = 15


def load_predictions(inventory_path: Path) -> dict[str, tuple[int, int, int, int]]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    predictions = {}
    for brick in inventory["bricks"]:
        box = brick["bbox_px"]
        predictions[brick["id"]] = (
            box["x"],
            box["y"],
            box["x"] + box["width"],
            box["y"] + box["height"],
        )
    return predictions


def strongest_x_edge(
    sobel_x: np.ndarray,
    current_x: int,
    y_start: int,
    y_end: int,
    radius: int = X_SEARCH_RADIUS,
) -> tuple[int, list[float]]:
    search_start = max(0, current_x - radius)
    search_end = min(sobel_x.shape[1], current_x + radius + 1)
    profile = sobel_x[y_start:y_end, search_start:search_end].mean(axis=0)
    best_x = search_start + int(np.argmax(profile))
    return best_x, profile.tolist()


def strongest_y_edge(
    sobel_y: np.ndarray,
    current_y: int,
    x_start: int,
    x_end: int,
    radius: int = Y_SEARCH_RADIUS,
) -> tuple[int, list[float]]:
    search_start = max(0, current_y - radius)
    search_end = min(sobel_y.shape[0], current_y + radius + 1)
    profile = sobel_y[search_start:search_end, x_start:x_end].mean(axis=1)
    best_y = search_start + int(np.argmax(profile))
    return best_y, profile.tolist()


def match_targets(
    predictions: dict[str, tuple[int, int, int, int]],
    targets: list[tuple[float, float, float, float]],
) -> dict[str, tuple[float, float, float, float]]:
    candidates = []
    for brick_id, prediction in predictions.items():
        for target_index, target in enumerate(targets):
            candidates.append(
                (calculate_iou(prediction, target), brick_id, target_index)
            )

    matches = {}
    used_targets = set()
    for _, brick_id, target_index in sorted(candidates, reverse=True):
        if brick_id in matches or target_index in used_targets:
            continue
        matches[brick_id] = targets[target_index]
        used_targets.add(target_index)
    return matches


def draw_box(
    image: np.ndarray,
    box: tuple[float, float, float, float],
    color: tuple[int, int, int],
    label: str,
) -> None:
    x0, y0, x1, y1 = map(round, box)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, 2)
    cv2.putText(
        image,
        label,
        (x0 + 2, max(18, y0 - 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        color,
        1,
        cv2.LINE_AA,
    )


def build_cut_overlay(
    image: np.ndarray,
    refined_row_4_x: list[int],
    refined_row_5_x: list[int],
    upper_boundaries: list[int],
    lower_boundaries: list[int],
) -> np.ndarray:
    preview = image.copy()

    for y in CURRENT_HORIZONTAL_Y:
        cv2.line(preview, (305, y), (780, y), (0, 0, 255), 1)

    for index, y in enumerate(upper_boundaries):
        cv2.line(
            preview,
            (refined_row_4_x[index], y),
            (refined_row_4_x[index + 1], y),
            (255, 255, 0),
            2,
        )
    for index, y in enumerate(lower_boundaries):
        cv2.line(
            preview,
            (refined_row_5_x[index], y),
            (refined_row_5_x[index + 1], y),
            (255, 255, 0),
            2,
        )

    for x in CURRENT_ROW_4_X:
        cv2.line(preview, (x, 468), (x, 525), (0, 0, 255), 1)
    for x in CURRENT_ROW_5_X:
        cv2.line(preview, (x, 505), (x, 562), (0, 0, 255), 1)
    for x in refined_row_4_x:
        cv2.line(preview, (x, 468), (x, 525), (255, 255, 0), 2)
    for x in refined_row_5_x:
        cv2.line(preview, (x, 505), (x, 562), (255, 255, 0), 2)

    cv2.rectangle(preview, (8, 8), (285, 68), (30, 30, 30), -1)
    cv2.putText(
        preview,
        "Red: current detector cuts",
        (16, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 0, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        "Cyan: local Sobel refinements",
        (16, 54),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 0),
        1,
        cv2.LINE_AA,
    )
    return preview


def build_bbox_comparison(
    image: np.ndarray,
    predictions: dict[str, tuple[int, int, int, int]],
    refined: dict[str, tuple[int, int, int, int]],
    targets: dict[str, tuple[float, float, float, float]],
) -> np.ndarray:
    current_preview = image.copy()
    refined_preview = image.copy()
    for brick_id in refined:
        draw_box(current_preview, predictions[brick_id], (0, 0, 255), brick_id)
        draw_box(current_preview, targets[brick_id], (255, 255, 255), "GT")
        draw_box(refined_preview, refined[brick_id], (255, 255, 0), brick_id)
        draw_box(refined_preview, targets[brick_id], (255, 255, 255), "GT")

    cv2.rectangle(current_preview, (0, 0), (250, 28), (30, 30, 30), -1)
    cv2.putText(
        current_preview,
        "Current bboxes (red) + GT (white)",
        (8, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.rectangle(refined_preview, (0, 0), (265, 28), (30, 30, 30), -1)
    cv2.putText(
        refined_preview,
        "Refined bboxes (cyan) + GT (white)",
        (8, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return np.hstack((current_preview, refined_preview))


def normalize_gradient(gradient: np.ndarray) -> np.ndarray:
    clipped = np.clip(gradient, 0, np.percentile(gradient, 99))
    normalized = cv2.normalize(clipped, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.applyColorMap(normalized.astype(np.uint8), cv2.COLORMAP_TURBO)


def main() -> None:
    image = cv2.imread(str(IMAGE_PATH))
    if image is None:
        raise FileNotFoundError(f"Could not load image: {IMAGE_PATH}")

    predictions = load_predictions(SCENE_DIRECTORY / "inventory.json")
    target_boxes = load_brick_boxes(LABEL_PATH, image.shape)
    targets = match_targets(predictions, target_boxes)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    sobel_x = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3))
    sobel_y = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3))

    refined_row_4_x = [
        strongest_x_edge(sobel_x, x, 468, 525)[0]
        for x in CURRENT_ROW_4_X
    ]
    refined_row_5_x = [
        strongest_x_edge(sobel_x, x, 505, 562, radius=35)[0]
        for x in CURRENT_ROW_5_X
    ]

    upper_boundaries = [
        strongest_y_edge(sobel_y, 483, x0, x1)[0]
        for x0, x1 in zip(refined_row_4_x[:-1], refined_row_4_x[1:])
    ]
    lower_boundaries = [
        strongest_y_edge(sobel_y, 520, x0, x1)[0]
        for x0, x1 in zip(refined_row_5_x[:-1], refined_row_5_x[1:])
    ]

    refined = {
        "brick_046": (
            refined_row_4_x[0], upper_boundaries[0],
            refined_row_4_x[1], lower_boundaries[0],
        ),
        "brick_047": (
            refined_row_4_x[1], upper_boundaries[1],
            refined_row_4_x[2], lower_boundaries[1],
        ),
        "brick_048": (
            refined_row_4_x[2], upper_boundaries[2],
            refined_row_4_x[3], lower_boundaries[2],
        ),
        "brick_049": (
            refined_row_5_x[0], lower_boundaries[0],
            refined_row_5_x[1], predictions["brick_049"][3],
        ),
        "brick_050": (
            refined_row_5_x[1], lower_boundaries[1],
            refined_row_5_x[2], predictions["brick_050"][3],
        ),
        "brick_051": (
            refined_row_5_x[2], lower_boundaries[2],
            refined_row_5_x[3], predictions["brick_051"][3],
        ),
    }

    comparisons = []
    for brick_id, refined_box in refined.items():
        baseline_iou = calculate_iou(predictions[brick_id], targets[brick_id])
        refined_iou = calculate_iou(refined_box, targets[brick_id])
        comparisons.append(
            {
                "brick_id": brick_id,
                "current_bbox": predictions[brick_id],
                "refined_bbox": refined_box,
                "ground_truth_bbox": [round(value, 2) for value in targets[brick_id]],
                "current_iou": round(baseline_iou, 3),
                "refined_iou": round(refined_iou, 3),
            }
        )

    report = {
        "scene": "bricks_51",
        "method": "local Sobel cut refinement",
        "detector_modified": False,
        "current_row_4_x": CURRENT_ROW_4_X,
        "refined_row_4_x": refined_row_4_x,
        "current_row_5_x": CURRENT_ROW_5_X,
        "refined_row_5_x": refined_row_5_x,
        "current_horizontal_y": CURRENT_HORIZONTAL_Y,
        "refined_upper_boundary_by_segment": upper_boundaries,
        "refined_lower_boundary_by_segment": lower_boundaries,
        "targeted_bbox_comparison": comparisons,
        "targeted_mean_iou": {
            "current": round(float(np.mean([item["current_iou"] for item in comparisons])), 3),
            "refined": round(float(np.mean([item["refined_iou"] for item in comparisons])), 3),
        },
    }

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUTPUT_DIRECTORY / "sobel_x.png"), normalize_gradient(sobel_x))
    cv2.imwrite(str(OUTPUT_DIRECTORY / "sobel_y.png"), normalize_gradient(sobel_y))
    cv2.imwrite(
        str(OUTPUT_DIRECTORY / "current_vs_refined_cuts.png"),
        build_cut_overlay(
            image,
            refined_row_4_x,
            refined_row_5_x,
            upper_boundaries,
            lower_boundaries,
        ),
    )
    cv2.imwrite(
        str(OUTPUT_DIRECTORY / "current_vs_refined_bboxes.png"),
        build_bbox_comparison(image, predictions, refined, targets),
    )
    with (OUTPUT_DIRECTORY / "report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(f"Row 4 X cuts: {CURRENT_ROW_4_X} -> {refined_row_4_x}")
    print(f"Row 5 X cuts: {CURRENT_ROW_5_X} -> {refined_row_5_x}")
    print(f"Upper Y boundary by segment: {upper_boundaries}")
    print(f"Lower Y boundary by segment: {lower_boundaries}")
    print(
        "Targeted mean IoU: "
        f"{report['targeted_mean_iou']['current']:.3f} -> "
        f"{report['targeted_mean_iou']['refined']:.3f}"
    )
    print(f"Saved experiment to: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

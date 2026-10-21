import json
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIRECTORY = PROJECT_ROOT / "data" / "images" / "color_estimation"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_lab_clusters"
SCENE_NAMES = (
    "wall_exposure_dark",
    "wall_mixed_colors",
    "wall_stylized",
    "wall_textured",
)
CLUSTER_COUNT = 5
TITLE_HEIGHT = 42
KMEANS_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    50,
    0.2,
)


def load_image(image_path: Path) -> np.ndarray:
    """Load one diagnostic wall image."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return image


def cluster_lab_image(
    image: np.ndarray,
    cluster_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Group image pixels in Lab and order clusters from dark to light."""
    lab_image = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    pixels = lab_image.reshape(-1, 3).astype(np.float32)

    cv2.setRNGSeed(42)
    _, labels, centers = cv2.kmeans(
        pixels,
        cluster_count,
        None,
        KMEANS_CRITERIA,
        5,
        cv2.KMEANS_PP_CENTERS,
    )

    lightness_order = np.argsort(centers[:, 0])
    ordered_centers = centers[lightness_order]
    label_mapping = np.empty(cluster_count, dtype=np.int32)
    label_mapping[lightness_order] = np.arange(cluster_count)
    ordered_labels = label_mapping[labels.ravel()].reshape(lab_image.shape[:2])
    return ordered_labels, ordered_centers


def reconstruct_cluster_map(
    labels: np.ndarray,
    centers: np.ndarray,
) -> np.ndarray:
    """Replace each pixel with its cluster-center color."""
    lab_map = centers[labels].astype(np.uint8)
    return cv2.cvtColor(lab_map, cv2.COLOR_LAB2BGR)


def add_title(image: np.ndarray, title: str) -> np.ndarray:
    """Add a white title strip above one image panel."""
    if len(image.shape) == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    panel = cv2.copyMakeBorder(
        image,
        TITLE_HEIGHT,
        0,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    cv2.putText(
        panel,
        title,
        (8, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return panel


def build_mask_panel(
    labels: np.ndarray,
    centers: np.ndarray,
) -> tuple[np.ndarray, list[dict]]:
    """Build a two-row panel and statistics for every Lab cluster."""
    panels = []
    summaries = []
    total_pixels = labels.size

    for cluster_index, center in enumerate(centers):
        mask = np.where(labels == cluster_index, 255, 0).astype(np.uint8)
        pixel_count = int(np.count_nonzero(mask))
        percentage = 100.0 * pixel_count / total_pixels
        l_value, a_value, b_value = center
        title = (
            f"C{cluster_index}: Lab "
            f"({l_value:.0f}, {a_value:.0f}, {b_value:.0f}) "
            f"{percentage:.1f}%"
        )
        panels.append(add_title(mask, title))
        summaries.append(
            {
                "cluster": cluster_index,
                "center_lab_opencv": {
                    "l": round(float(l_value), 2),
                    "a": round(float(a_value), 2),
                    "b": round(float(b_value), 2),
                },
                "pixel_count": pixel_count,
                "percentage": round(percentage, 2),
            }
        )

    blank_panel = np.full_like(panels[0], 255)
    top_row = cv2.hconcat(panels[:3])
    bottom_row = cv2.hconcat([panels[3], panels[4], blank_panel])
    return cv2.vconcat([top_row, bottom_row]), summaries


def process_scene(scene_name: str) -> dict:
    """Cluster one wall scene and save all diagnostic artifacts."""
    image_path = IMAGE_DIRECTORY / f"{scene_name}.jpg"
    image = load_image(image_path)
    labels, centers = cluster_lab_image(image, CLUSTER_COUNT)
    cluster_map = reconstruct_cluster_map(labels, centers)
    mask_panel, summaries = build_mask_panel(labels, centers)

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(scene_directory / "cluster_map.png"), cluster_map)
    cv2.imwrite(str(scene_directory / "cluster_masks.png"), mask_panel)
    (scene_directory / "cluster_summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "scene": scene_name,
        "centers": summaries,
        "output_directory": str(scene_directory),
    }


def main() -> None:
    for scene_name in SCENE_NAMES:
        result = process_scene(scene_name)
        print(f'\n{result["scene"]}')
        for item in result["centers"]:
            center = item["center_lab_opencv"]
            print(
                f'  C{item["cluster"]}: '
                f'L={center["l"]:.1f}, '
                f'a={center["a"]:.1f}, '
                f'b={center["b"]:.1f}, '
                f'{item["percentage"]:.1f}%'
            )

    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

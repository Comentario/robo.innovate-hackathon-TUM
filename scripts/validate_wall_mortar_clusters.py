import json
import sys
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from perception.brick_detector.experimental_wall_detector import (
    MORPH_KERNEL_SIZE,
    detect_brick_components,
    draw_detections,
)
from validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    IMAGE_DIRECTORY,
    cluster_lab_image,
    load_image,
)


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_mortar_clusters"
TITLE_HEIGHT = 42
MORTAR_VARIANTS = {
    "wall_exposure_dark": {"c3_c4": (3, 4)},
    "wall_mixed_colors": {"c4": (4,), "c3_c4": (3, 4)},
    "wall_stylized": {"c0": (0,)},
    "wall_textured": {"c4": (4,), "c3_c4": (3, 4)},
}


def build_masks(
    labels: np.ndarray,
    mortar_clusters: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """Connect the mortar network before building its brick complement."""
    mortar_mask = np.where(
        np.isin(labels, mortar_clusters),
        255,
        0,
    ).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_KERNEL_SIZE)
    mortar_mask = cv2.morphologyEx(mortar_mask, cv2.MORPH_CLOSE, kernel)
    mortar_mask = cv2.dilate(mortar_mask, kernel, iterations=1)
    brick_mask = cv2.bitwise_not(mortar_mask)
    brick_mask = cv2.morphologyEx(brick_mask, cv2.MORPH_OPEN, kernel)
    return mortar_mask, brick_mask


def add_title(image: np.ndarray, title: str) -> np.ndarray:
    """Add a title above one diagnostic panel."""
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


def process_variant(
    image: np.ndarray,
    labels: np.ndarray,
    scene_name: str,
    variant_name: str,
    mortar_clusters: tuple[int, ...],
) -> dict:
    """Generate masks and boxes for one manual mortar-cluster choice."""
    mortar_mask, brick_mask = build_masks(labels, mortar_clusters)
    detections = detect_brick_components(brick_mask)
    preview = draw_detections(image, detections)
    cluster_text = "+".join(f"C{value}" for value in mortar_clusters)
    comparison = cv2.hconcat(
        [
            add_title(mortar_mask, f"Mortar: {cluster_text}"),
            add_title(brick_mask, "Inverted brick mask"),
            add_title(preview, f"Detections: {len(detections)}"),
        ]
    )

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(
        str(scene_directory / f"{variant_name}_comparison.png"),
        comparison,
    )
    (scene_directory / f"{variant_name}_detections.json").write_text(
        json.dumps(detections, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "scene": scene_name,
        "variant": variant_name,
        "mortar_clusters": list(mortar_clusters),
        "detections": len(detections),
    }


def main() -> None:
    print("Scene                     mortar      detections")
    for scene_name, variants in MORTAR_VARIANTS.items():
        image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
        labels, _ = cluster_lab_image(image, CLUSTER_COUNT)

        for variant_name, mortar_clusters in variants.items():
            result = process_variant(
                image,
                labels,
                scene_name,
                variant_name,
                mortar_clusters,
            )
            cluster_text = "+".join(
                f"C{value}" for value in result["mortar_clusters"]
            )
            print(
                f'{result["scene"]:<25} '
                f'{cluster_text:<10} '
                f'{result["detections"]:>10}'
            )

    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

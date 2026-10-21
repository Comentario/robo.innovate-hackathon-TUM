import numpy as np

from perception.brick_detector.background_difference import detect_pallet_bricks
from perception.brick_detector.experimental_wall_detector import detect_wall_bricks
from perception.color_estimator.measure_lab import (
    INNER_MARGIN_RATIO,
    build_relative_lab_classification,
    measure_brick_colors,
    select_color_eligible_bricks,
)
from perception.inventory_manager.inventory import (
    build_color_inventory,
    build_partial_inventory,
)


def build_perception_result(
    image: np.ndarray,
    image_id: str,
    detections: list[dict],
    detector_diagnostics: dict,
    detector_mode: str,
    source_detector: str,
) -> tuple[dict, dict]:
    """Build the shared color inventory after either detector finishes."""
    partial_inventory = build_partial_inventory(
        image_id=image_id,
        image_shape=image.shape,
        detections=detections,
        source_detector=source_detector,
    )
    eligible_bricks = select_color_eligible_bricks(partial_inventory["bricks"])
    measurements = measure_brick_colors(
        image,
        eligible_bricks,
        INNER_MARGIN_RATIO,
    )
    classification = build_relative_lab_classification(measurements)
    inventory = build_color_inventory(partial_inventory, classification)
    diagnostics = {
        "detector_mode": detector_mode,
        "detector": detector_diagnostics,
        "color_measurements": measurements,
        "color_classification": classification,
    }
    return inventory, diagnostics


def run_pallet_perception(
    current_image: np.ndarray,
    background_image: np.ndarray,
    image_id: str,
) -> tuple[dict, dict]:
    """Run pallet detection and relative color estimation entirely in memory."""
    detections, detector_diagnostics = detect_pallet_bricks(
        current_image,
        background_image,
    )
    return build_perception_result(
        image=current_image,
        image_id=image_id,
        detections=detections,
        detector_diagnostics=detector_diagnostics,
        detector_mode="pallet",
        source_detector="pallet_background_difference_v0.2",
    )


def run_wall_perception(
    current_image: np.ndarray,
    image_id: str,
) -> tuple[dict, dict]:
    """Run wall detection and relative color estimation entirely in memory."""
    detections, detector_diagnostics = detect_wall_bricks(current_image)
    return build_perception_result(
        image=current_image,
        image_id=image_id,
        detections=detections,
        detector_diagnostics=detector_diagnostics,
        detector_mode="wall",
        source_detector="wall_lab_kmeans_v0.1",
    )


def run_perception(
    current_image: np.ndarray,
    image_id: str,
    detector_mode: str,
    background_image: np.ndarray | None = None,
) -> tuple[dict, dict]:
    """Select a detector and return one shared color-inventory contract."""
    if detector_mode == "pallet":
        if background_image is None:
            raise ValueError("Pallet detector mode requires a background image")
        return run_pallet_perception(
            current_image,
            background_image,
            image_id,
        )
    if detector_mode == "wall":
        return run_wall_perception(current_image, image_id)
    raise ValueError(
        f"Unknown detector mode: {detector_mode!r}. Expected 'pallet' or 'wall'."
    )

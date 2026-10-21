import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from perception.brick_detector.experimental_wall_detector import (
    MAX_ASPECT_RATIO,
    MIN_AREA_RATIO,
    MIN_ASPECT_RATIO,
    MIN_FILL_RATIO,
    MIN_HEIGHT_RATIO,
    MIN_WIDTH_RATIO,
)
from validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    IMAGE_DIRECTORY,
    cluster_lab_image,
    load_image,
)
from validate_wall_mortar_clusters import build_masks


OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "wall_component_diagnostics"
SCENE_VARIANTS = {
    "wall_exposure_dark": {"c3_c4": (3, 4)},
    "wall_mixed_colors": {"c4": (4,)},
    "wall_stylized": {"c0": (0,)},
    "wall_textured": {"c4": (4,), "c3_c4": (3, 4)},
}
LARGE_SIZE_RATIO = 1.8
VISUAL_MIN_AREA_FACTOR = 0.1
STATUS_COLORS = {
    "accepted": (0, 255, 0),
    "possible_merge": (0, 255, 255),
    "size": (0, 0, 255),
    "aspect": (0, 165, 255),
    "fill": (255, 0, 255),
}


def classify_components(mask: np.ndarray) -> tuple[list[dict], dict]:
    """Apply the current filters while preserving every rejection reason."""
    image_height, image_width = mask.shape
    minimum_area = image_height * image_width * MIN_AREA_RATIO
    minimum_width = image_width * MIN_WIDTH_RATIO
    minimum_height = image_height * MIN_HEIGHT_RATIO
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask,
        connectivity=8,
    )
    components = []

    for label in range(1, count):
        x, y, width, height, area = stats[label]
        aspect_ratio = width / height
        fill_ratio = area / (width * height)
        reasons = []

        if area < minimum_area:
            reasons.append("area")
        if width < minimum_width:
            reasons.append("width")
        if height < minimum_height:
            reasons.append("height")
        if not MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO:
            reasons.append("aspect")
        if fill_ratio < MIN_FILL_RATIO:
            reasons.append("fill")

        components.append(
            {
                "label": label,
                "bbox_px": {
                    "x": int(x),
                    "y": int(y),
                    "width": int(width),
                    "height": int(height),
                },
                "area_px": int(area),
                "aspect_ratio": round(float(aspect_ratio), 3),
                "fill_ratio": round(float(fill_ratio), 3),
                "reasons": reasons,
            }
        )

    accepted = [item for item in components if not item["reasons"]]
    median_width = float(
        np.median([item["bbox_px"]["width"] for item in accepted])
    )
    median_height = float(
        np.median([item["bbox_px"]["height"] for item in accepted])
    )

    for item in accepted:
        bbox = item["bbox_px"]
        item["possible_merge"] = (
            bbox["width"] > LARGE_SIZE_RATIO * median_width
            or bbox["height"] > LARGE_SIZE_RATIO * median_height
        )

    thresholds = {
        "minimum_area": round(float(minimum_area), 2),
        "minimum_width": round(float(minimum_width), 2),
        "minimum_height": round(float(minimum_height), 2),
        "median_accepted_width": round(median_width, 2),
        "median_accepted_height": round(median_height, 2),
    }
    return components, {"labels": labels, "thresholds": thresholds}


def component_status(component: dict) -> str:
    """Reduce detailed reasons to one color category for the preview."""
    if not component["reasons"]:
        if component.get("possible_merge", False):
            return "possible_merge"
        return "accepted"
    if any(reason in component["reasons"] for reason in ("area", "width", "height")):
        return "size"
    if "aspect" in component["reasons"]:
        return "aspect"
    return "fill"


def draw_diagnostics(
    image: np.ndarray,
    components: list[dict],
    minimum_area: float,
) -> np.ndarray:
    """Draw accepted and rejected component boxes using status colors."""
    preview = image.copy()
    visual_minimum_area = minimum_area * VISUAL_MIN_AREA_FACTOR

    for component in components:
        if component["area_px"] < visual_minimum_area:
            continue
        bbox = component["bbox_px"]
        status = component_status(component)
        color = STATUS_COLORS[status]
        cv2.rectangle(
            preview,
            (bbox["x"], bbox["y"]),
            (
                bbox["x"] + bbox["width"],
                bbox["y"] + bbox["height"],
            ),
            color,
            2,
        )

    legend = [
        ("accepted", "accepted"),
        ("possible_merge", "possible merge"),
        ("size", "rejected: size"),
        ("aspect", "rejected: aspect"),
        ("fill", "rejected: fill"),
    ]
    legend_height = 28 * len(legend) + 12
    preview = cv2.copyMakeBorder(
        preview,
        legend_height,
        0,
        0,
        0,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    for index, (status, text) in enumerate(legend):
        y = 24 + index * 28
        cv2.rectangle(preview, (10, y - 12), (30, y + 4), STATUS_COLORS[status], -1)
        cv2.putText(
            preview,
            text,
            (40, y + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return preview


def summarize_components(components: list[dict]) -> dict:
    """Count component statuses and detailed rejection reasons."""
    status_counts = Counter(component_status(item) for item in components)
    reason_counts = Counter(
        reason
        for item in components
        for reason in item["reasons"]
    )
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
    }


def process_variant(
    image: np.ndarray,
    labels: np.ndarray,
    scene_name: str,
    variant_name: str,
    mortar_clusters: tuple[int, ...],
) -> dict:
    """Diagnose one manually selected mortar-cluster variant."""
    _, brick_mask = build_masks(labels, mortar_clusters)
    components, details = classify_components(brick_mask)
    summary = summarize_components(components)
    preview = draw_diagnostics(
        image,
        components,
        details["thresholds"]["minimum_area"],
    )

    scene_directory = OUTPUT_DIRECTORY / scene_name
    scene_directory.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(
        str(scene_directory / f"{variant_name}_diagnostics.png"),
        preview,
    )
    report = {
        "scene": scene_name,
        "variant": variant_name,
        "mortar_clusters": list(mortar_clusters),
        "thresholds": details["thresholds"],
        **summary,
        "components": components,
    }
    (scene_directory / f"{variant_name}_diagnostics.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    print("Scene                     variant   accepted   merges   rejected")
    for scene_name, variants in SCENE_VARIANTS.items():
        image = load_image(IMAGE_DIRECTORY / f"{scene_name}.jpg")
        labels, _ = cluster_lab_image(image, CLUSTER_COUNT)

        for variant_name, mortar_clusters in variants.items():
            report = process_variant(
                image,
                labels,
                scene_name,
                variant_name,
                mortar_clusters,
            )
            counts = report["status_counts"]
            accepted = counts.get("accepted", 0)
            merges = counts.get("possible_merge", 0)
            rejected = sum(
                value
                for key, value in counts.items()
                if key not in ("accepted", "possible_merge")
            )
            print(
                f"{scene_name:<25} "
                f"{variant_name:<9} "
                f"{accepted:>8} "
                f"{merges:>8} "
                f"{rejected:>10}"
            )

    print(f"\nOutputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()

import json
from copy import deepcopy
from pathlib import Path


def build_partial_inventory(
    image_id: str,
    image_shape: tuple[int, ...],
    detections: list[dict],
    source_detector: str | None = None,
) -> dict:
    """Normalize detector results into the shared partial inventory contract."""
    image_height, image_width = image_shape[:2]
    bricks = []
    for detection in detections:
        brick = deepcopy(detection)
        bbox = brick["bbox_px"]
        brick.setdefault(
            "center_px",
            {
                "x": round(bbox["x"] + bbox["width"] / 2.0, 2),
                "y": round(bbox["y"] + bbox["height"] / 2.0, 2),
            },
        )
        brick.setdefault("eligible_for_color", True)
        brick.setdefault("color_group", "unknown")
        brick.setdefault("color_score", 0.0)
        bricks.append(brick)

    return {
        "schema_version": "0.1",
        "image_id": image_id,
        "image_size_px": {
            "width": int(image_width),
            "height": int(image_height),
        },
        **(
            {"source_detector": source_detector}
            if source_detector is not None
            else {}
        ),
        "processing_status": "partial",
        "bricks": bricks,
    }


def save_inventory(inventory: dict, output_path: Path) -> None:
    """Save an inventory as readable JSON for another module or person."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )


def build_color_inventory(inventory: dict, classification: dict) -> dict:
    """Add relative color results without modifying the detector inventory."""
    colored_inventory = deepcopy(inventory)
    assignments = {
        item["id"]: item for item in classification.get("assignments", [])
    }

    for brick in colored_inventory["bricks"]:
        assignment = assignments.get(brick["id"])
        if assignment is None:
            brick["color_group"] = "unknown"
            brick["color_score"] = 0.0
            continue
        brick["color_group"] = assignment["color_group"]
        brick["color_score"] = assignment["color_score"]

    selected_k = classification.get("selected_k")
    selected_candidate = next(
        (
            candidate
            for candidate in classification.get("candidates", [])
            if candidate["k"] == selected_k
        ),
        None,
    )
    colored_inventory["schema_version"] = "0.2"
    colored_inventory["processing_status"] = (
        "color_estimated"
        if classification.get("status") == "accepted"
        else "color_inconclusive"
    )
    colored_inventory["color_estimation"] = {
        "method": "relative_cielab_kmeans_v0.1",
        "status": classification.get("status", "inconclusive"),
        "selected_k": selected_k,
        "selection_reason": classification.get("selection_reason"),
        "group_centers_lab": (
            [] if selected_candidate is None else selected_candidate["centers_lab"]
        ),
    }
    return colored_inventory

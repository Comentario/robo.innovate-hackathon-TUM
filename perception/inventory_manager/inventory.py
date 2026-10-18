import json
from pathlib import Path


def build_partial_inventory(
    image_id: str,
    image_shape: tuple[int, ...],
    detections: list[dict],
) -> dict:
    """Build an inventory whose color estimation is still pending."""
    image_height, image_width = image_shape[:2]
    return {
        "schema_version": "0.1",
        "image_id": image_id,
        "image_size_px": {
            "width": int(image_width),
            "height": int(image_height),
        },
        "processing_status": "partial",
        "bricks": detections,
    }


def save_inventory(inventory: dict, output_path: Path) -> None:
    """Save an inventory as readable JSON for another module or person."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )

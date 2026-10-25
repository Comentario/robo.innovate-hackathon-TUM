"""Run Grounding DINO locally on the clean brick images of the hackathon dataset.

Mirrors Initial_Dataset_Bricks_LEGO/brick_detector_colab.ipynb (same model,
prompt, thresholds and resize), but only processes brick scenes without paper
labels and also stores every box in original image pixels.
"""

import argparse
import json
import re
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont, ImageOps
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "grounding_dino"

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
PROMPT = "bricks"
BOX_THRESHOLD = 0.35
TEXT_THRESHOLD = 0.25
MAX_SIDE = 1280

# Brick scenes are named "<count>B_<condition>_NS.jpg". Scenes ending in "_S"
# contain paper labels, and LEGO/WIN images do not show real bricks.
SCENE_PATTERN = re.compile(r"^(\d+)B_.+_NS\.jpg$")


def normalize_prompt(prompt: str) -> str:
    """Grounding DINO expects lowercase phrases that end with a period."""
    parts = [p.strip().lower() for p in re.split(r"[.,]", prompt) if p.strip()]
    return ". ".join(parts) + "." if parts else ""


def list_scenes(image_root: Path, pattern: re.Pattern) -> list[Path]:
    """Return the matching brick scenes in a stable order."""
    return sorted(p for p in image_root.iterdir() if pattern.match(p.name))


def expected_count(name: str, pattern: re.Pattern) -> int | None:
    """Read the brick count from the first pattern group when it has one."""
    match = pattern.match(name)
    if match and match.groups() and (match.group(1) or "").isdigit():
        return int(match.group(1))
    return None


def load_font(size: int):
    """Load the default PIL font at a readable size."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def detect(model, processor, device, image, prompt, box_thr, text_thr) -> list[dict]:
    """Run one zero-shot detection and return boxes in the given image size."""
    inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
    with torch.inference_mode():
        outputs = model(**inputs)
    result = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        threshold=box_thr,
        text_threshold=text_thr,
        target_sizes=[image.size[::-1]],
    )[0]
    labels = result.get("text_labels") or result.get("labels") or []
    return [
        {
            "label": str(label) or "object",
            "score": round(float(score), 3),
            "box": [round(v, 1) for v in box],
        }
        for box, score, label in zip(
            result["boxes"].tolist(), result["scores"].tolist(), labels
        )
    ]


def annotate(image: Image.Image, detections: list[dict]) -> Image.Image:
    """Draw numbered boxes with their scores."""
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    longest = max(canvas.size)
    width = max(2, round(longest / 400))
    font = load_font(max(12, round(longest / 50)))
    for index, detection in enumerate(detections, 1):
        x1, y1, x2, y2 = detection["box"]
        draw.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=width)
        text = f"{index} {detection['label']} {detection['score']:.2f}"
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        text_y = max(0, y1 - (bottom - top) - 6)
        draw.rectangle(
            [x1, text_y, x1 + right - left + 8, text_y + bottom - top + 6],
            fill=(255, 64, 64),
        )
        draw.text((x1 + 4, text_y + 2), text, fill=(255, 255, 255), font=font)
    return canvas


def to_original_pixels(box: list[float], scale: float, size: tuple[int, int]) -> dict:
    """Convert an x1/y1/x2/y2 box from the resized image to original pixels."""
    width, height = size
    x1, y1, x2, y2 = (round(v * scale) for v in box)
    x1, x2 = max(0, x1), min(width, x2)
    y1, y2 = max(0, y1), min(height, y2)
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--box-threshold", type=float, default=BOX_THRESHOLD)
    parser.add_argument("--text-threshold", type=float, default=TEXT_THRESHOLD)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--images", type=Path, default=IMAGE_ROOT)
    parser.add_argument(
        "--pattern", default=SCENE_PATTERN.pattern,
        help="Regex for image names; group 1, if numeric, is the expected count.",
    )
    args = parser.parse_args()

    pattern = re.compile(args.pattern)
    prompt = normalize_prompt(args.prompt)
    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    start = time.monotonic()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID)
    model = model.to(device).eval()
    print(f"model {MODEL_ID} on {device} ready in {time.monotonic() - start:.1f}s")

    all_records = {}
    summary = []
    for path in list_scenes(args.images, pattern):
        original = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        resized = original.copy()
        resized.thumbnail((MAX_SIDE, MAX_SIDE))
        scale = original.width / resized.width

        start = time.monotonic()
        detections = detect(
            model, processor, device, resized, prompt,
            args.box_threshold, args.text_threshold,
        )
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        for detection in detections:
            detection["bbox_px"] = to_original_pixels(
                detection["box"], scale, original.size
            )

        expected = expected_count(path.name, pattern)
        record = {
            "image": path.name,
            "model": MODEL_ID,
            "prompt": prompt,
            "box_threshold": args.box_threshold,
            "text_threshold": args.text_threshold,
            "size": list(resized.size),
            "original_size": list(original.size),
            "expected_bricks": expected,
            "count": len(detections),
            "detections": detections,
            "ms": elapsed_ms,
        }
        annotate(resized, detections).save(
            output_root / f"{path.stem}_preview.jpg", quality=90
        )
        (output_root / f"{path.stem}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        all_records[path.name] = record
        summary.append(
            {"image": path.name, "expected_bricks": expected, "detections": len(detections)}
        )
        print(f"{path.name}: {len(detections)} boxes (expected {expected}, {elapsed_ms:.0f} ms)")

    (output_root / "detections.json").write_text(
        json.dumps(all_records, indent=2), encoding="utf-8"
    )
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

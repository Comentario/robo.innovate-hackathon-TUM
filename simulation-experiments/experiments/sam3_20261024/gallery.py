"""Small contact sheet from saved overlays only; no inference or refinement."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prompts = [("stack", "stack of LEGO bricks"), ("brick", "LEGO brick"),
               ("brick_2x4", "2x4 LEGO brick"), ("top_surface", "top surface of a LEGO brick")]
    views = ["img_1", "img_10", "img_16"]
    width, height, header = 480, 270, 32
    canvas = Image.new("RGB", (4*width, len(views)*(height+header)+36), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), "SAM 3 | original raw contours/boxes; thumbnail display only | no deduplication/refinement", fill="black")
    for row, view in enumerate(views):
        for col, (prompt_id, text) in enumerate(prompts):
            folder = args.predictions/prompt_id/view
            data = json.loads((folder/"raw.json").read_text())
            image = Image.open(folder/"overlay.png").convert("RGB")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            x, y = col*width, 36+row*(height+header)
            draw.text((x+6, y+5), f"{view} | {text} | n={len(data['detections'])}", fill="black")
            canvas.paste(image, (x, y+header))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, quality=90)


if __name__ == "__main__":
    main()

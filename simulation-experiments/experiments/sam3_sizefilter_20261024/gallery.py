"""Compose a few saved overlays; no inference, filtering or scoring."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--processed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    views = ["img_1", "img_13", "img_16", "img_10"]
    width, height, header = 480, 270, 32
    canvas = Image.new("RGB", (3*width, len(views)*(height+header)+32), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), "Saved SAM masks: raw | dimension filter | plus seam splits. Last row shows the wrong-scale failure.", fill="black")
    for row, view in enumerate(views):
        folders = [("Raw SAM", args.original/view),
                   ("Size retained", args.processed/view/"retained_only"),
                   ("With seam splits", args.processed/view/"final")]
        for column, (label, folder) in enumerate(folders):
            record = json.loads((folder/"raw.json").read_text())
            image = Image.open(folder/"overlay.png").convert("RGB")
            x, y = column*width, 32+row*(height+header)
            draw.text((x+6, y+5), f"{view} | {label} | n={len(record['detections'])}", fill="black")
            canvas.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, y+header))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, quality=90)


if __name__ == "__main__":
    main()

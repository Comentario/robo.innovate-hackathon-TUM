"""Queued composition of saved overlays; labels are evaluation-only display."""
import argparse
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sam-root", type=Path, required=True)
    parser.add_argument("--size-root", type=Path, required=True)
    parser.add_argument("--chain-root", type=Path, required=True)
    parser.add_argument("--missing-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise SystemExit("Queue saved-overlay batch composition through default Pueue")
    absence = json.loads(args.missing_reference.read_text())["instances"]
    views = [("img_13", "partial success; inferred internal boundaries"),
             ("img_1", "gap failure: no missing declarations"),
             ("img_7", "phase uncertainty and incomplete coverage"),
             ("img_9", "all ridge proposals rejected at pitch stage")]
    width, height, header = 480, 270, 44
    canvas = Image.new("RGB", (4*width, len(views)*(height+header)+40), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 6), "Saved outputs only. Chains: green present, amber uncertain; cyan observed / magenta inferred boundary.", fill="black")
    draw.text((8, 22), "White polygons in chain panels: supplementary visual-face absence references (EVALUATION ONLY). No successful missing call occurred.", fill="black")
    for row, (stem, note) in enumerate(views):
        chain = json.loads((args.chain_root/stem/"chains.json").read_text())
        folders = [("Raw SAM", args.sam_root/stem),
                   ("Dimensions only", args.size_root/stem/"retained_only"),
                   ("Dimensions + splits", args.size_root/stem/"final"),
                   ("Ridge chains", args.chain_root/stem)]
        for col, (label, folder) in enumerate(folders):
            image = Image.open(folder/"overlay.png").convert("RGB")
            if col == 3:
                painter = ImageDraw.Draw(image)
                for ref in absence:
                    if ref["file"] == stem+".jpg":
                        points = [tuple(p) for p in ref["polygon"]]
                        painter.line(points+[points[0]], fill="white", width=3)
                count = {d: sum(s["decision"] == d for c in chain["chains"] for s in c["slots"])
                         for d in ("present", "missing", "uncertain")}
                detail = f"P={count['present']} M={count['missing']} U={count['uncertain']}"
            else:
                record = json.loads((folder/"raw.json").read_text())
                detail = f"n={len(record['detections'])}"
            x, y = col*width, 40+row*(height+header)
            draw.text((x+5, y+4), f"{stem} | {label} | {detail}", fill="black")
            draw.text((x+5, y+23), note, fill="black")
            canvas.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, y+header))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, quality=90)


if __name__ == "__main__":
    main()

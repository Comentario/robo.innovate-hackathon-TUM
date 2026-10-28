#!/usr/bin/env python3
"""Build an evidence board from encoded film stills; never retouch source frames."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("unreal/lighting/presentation-review.v1.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/unreal_lighting_review"))
    parser.add_argument("--verify-video", action="store_true", help="Hash the original 4K film as well as the stills")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    title_font = ImageFont.truetype(font_path, 23)
    small_font = ImageFont.truetype(font_path, 17)
    board = Image.new("RGB", (1920, 4 * 640 + 100), "#101820")
    draw = ImageDraw.Draw(board)
    draw.text((24, 16), "CURRENT FILM | PRESENTATION LIGHTING REVIEW", font=title_font, fill="white")
    draw.text((24, 52), "Observed baseline only. Boxes mark review areas; proposed lighting has not been rendered.", font=small_font, fill="#b9c7d3")
    cards, evidence = [], []
    for index, item in enumerate(profile["findings"]):
        seconds = item["seconds"]
        filename = f"frame-{round(seconds * 1000):06d}.jpg"
        source = Path(profile["reference"]["stills"]) / filename
        with Image.open(source) as original:
            assert original.size == (1600, 900), (source, original.size)
            frame = original.resize((960, 540), getattr(Image, "Resampling", Image).LANCZOS)
        x, y = (index % 2) * 960, 100 + (index // 2) * 640
        color = "#ffb85c" if item["priority"] == "P1" else "#69c5e4"
        minutes, secs = divmod(seconds, 60)
        timecode = f"{int(minutes):02d}:{secs:06.3f}"
        title = f'{item["id"]}  {item["priority"]}  {timecode}  |  {item["title"]}'
        draw.text((x + 16, y + 10), title, font=title_font, fill=color)
        board.paste(frame, (x, y + 52))
        left, top, right, bottom = item["region"]
        assert 0 <= left < right <= 1 and 0 <= top < bottom <= 1
        draw.rectangle((x + left * 960, y + 52 + top * 540, x + right * 960, y + 52 + bottom * 540), outline=color, width=3)
        draw.text((x + 16, y + 605), "Baseline frame / proposed correction pending", font=small_font, fill="#b9c7d3")
        encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        escape = html.escape
        cards.append(
            f'<article><h2>{escape(title)}</h2><div class="frame">'
            f'<img alt="{escape(item["title"])} baseline" src="data:image/jpeg;base64,{encoded}">'
            f'<div class="box" style="left:{left*100}%;top:{top*100}%;width:{(right-left)*100}%;height:{(bottom-top)*100}%;border-color:{color}"></div></div>'
            f'<p><b>Observed:</b> {escape(item["observation"])}</p>'
            f'<p><b>Proposed:</b> {escape(item["proposal"])}</p>'
            f'<p><b>Acceptance:</b> {escape(item["acceptance"])}</p></article>'
        )
        evidence.append({"id": item["id"], "seconds": seconds, "file": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    # Also inventory frames inspected beyond the eight illustrated examples.
    all_frames = []
    for seconds in profile["reference"]["sampleSeconds"]:
        source = Path(profile["reference"]["stills"]) / f"frame-{round(seconds * 1000):06d}.jpg"
        all_frames.append({"seconds": seconds, "file": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    board.save(args.output / "lighting-review-board.jpg", quality=94)
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brickflow | Lighting review</title><style>
body{font:16px/1.5 system-ui;margin:32px auto;padding:0 20px;max-width:1450px;background:#101820;color:#e4edf4}
h1{font-size:30px}h2{font-size:19px;color:#ffcd88}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr));gap:24px}
article{background:#192631;padding:18px;border-radius:12px}.frame{position:relative}img{width:100%;display:block}.box{position:absolute;box-sizing:border-box;border:2px solid}
button{background:#d7e6f0;border:0;padding:10px 15px;border-radius:6px;cursor:pointer;margin-bottom:20px}b{color:#acd9ea}.hide .box{display:none}
</style><h1>Current film: presentation lighting review</h1>
<p>Greenfield 30 native film. Eight illustrated findings from sixteen reviewed film stills. P1 = first correction pass; P2 = second pass.</p>
<p>These are baseline images, with review boxes only. Lighting proposals have not been applied or rendered. New warehouse, AMR and dock zones require a separate review in the final simulation.</p>
<button onclick="document.body.classList.toggle('hide')">Toggle review boxes</button><main>'''
    (args.output / "index.html").write_text(document + "".join(cards) + "</main></html>")
    manifest = {"schema": "brickflow.lighting-review-evidence.v1", "profileSha256": hashlib.sha256(args.profile.read_bytes()).hexdigest(), "videoSha256Verified": False, "allSamples": all_frames, "illustratedSamples": evidence, "lightingChangesApplied": False}
    if args.verify_video:
        digest = hashlib.sha256()
        with Path(profile["reference"]["film"]).open("rb") as video:
            for chunk in iter(lambda: video.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        manifest["videoSha256"] = digest.hexdigest()
        assert digest.hexdigest() == profile["reference"]["expectedSha256"], "Film differs from the reviewed delivery"
        manifest["videoSha256Verified"] = True
    (args.output / "evidence.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"findings": len(evidence), "samples": len(all_frames), "output": str(args.output), "videoSha256Verified": manifest["videoSha256Verified"]}))


if __name__ == "__main__":
    main()

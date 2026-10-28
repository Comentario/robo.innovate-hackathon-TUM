"""Editorial comparison of the delivered film and real Franka footage, using actual pixels."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--physical", type=Path, required=True, help="Upright 30fps portrait proxy, beginning at original footage second 4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--gpu", default="2")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--original-sha256", required=True)
    parser.add_argument("--layout-profile", type=Path, help="Optional editorial variation; the original layout remains the default")
    parser.add_argument("--prepare-only", action="store_true", help="Write the mask and filtergraph without encoding")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    width, height = args.width, args.width * 9 // 16
    panel_h = height * 8 // 9
    panel_w = panel_h * 9 // 16
    margin = width // 80
    radius = width // 100
    profile = json.loads(args.layout_profile.read_text()) if args.layout_profile else None
    if profile:
        panel_h = round(height * profile["heightFraction"] / 32) * 32
        panel_w = panel_h * 9 // 16
        radius = round(width * profile["cornerRadiusFraction"])
    # A presentation matte and shadow; the captured robot pixels remain genuine.
    mask = Image.new("L", (panel_w * 4, panel_h * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, panel_w * 4 - 1, panel_h * 4 - 1), radius=radius * 4, fill=255)
    mask = mask.resize((panel_w, panel_h), getattr(Image, "Resampling", Image).LANCZOS)
    if profile and profile.get("edgeFeatherFraction", 0):
        feather = max(1, round(width * profile["edgeFeatherFraction"]))
        padded = Image.new("L", (panel_w + 4 * feather, panel_h + 4 * feather), 0)
        padded.paste(mask, (2 * feather, 2 * feather))
        mask = padded.filter(ImageFilter.GaussianBlur(feather)).crop((2 * feather, 2 * feather, panel_w + 2 * feather, panel_h + 2 * feather))
    if profile and profile.get("opacity", 1) != 1:
        opacity = profile["opacity"]
        mask = mask.point(lambda value: round(value * opacity))
    mask.save(args.output / "portrait-mask.png")
    card_size = (panel_w + 2 * margin, panel_h + 2 * margin)
    shadow_alpha = Image.new("L", card_size, 0)
    shadow_strength = profile.get("shadowOpacity", 150) if profile else 150
    ImageDraw.Draw(shadow_alpha).rounded_rectangle((margin, margin + 8, panel_w + margin, panel_h + margin + 8), radius=radius, fill=shadow_strength)
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(max(1, margin / 2)))
    shadow = Image.new("RGBA", card_size, (0, 0, 0, 0));shadow.putalpha(shadow_alpha)
    shadow.save(args.output / "portrait-shadow.png")
    x = width - panel_w - width // 30 - margin
    y = (height - panel_h) // 2 - margin
    fade_in, fade_out = [6, 7.2], [16.3, 18.1]
    if profile:
        x = round(width * profile["leftFraction"]) - margin
        y = round(height * profile["topFraction"]) - margin
        fade_in, fade_out = profile["fadeInSeconds"], profile["fadeOutSeconds"]
        assert 0 <= x + margin and x + margin + panel_w <= width
        assert 0 <= y + margin and y + margin + panel_h <= height
    x_expression, y_expression = str(x), str(y)
    if profile and profile.get("entryOffsetFraction"):
        u = f"clip((t-{fade_in[0]})/{fade_in[1]-fade_in[0]},0,1)"
        remaining = f"(1-pow({u},3)*(10-15*{u}+6*pow({u},2)))"
        dx, dy = profile["entryOffsetFraction"]
        x_expression = f"'{x}+{round(dx*width)}*{remaining}'"
        y_expression = f"'{y}+{round(dy*height)}*{remaining}'"
    fade_filters = "fade=t=in:st=3.7:d=1.2:alpha=1,fade=t=out:st=14:d=1.8:alpha=1,"
    if profile:
        fade_filters = f"fade=t=in:st={fade_in[0]-2.3:.6f}:d={fade_in[1]-fade_in[0]:.6f}:alpha=1,fade=t=out:st={fade_out[0]-2.3:.6f}:d={fade_out[1]-fade_out[0]:.6f}:alpha=1,"
    graph = (
        f"[0:v]fps=30,scale={width}:{height}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[base];"
        f"[1:v]trim=duration=12.8,setpts=PTS-STARTPTS,fps=30,scale={panel_w}:{panel_h}:flags=lanczos,"
        "setsar=1,tpad=stop_mode=clone:stop_duration=4,format=rgba[real];"
        "[2:v]format=gray[mask];[real][mask]alphamerge[masked];"
        f"[3:v][masked]overlay=x={margin}:y={margin}:shortest=1:format=auto,"
        f"{fade_filters}"
        "setpts=PTS+2.3/TB[card];"
        f"[base][card]overlay=x={x_expression}:y={y_expression}:eof_action=pass:format=auto,format=yuv420p[out]"
    )
    (args.output / "filtergraph.txt").write_text(graph + "\n")
    if args.prepare_only:
        print(json.dumps({"filtergraph": graph, "panelBoundsPixels": [x+margin, y+margin, panel_w, panel_h]}))
        return
    final = args.output / "brickflow-franka-overlay-4k.mp4"
    command = [args.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "warning", "-filter_complex_threads", "2",
               "-ss", "84", "-i", str(args.simulation), "-i", str(args.physical),
               "-loop", "1", "-framerate", "30", "-i", str(args.output / "portrait-mask.png"),
               "-loop", "1", "-framerate", "30", "-i", str(args.output / "portrait-shadow.png"),
               "-filter_complex", graph, "-map", "[out]", "-frames:v", "840", "-an", "-map_metadata", "-1",
               "-c:v", "h264_nvenc", "-gpu", args.gpu, "-preset", "p7", "-tune", "hq", "-rc", "vbr",
               "-cq", "16", "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1", "-pix_fmt", "yuv420p",
               "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-movflags", "+faststart", str(final)]
    with (args.output / "encode.log").open("w") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    preview = args.output / "brickflow-franka-overlay-1080p.mp4"
    subprocess.run([args.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(final),
                    "-vf", "scale=1920:1080:flags=lanczos", "-an", "-map_metadata", "-1", "-c:v", "h264_nvenc",
                    "-gpu", args.gpu, "-preset", "p7", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(preview)], check=True)
    plan = {"schema": "brickflow.franka-overlay-edit.v1", "status": "editorial-visual-test",
            "simulationSource": str(args.simulation), "physicalProxy": str(args.physical), "originalPhysicalSha256": args.original_sha256,
            "physicalProxySha256": hashlib.sha256(args.physical.read_bytes()).hexdigest(),
            "simulationFilmStartSeconds": 84, "durationSeconds": 28, "fps": 30, "frames": 840,
            "physicalOriginalStartSeconds": 4, "physicalOriginalEndSeconds": 16.8,
            "physicalOriginalToFilmOffsetSeconds": 82.3,
            "fadeInFilmSeconds": [84+t for t in fade_in], "fadeOutFilmSeconds": [84+t for t in fade_out],
            "physicalFreezeFilmSeconds": [99.1, 84+fade_out[1]], "physicalPlaybackRate": 1,
            "note": "Approximate editorial phase alignment, not calibrated image registration or validation of robot control. No native simulation poses or clock were modified. Original phone video is preserved; presentation comparison is silent.",
            "outputs": []}
    if profile:
        plan["layoutProfile"] = profile
        plan["layoutProfileSha256"] = hashlib.sha256(args.layout_profile.read_bytes()).hexdigest()
        plan["panelBoundsPixels"] = [x+margin, y+margin, panel_w, panel_h]
    for p in [final, preview]:
        plan["outputs"].append({"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    (args.output / "edit-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()

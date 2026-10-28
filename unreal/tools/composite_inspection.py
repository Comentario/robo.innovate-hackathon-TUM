"""Show one recorded classification camera over the delivered inspection film shot."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--algorithm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", default="2")
    args = parser.parse_args()
    digest = hashlib.sha256(args.algorithm.read_bytes()).hexdigest()
    assert digest == "9649e3d6f42b9591d8dfdbb7b99ef796abc4dbb3e5da712afa5b24dba104c354", "Classification recording differs from inspected source"
    args.output.mkdir(exist_ok=False, parents=True)
    width, height, margin, radius = 1536, 1192, 48, 32
    mask = Image.new("L", (width * 4, height * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * 4 - 1, height * 4 - 1), radius=radius * 4, fill=255)
    mask = mask.resize((width, height), getattr(Image, "Resampling", Image).LANCZOS)
    mask.save(args.output / "camera-mask.png")
    alpha = Image.new("L", (width + 2 * margin, height + 2 * margin), 0)
    ImageDraw.Draw(alpha).rounded_rectangle((margin, margin + 8, width + margin, height + margin + 8), radius=radius, fill=135)
    alpha = alpha.filter(ImageFilter.GaussianBlur(24))
    shadow = Image.new("RGBA", alpha.size, (0, 0, 0, 0));shadow.putalpha(alpha)
    shadow.save(args.output / "camera-shadow.png")
    graph = (
        "[0:v]fps=30,scale=3840:2160:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[base];"
        f"[1:v]fps=30,setpts=PTS-STARTPTS,scale={width}:{height}:flags=lanczos,setsar=1,"
        "tpad=stop_mode=clone:stop_duration=2,format=rgba[feed];"
        "[2:v]format=gray[mask];[feed][mask]alphamerge[masked];"
        f"[3:v][masked]overlay=x={margin}:y={margin}:shortest=1:format=auto,"
        "fade=t=in:st=0:d=1.2:alpha=1,fade=t=out:st=10.2:d=1.6:alpha=1,setpts=PTS+11/TB[card];"
        "[base][card]overlay=x=86:y=49:eof_action=pass:format=auto,format=yuv420p[out]"
    )
    (args.output / "filtergraph.txt").write_text(graph + "\n")
    master = args.output / "brickflow-inspection-overlay-4k.mp4"
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-filter_complex_threads", "2",
               "-ss", "118", "-i", str(args.simulation), "-i", str(args.algorithm),
               "-loop", "1", "-framerate", "30", "-i", str(args.output / "camera-mask.png"),
               "-loop", "1", "-framerate", "30", "-i", str(args.output / "camera-shadow.png"),
               "-filter_complex", graph, "-map", "[out]", "-frames:v", "840", "-an", "-map_metadata", "-1",
               "-c:v", "h264_nvenc", "-gpu", args.gpu, "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0",
               "-spatial-aq", "1", "-temporal-aq", "1", "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
               "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", str(master)]
    with (args.output / "encode.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    preview = args.output / "brickflow-inspection-overlay-1080p.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(master),
                    "-vf", "scale=1920:1080:flags=lanczos", "-an", "-map_metadata", "-1", "-c:v", "h264_nvenc", "-gpu", args.gpu,
                    "-preset", "p7", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(preview)], check=True)
    plan = {"schema": "brickflow.inspection-overlay-edit.v1", "status": "editorial-visual-test", "cameraFeedsShown": 1,
            "algorithmSource": args.algorithm.name, "algorithmSourceSha256": digest,
            "algorithmSourceResolution": [848, 658], "algorithmSourceFrames": 319, "algorithmPlaybackRate": 1,
            "sourceAnnotationsPreserved": True, "simulationFilmStartSeconds": 118, "durationSeconds": 28, "fps": 30, "frames": 840,
            "simulationClockModified": False, "algorithmStartsAtFilmSecond": 129,
            "fadeInFilmSeconds": [129, 130.2], "fadeOutFilmSeconds": [139.2, 140.8],
            "sourceFrameHoldFilmSeconds": [129 + 319 / 30, 140.8], "panelBoundsPixels": [134, 97, width, height],
            "limitations": "The recorded one-camera detections illustrate the physical classifier. Real and synthetic brick IDs are not paired. The 848x658 source is scaled for presentation; 4K export adds no source detail. This edit is not independent validation of the classifier or a two-camera accuracy claim.",
            "outputs": []}
    for p in [master, preview]:
        plan["outputs"].append({"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    (args.output / "edit-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()

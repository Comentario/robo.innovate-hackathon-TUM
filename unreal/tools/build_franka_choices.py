"""Verify six editorial choices and build a portable video comparison folder."""
import argparse
import concurrent.futures
import hashlib
import html
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def verify_video(path, expected):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_packets",
        "-show_entries", "stream=width,height,r_frame_rate,nb_frames,nb_read_frames:format=duration,size:packet=pts_time,dts_time",
        "-of", "json", str(path)], text=True))
    stream, packets = probe["streams"][0], probe["packets"]
    assert stream["nb_read_frames"] == "840" and stream["nb_frames"] == "840"
    assert stream["r_frame_rate"] == "30/1" and float(probe["format"]["duration"]) == 28
    assert len(packets) == 840
    pts = sorted(float(p["pts_time"]) for p in packets)
    error = max(abs(t - i / 30) for i, t in enumerate(pts))
    assert error < 0.00002
    dts = [float(p["dts_time"]) for p in packets]
    assert all(b > a for a, b in zip(dts, dts[1:]))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == expected["sha256"] and path.stat().st_size == expected["bytes"]
    return {"file": path.name, "sha256": digest, "framesDecoded": 840, "durationSeconds": 28,
            "width": stream["width"], "height": stream["height"], "packetTimestampErrorSeconds": error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gpu", default="3")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    original = json.loads((args.baseline / "edit-plan.json").read_text())
    baseline_copy = args.root / "v1-original"
    # Keep a complete byte-identical baseline inside the portable comparison folder.
    for entry in original["outputs"]:
        p = args.baseline / entry["file"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == entry["sha256"]
        destination = baseline_copy / entry["file"]
        if not destination.exists():
            shutil.copyfile(p, destination)
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == entry["sha256"]
    shutil.copyfile(args.baseline / "edit-plan.json", baseline_copy / "edit-plan.json")
    variants = [{"id": "v1-original", "label": "V1 · Original", "description": "Preserved original. Large portrait on the right, rounded corners and a soft shadow."}] + config["variants"]
    def inspect(variant):
        directory = args.root / variant["id"]
        plan = json.loads((directory / "edit-plan.json").read_text())
        for key in ["physicalProxySha256", "originalPhysicalSha256", "simulationFilmStartSeconds", "durationSeconds", "fps", "frames", "physicalOriginalStartSeconds", "physicalOriginalEndSeconds", "physicalOriginalToFilmOffsetSeconds", "physicalPlaybackRate"]:
            assert plan[key] == original[key], (variant["id"], key)
        checks = [verify_video(directory / item["file"], item) for item in plan["outputs"]]
        for seconds in [6.4, 7.2, 10, 13, 17, 20]:
            name = "poster.jpg" if seconds == 10 else f"sample-{round(seconds*10):03d}.jpg"
            target = directory / name
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "2", "-ss", str(seconds),
                            "-i", str(directory / "brickflow-franka-overlay-1080p.mp4"), "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "2", "-y", str(target)], check=True)
        result = dict(variant, preview=variant["id"] + "/brickflow-franka-overlay-1080p.mp4",
                      fullResolution=variant["id"] + "/brickflow-franka-overlay-4k.mp4", poster=variant["id"] + "/poster.jpg", verification=checks)
        print(json.dumps({"verified": variant["id"], "outputs": len(checks)}), flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        choices = list(pool.map(inspect, variants))
    manifest = {"schema": "brickflow.franka-choices.v1", "originalPreserved": True, "newVariants": 5,
                "durationSeconds": 28, "choices": choices, "visualReviewStatus": "pending"}
    (args.root / "choices.json").write_text(json.dumps(manifest, indent=2) + "\n")
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 24)
    board = Image.new("RGB", (1920, 2 * 420 + 65), "#101820")
    draw = ImageDraw.Draw(board)
    draw.text((20, 18), "FRANKA OVERLAY | SIX EDITORIAL CHOICES | SAME OUTPUT TIME: 10 s", font=font, fill="white")
    for index, choice in enumerate(choices):
        image = Image.open(args.root / choice["poster"]).convert("RGB").resize((640, 360))
        x, y = index % 3 * 640, 65 + index // 3 * 420
        draw.text((x + 14, y + 8), choice["label"], font=font, fill="#a6dce9")
        board.paste(image, (x, y + 45))
    board.save(args.root / "choices-contact.jpg", quality=94)
    # The labeled mosaic is a review artifact. Individual presentation clips have no labels.
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-filter_complex_threads", "3"]
    filters = []
    for index, choice in enumerate(choices):
        command += ["-threads", "2", "-i", str(args.root / choice["preview"])]
        title = choice["label"].replace("·", "|")
        filters.append(f"[{index}:v]fps=30,scale=640:360:flags=lanczos,setsar=1,drawbox=x=0:y=0:w=iw:h=30:color=black@0.75:t=fill,drawtext=fontfile={font_path}:text='{title}':fontcolor=white:fontsize=18:x=10:y=5[v{index}]")
    filters.append("".join(f"[v{i}]" for i in range(6)) + "xstack=inputs=6:layout=0_0|640_0|1280_0|0_360|640_360|1280_360:fill=black,format=yuv420p[out]")
    command += ["-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "840", "-an", "-map_metadata", "-1", "-c:v", "h264_nvenc", "-gpu", args.gpu,
                "-preset", "p7", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(args.root / "compare-six.mp4")]
    with (args.root / "comparison-encode.log").open("w") as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    data = json.dumps(choices).replace("</", "<\\/")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brickflow | Franka overlay choices</title><style>
body{background:#101820;color:#e8f0f5;font:16px/1.5 system-ui;margin:28px auto;max-width:1800px;padding:0 24px}h1{font-size:29px}a{color:#8bd3ec}button,select{font:inherit;padding:9px 14px;border-radius:7px;border:0;background:#d8e8f2;color:#102631;margin:0 8px 12px 0}main{display:grid;grid-template-columns:1fr 1fr;gap:20px}section{background:#192832;border-radius:12px;padding:15px;min-width:0}video{width:100%;display:block;background:black;border-radius:8px}#scrub{width:min(700px,65vw)}small{color:#abc0cc}p{margin:10px 0}nav{margin-bottom:18px}#time{font-variant-numeric:tabular-nums}@media(max-width:900px){main{grid-template-columns:1fr}}.cardgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:20px}.cardgrid img{width:100%;border-radius:8px}.cardgrid button{width:100%;padding:10px;text-align:left;background:#223c4b;color:#e8f0f5}.cardgrid span{display:block}
</style><h1>Franka overlay: six choices</h1><p>Original V1 preserved, plus five new edits. Every clip uses the same 28-second simulation excerpt and the same real pickup cycle. Only presentation details change.</p>
<nav><button id="play">Play / pause both</button><button data-time="6.5">Fade in</button><button data-time="10">Transfer</button><button data-time="13">Placement</button><button data-time="17">Fade out</button><span id="time">0.00 / 28.00 s</span><br><input id="scrub" type="range" min="0" max="27.966667" step="0.033333" value="0"> <a href="compare-six.mp4">Open six-way comparison</a></nav>
<main><section><select id="pickA"></select><video id="a" controls muted playsinline preload="metadata"></video><p id="noteA"></p><a id="fullA">Open 4K</a></section><section><select id="pickB"></select><video id="b" muted playsinline preload="metadata"></video><p id="noteB"></p><a id="fullB">Open 4K</a></section></main>
<p><small>Use the left player or shared controls to keep both views aligned. The phase correspondence is editorial, not calibrated camera registration.</small></p><div class="cardgrid" id="cards"></div><script>
const choices=DATA,a=document.getElementById('a'),b=document.getElementById('b'),scrub=document.getElementById('scrub');let changing=false;
function assign(side,index,time=0,resume=false){const c=choices[index],v=side==='A'?a:b;v.src=c.preview;v.poster=c.poster;document.getElementById('note'+side).textContent=c.description;document.getElementById('full'+side).href=c.fullResolution;v.onloadedmetadata=()=>{v.currentTime=Math.min(time,v.duration-.04);if(resume)v.play().catch(()=>{})};v.load()}
for(const side of ['A','B']){const select=document.getElementById('pick'+side);choices.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=c.label;select.appendChild(o)});select.value=side==='A'?0:1;select.onchange=()=>{const time=a.currentTime,playing=!a.paused;assign(side,+select.value,time,playing)}}
assign('A',0);assign('B',1);
a.addEventListener('play',()=>{if(Math.abs(b.currentTime-a.currentTime)>.08)b.currentTime=a.currentTime;b.play().catch(()=>{})});a.addEventListener('pause',()=>b.pause());a.addEventListener('seeking',()=>{if(!changing&&b.readyState)b.currentTime=a.currentTime});a.addEventListener('timeupdate',()=>{scrub.value=a.currentTime;document.getElementById('time').textContent=a.currentTime.toFixed(2)+' / 28.00 s';if(!changing&&!a.paused&&b.readyState&&Math.abs(b.currentTime-a.currentTime)>.12)b.currentTime=a.currentTime});a.addEventListener('ended',()=>b.pause());
function seek(t){changing=true;a.pause();b.pause();a.currentTime=t;b.currentTime=t;setTimeout(()=>changing=false,100)}document.getElementById('play').onclick=()=>{if(a.paused){a.play().catch(()=>{});b.play().catch(()=>{})}else{a.pause();b.pause()}};scrub.oninput=()=>seek(+scrub.value);document.querySelectorAll('[data-time]').forEach(button=>button.onclick=()=>seek(+button.dataset.time));
choices.forEach((c,i)=>{const button=document.createElement('button'),image=document.createElement('img'),label=document.createElement('span');image.src=c.poster;image.alt=c.label;label.textContent=c.label;button.append(image,label);button.onclick=()=>{const time=a.currentTime;document.getElementById('pickB').value=i;assign('B',i,time,!a.paused)};document.getElementById('cards').appendChild(button)});
</script></html>'''
    (args.root / "index.html").write_text(page.replace("DATA", data))
    print(json.dumps({"choices": len(choices), "newVariants": 5, "verifiedOutputs": 12, "gallery": str(args.root / "index.html")}), flush=True)


if __name__ == "__main__":
    main()

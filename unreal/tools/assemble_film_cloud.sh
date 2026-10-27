#!/usr/bin/env bash
set -euo pipefail
root="$HOME/workspace/brickflow-native/Saved/Films"
label="${1:?Supply the shared render prefix}"
output="$root/$label-delivery"
mkdir -p "$output"
for i in 0 1 2 3; do
  part="$root/$label-part$i"
  test "$(cat "$part/render.status")" = 0
  test "$(cat "$part/encoder.status")" = 0
  test -f "$part/complete.status"
done
python3 - "$root" "$label" "$output" <<'PY'
import csv,json,pathlib,sys
root,label,out=pathlib.Path(sys.argv[1]),sys.argv[2],pathlib.Path(sys.argv[3]);parts=[root/f'{label}-part{i}' for i in range(4)]
plans=[json.loads((p/'edit-plan.json').read_text()) for p in parts];assert all(p==plans[0] for p in plans)
rows=[]
for p in parts:
 r=list(csv.DictReader((p/'trace.csv').open(encoding='utf-8-sig')));probe=json.loads((p/'video-probe.json').read_text())['streams'][0]
 assert int(probe['nb_frames'])==len(r),(p,probe,len(r));assert (probe['width'],probe['height'])==(3840,2160);rows+=r
assert [int(r['frame']) for r in rows]==list(range(plans[0]['frames']))
with (out/'trace.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
(out/'edit-plan.json').write_text(json.dumps(plans[0],indent=2))
for kind,filename in [('master','brickflow-master-444.mkv'),('review','brickflow-review-4k.mp4')]:
 (out/f'{kind}-parts.txt').write_text(''.join("file '"+str(p/filename)+"'\n" for p in parts))
(out/'insert-points.json').write_text(json.dumps([{'name':s['name'],'startSeconds':s['firstFrame']/30,'durationSeconds':s['frames']/30,'nativeSeconds':s['nativeStart']} for s in plans[0]['shots'] if s['freeze'] and s['camera'] in ('row-hold','sensor')],indent=2))
PY
ffmpeg -nostdin -hide_banner -loglevel warning -y -f concat -safe 0 -i "$output/master-parts.txt" \
  -map 0:v -c copy "$output/brickflow-tracking-master-4k-444.mkv"
ffmpeg -nostdin -hide_banner -loglevel warning -y -f concat -safe 0 -i "$output/review-parts.txt" \
  -map 0:v -c copy -movflags +faststart "$output/brickflow-tracking-4k.mp4"
ffprobe -v error -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,nb_frames \
  -show_entries format=duration,size -of json "$output/brickflow-tracking-4k.mp4" > "$output/video-probe.json"
python3 - "$output" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]);plan=json.loads((p/'edit-plan.json').read_text());probe=json.loads((p/'video-probe.json').read_text());s=probe['streams'][0]
assert int(s['nb_frames'])==plan['frames'];assert abs(float(probe['format']['duration'])-plan['frames']/30)<.04
assert (s['width'],s['height'],s['r_frame_rate'])==(3840,2160,'30/1')
print(json.dumps(probe,indent=2))
PY
sha256sum "$output/brickflow-tracking-4k.mp4" > "$output/review.sha256"
printf 'complete\n' > "$output/delivery.status"

#!/usr/bin/env bash
# Run from the repository root; resumes collection of the fixed v4 render.
set -euo pipefail
remote=/home/shadeform/workspace/brickflow-native/Saved/Films/continuous-4k-v4-delivery
output=artifacts/unreal_continuous/delivery
mkdir -p "$output"
trap 'printf "Collection failed; inspect collection.log.\n" > "$output/collection.status"' ERR
printf 'Waiting for cloud render and assembly.\n' > "$output/collection.status"
ready=false
for attempt in {1..240}; do
  if ssh -o BatchMode=yes -o ConnectTimeout=15 -T brickflow-cinematic "test -f '$remote/delivery.status'"; then ready=true; break; fi
  sleep 45
done
if [[ "$ready" != true ]]; then printf 'Timed out waiting for delivery.\n' > "$output/collection.status"; exit 1; fi
printf 'Validating complete native trace.\n' > "$output/collection.status"
for name in edit-plan.json trace.csv insert-points.json video-probe.json review.sha256; do
  scp -o BatchMode=yes "brickflow-cinematic:$remote/$name" "$output/$name"
done
python3 tests_native/verify_film.py "$output" --complete
python3 - "$output" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]);v=json.loads((p/'verification.json').read_text());assert not v['cameraAuditOnly']
PY
printf 'Creating and collecting review videos.\n' > "$output/collection.status"
ssh -o BatchMode=yes -T brickflow-cinematic 'bash /home/shadeform/workspace/brickflow-native/create_film_review_cloud.sh continuous-4k-v4-delivery'
scp -o BatchMode=yes "brickflow-cinematic:$remote/brickflow-tracking-1080p.mp4" "$output/brickflow-continuous-1080p.mp4"
scp -o BatchMode=yes "brickflow-cinematic:$remote/preview-probe.json" "$output/preview-probe.json"
# Parallel byte ranges avoid serial transfer bottlenecks. Never collect the large master.
ssh -o BatchMode=yes -T brickflow-cinematic "python3 - '$remote'" <<'PY'
import math,pathlib,sys
p=pathlib.Path(sys.argv[1]);src=p/'brickflow-tracking-4k.mp4';size=math.ceil(src.stat().st_size/4)
with src.open('rb') as f:
 for i in range(4):
  with (p/f'transfer-{i:02}').open('wb') as out:
   left=size
   while left:
    b=f.read(min(left,8*1024*1024))
    if not b:break
    out.write(b);left-=len(b)
PY
scratch=$(mktemp -d /tmp/brickflow-continuous-transfer.XXXXXX)
pids=()
for i in 00 01 02 03; do
  scp -o BatchMode=yes "brickflow-cinematic:$remote/transfer-$i" "$scratch/transfer-$i" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do wait "$pid"; done
cat "$scratch/transfer-00" "$scratch/transfer-01" "$scratch/transfer-02" "$scratch/transfer-03" > "$output/brickflow-continuous-4k.mp4"
ssh -o BatchMode=yes -T brickflow-cinematic "sha256sum '$remote/brickflow-tracking-1080p.mp4'" > "$output/preview.sha256"
python3 - "$output" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1])
for name,receipt in [('brickflow-continuous-4k.mp4','review.sha256'),('brickflow-continuous-1080p.mp4','preview.sha256')]:
 digest=hashlib.sha256()
 with (p/name).open('rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
 assert digest.hexdigest()==(p/receipt).read_text().split()[0],name
probe=json.loads((p/'preview-probe.json').read_text());s=probe['streams'][0]
assert (s['width'],s['height'],int(s['nb_frames']))==(1920,1080,11867)
(p/'collection.status').write_text('Downloaded and checksum-verified. Visual review still required.\n')
PY

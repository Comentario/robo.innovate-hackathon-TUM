#!/usr/bin/env bash
# Boot the native simulation on every adapter and audit it without capturing video.
set -euo pipefail
project="$HOME/workspace/brickflow-native"
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
repo="$HOME/workspace/robo.innovate-hackathon-TUM"
label="${1:?Supply a new audit prefix}"
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
test "$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)" -eq 4
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-native-audit"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
for i in 0 1 2 3; do test ! -e "$project/Saved/Migration/$label-gpu$i"; done
pids=()
for i in 0 1 2 3; do
  output="$project/Saved/Migration/$label-gpu$i"
  mkdir -p "$output"
  xvfb-run -n "$((240+i*5))" -a -s '-screen 0 1280x720x24' \
    "$engine/Engine/Binaries/Linux/UnrealEditor" "$project/Brickflow.uproject" /Engine/Maps/Entry \
    -game -RenderOffscreen -vulkan -preferNvidia "-graphicsadapter=$i" \
    -nosound -nosplash -unattended -nop4 -Windowed -ForceRes -ResX=1280 -ResY=720 \
    "-BrickflowFilm=$output" -BrickflowFilmAudit "-abslog=$output/engine.log" \
    > "$output/stdout.log" 2>&1 &
  pids+=("$!")
done
failed=false
for i in 0 1 2 3; do
  result=0
  wait "${pids[$i]}" || result=$?
  echo "$result" > "$project/Saved/Migration/$label-gpu$i/process.status"
  if [[ "$result" != 0 ]]; then failed=true; fi
done
[[ "$failed" == false ]]
for i in 0 1 2 3; do
  output="$project/Saved/Migration/$label-gpu$i"
  grep -q "Using device at index $i of 4" "$output/engine.log"
  python3 "$repo/tests_native/verify_film.py" "$output" \
    --reference "$repo/artifacts/unreal_film/selected-reference.json" --complete
  ffmpeg -nostdin -hide_banner -loglevel error -f lavfi -i color=c=black:s=1280x720:r=30 \
    -frames:v 1 -c:v h264_nvenc -gpu "$i" -f null - > "$output/encoder-null.log" 2>&1
  echo passed > "$output/encoder-null.status"
done
printf 'Four native GPU audits and NVENC null-output checks passed. No film captured.\n'

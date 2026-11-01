#!/usr/bin/env bash
set -euo pipefail
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
project="$HOME/workspace/brickflow-native"
mode="${1:-mixed}"
chapter="${2:-0}"
replay_time="${3:-2400}"
width="${4:-1920}"
height=$((width*9/16))
name="$mode-chapter$chapter"
extra=("${@:5}")
command=("$engine/Engine/Binaries/Linux/UnrealEditor" "$project/Brickflow.uproject" /Engine/Maps/Entry -game)
for option in "${extra[@]}"; do
  if [[ "$option" == "-BrickflowSceneOnly" ]]; then name="$name-scene"; fi
  if [[ "$option" == "-BrickflowPackaged" ]]; then
    command=("$project/Packaged/Linux/Brickflow.sh")
    name="$name-packaged"
  fi
done
mkdir -p "$project/Saved/NativePresentation" "$project/Saved/Logs"
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-runtime"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
status=0
timeout --kill-after=20s 1200s xvfb-run -a -s "-screen 0 ${width}x${height}x24" \
  "${command[@]}" -RenderOffscreen -vulkan -preferNvidia -unattended \
  -nosound -nosplash -nop4 -Windowed -ForceRes "-ResX=$width" "-ResY=$height" \
  "-BrickflowMode=$mode" "-BrickflowChapter=$chapter" "-BrickflowTime=$replay_time" \
  "-BrickflowCapture=$project/Saved/NativePresentation/$name.png" -BrickflowExit \
  "${extra[@]}" \
  "-abslog=$project/Saved/Logs/preview-$name.engine.log" \
  > "$project/Saved/Logs/preview-$name.stdout.log" 2>&1 || status=$?
printf '%s\n' "$status" > "$project/Saved/Logs/preview-$name.status"
tail -80 "$project/Saved/Logs/preview-$name.stdout.log"
printf '\nNATIVE_PREVIEW_EXIT_CODE=%s\n' "$status"

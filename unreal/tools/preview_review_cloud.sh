#!/usr/bin/env bash
# Render one still of a frozen source state through Unreal; never a film.
set -euo pipefail
project="${1:?Supply an isolated review project path}"
manifest="${2:?Supply a frozen review manifest path}"
view="${3:-warehouse}"
variant="${4:-baseline}"
gpu="${5:-1}"
width="${6:-1600}"
label="${7:-lighting-v2}"
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
[[ "$variant" == baseline || "$variant" == candidate ]]
[[ "$view" =~ ^[a-zA-Z0-9_-]+$ && "$gpu" =~ ^[0-9]+$ && "$width" =~ ^[0-9]+$ ]]
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]]
height=$((width*9/16))
state="$(basename "$manifest" .json)"
output="$project/Saved/ReviewStills/$label/$state-$view-$variant"
mkdir -p "$project/Saved/ReviewStills/$label"
test ! -e "$output.png"
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-review-$gpu"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
timeout --kill-after=20s 600s xvfb-run -a -s "-screen 0 ${width}x${height}x24" \
 "$engine/Engine/Binaries/Linux/UnrealEditor" "$project/Brickflow.uproject" /Engine/Maps/Entry \
 -game -RenderOffscreen -vulkan -preferNvidia -unattended -nosound -nosplash -nop4 \
 -Windowed -ForceRes "-ResX=$width" "-ResY=$height" "-graphicsadapter=$gpu" \
 "-BrickflowReview=$manifest" "-BrickflowReviewCamera=$view" "-BrickflowReviewLighting=$variant" \
 "-BrickflowReviewRig=$(dirname "$manifest")/lighting-candidate.json" \
 "-BrickflowCapture=$output.png" -BrickflowExit \
 '-ExecCmds=t.MaxFPS 30,r.ScreenPercentage 100,r.AntiAliasingMethod 4,sg.ShadowQuality 4,sg.ReflectionQuality 4,r.MotionBlurQuality 0' \
 "-abslog=$output.engine.log" > "$output.stdout.log" 2>&1
test -s "$output.png"
test -s "$output.png.evidence.json"
printf '%s\n' "$output.png"

#!/usr/bin/env bash
# Separate review desktop; the native simulation and its desktop remain intact.
set -euo pipefail
project="${1:?Supply the isolated review project path}"
manifest="${2:?Supply the snapshot manifest path}"
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
output="$project/Saved/ReviewInteractive"
mkdir -p "$output"
if [[ -s "$output/game.pid" ]] && kill -0 "$(cat "$output/game.pid")" 2>/dev/null; then
  printf 'Review desktop already running.\n'
  exit 0
fi
export DISPLAY=:82
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-review-interactive"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
if ! xdpyinfo -display :82 >/dev/null 2>&1; then
  test ! -e /tmp/.X82-lock
  nohup Xvfb :82 -screen 0 1600x900x24 -nolisten tcp > "$output/xvfb.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$output/xvfb.pid"
fi
for _ in $(seq 1 30); do
  if xdpyinfo -display :82 >/dev/null 2>&1; then break; fi
  sleep 1
done
running() { [[ -s "$output/$1.pid" ]] && kill -0 "$(cat "$output/$1.pid")" 2>/dev/null; }
if ! running openbox; then
  nohup openbox > "$output/openbox.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$output/openbox.pid"
fi
if ! running x11vnc; then
  nohup x11vnc -display :82 -rfbport 5902 -localhost -forever -shared -nopw \
    > "$output/x11vnc.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$output/x11vnc.pid"
fi
if ! running novnc; then
  nohup websockify --web=/usr/share/novnc 127.0.0.1:6081 localhost:5902 \
    > "$output/novnc.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$output/novnc.pid"
fi
nohup "$engine/Engine/Binaries/Linux/UnrealEditor" "$project/Brickflow.uproject" /Engine/Maps/Entry \
 -game -vulkan -preferNvidia -graphicsadapter=0 -unattended -nosound -nosplash -nop4 \
 -Windowed -ForceRes -ResX=1600 -ResY=900 -WinX=0 -WinY=0 \
 "-BrickflowReview=$manifest" -BrickflowReviewLighting=candidate \
 "-BrickflowReviewRig=$(dirname "$manifest")/lighting-candidate.json" \
 '-ExecCmds=t.MaxFPS 30,r.ScreenPercentage 100,r.AntiAliasingMethod 4,r.MotionBlurQuality 0' \
 "-abslog=$output/review.engine.log" > "$output/review.stdout.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$output/game.pid"
printf 'Review desktop :82, noVNC loopback 6081. Keys 1-8 presets, 9 forks, 0 stock, L baseline/candidate; right-drag orbit, wheel zoom. Frozen unvalidated source state.\n'

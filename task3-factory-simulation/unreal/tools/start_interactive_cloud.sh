#!/usr/bin/env bash
set -euo pipefail
project="$HOME/workspace/brickflow-native"
session="$project/Saved/Interactive"
mkdir -p "$session"
export DISPLAY=:81
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-interactive"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
start() {
  local name="$1"
  shift
  if [[ -f "$session/$name.pid" ]] && kill -0 "$(cat "$session/$name.pid")" 2>/dev/null; then
    return
  fi
  nohup "$@" > "$session/$name.log" 2>&1 < /dev/null &
  echo "$!" > "$session/$name.pid"
}
start display Xvfb :81 -screen 0 1600x900x24 -nolisten tcp
for attempt in {1..30}; do
  if xdpyinfo -display :81 >/dev/null 2>&1; then break; fi
  sleep .2
done
start desktop openbox
start game "$project/Packaged/Linux/Brickflow.sh" -vulkan -preferNvidia \
  -Windowed -ForceRes -ResX=1600 -ResY=900 -WinX=0 -WinY=0 -nosound -nosplash \
  -BrickflowTime=2400 '-ExecCmds=t.MaxFPS 30'
start vnc x11vnc -display :81 -localhost -rfbport 5901 -nopw -forever -shared -noxdamage
start browser websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901
printf 'Interactive services started. Forward 6080 over SSH; no public desktop port is opened.\n'

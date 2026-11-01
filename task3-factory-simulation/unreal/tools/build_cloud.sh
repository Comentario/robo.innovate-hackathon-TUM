#!/usr/bin/env bash
set -euo pipefail
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
project="$HOME/workspace/brickflow-native"
mkdir -p "$project/Saved/Logs"
status=0
"$engine/Engine/Build/BatchFiles/Linux/Build.sh" BrickflowEditor Linux Development \
  "-Project=$project/Brickflow.uproject" -WaitMutex -NoHotReloadFromIDE \
  > "$project/Saved/Logs/native-build.log" 2>&1 || status=$?
printf '%s\n' "$status" > "$project/Saved/Logs/native-build.status"
tail -80 "$project/Saved/Logs/native-build.log"
printf '\nNATIVE_BUILD_EXIT_CODE=%s\n' "$status"

#!/usr/bin/env bash
set -euo pipefail
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
project="$HOME/workspace/brickflow-native"
mkdir -p "$project/Saved/Logs"
status=0
timeout --kill-after=20s 900s "$engine/Engine/Binaries/Linux/UnrealEditor-Cmd" \
  "$project/Brickflow.uproject" -run=pythonscript \
  "-script=$project/create_materials.py" -unattended -nop4 -nosplash -NullRHI \
  "-log=$project/Saved/Logs/material-authoring.engine.log" \
  > "$project/Saved/Logs/material-authoring.stdout.log" 2>&1 || status=$?
printf '%s\n' "$status" > "$project/Saved/Logs/material-authoring.status"
tail -60 "$project/Saved/Logs/material-authoring.stdout.log"
printf '\nMATERIAL_AUTHORING_EXIT_CODE=%s\n' "$status"

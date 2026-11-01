#!/usr/bin/env bash
set -euo pipefail
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
project="$HOME/workspace/brickflow-native"
mkdir -p "$project/Saved/Logs"
status=0
"$engine/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun \
  "-project=$project/Brickflow.uproject" -noP4 -unattended \
  -platform=Linux -clientconfig=Development -build -cook -stage -pak -archive \
  "-archivedirectory=$project/Packaged" \
  > "$project/Saved/Logs/native-package.log" 2>&1 || status=$?
printf '%s\n' "$status" > "$project/Saved/Logs/native-package.status"
tail -60 "$project/Saved/Logs/native-package.log"
printf '\nNATIVE_PACKAGE_EXIT_CODE=%s\n' "$status"

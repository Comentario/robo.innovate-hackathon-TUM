#!/usr/bin/env bash
set -euo pipefail
project="$HOME/workspace/brickflow-native"
label="${1:?Supply the shared render prefix}"
for attempt in {1..2160}; do
  ready=true
  for i in 0 1 2 3; do
    p="$project/Saved/Films/$label-part$i"
    if [[ -f "$p/render.status" ]] && [[ "$(cat "$p/render.status")" != 0 ]]; then echo "Render failed: $p"; exit 1; fi
    if [[ ! -s "$p/video-probe.json" ]]; then ready=false; fi
  done
  if [[ "$ready" == true ]]; then
    bash "$project/assemble_film_cloud.sh" "$label"
    exit
  fi
  sleep 5
done
printf 'Timed out waiting for render parts.\n'
exit 1

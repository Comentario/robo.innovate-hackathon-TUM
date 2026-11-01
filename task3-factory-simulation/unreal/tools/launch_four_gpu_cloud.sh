#!/usr/bin/env bash
# One independent native film segment per Vulkan adapter; no simulation cuts.
set -euo pipefail
project="$HOME/workspace/brickflow-native"
label="${1:?Supply a new render prefix}"
width="${2:-3840}"
first="${3:-0}"
last="${4:-11867}"
[[ "$label" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
[[ "$width" =~ ^[0-9]+$ && "$first" =~ ^[0-9]+$ && "$last" =~ ^[0-9]+$ ]] || exit 2
test "$last" -gt "$((first+3))"
test "$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)" -eq 4
for i in 0 1 2 3; do
  test ! -e "$project/Saved/Films/$label-part$i"
done
count=$((last-first))
for i in 0 1 2 3; do
  start=$((first+count*i/4))
  end=$((first+count*(i+1)/4))
  output="$project/Saved/Films/$label-part$i"
  mkdir -p "$output"
  nohup bash "$project/render_film_cloud.sh" "$label-part$i" "$width" 1 stream "$((7901+i))" "$start" "$end" "$i" \
    > "$output/launch.log" 2>&1 < /dev/null &
  printf 'Adapter %s: frames [%s,%s), PID %s\n' "$i" "$start" "$end" "$!"
done

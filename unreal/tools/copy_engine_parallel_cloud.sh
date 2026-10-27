#!/usr/bin/env bash
# Transfer byte ranges over independent authenticated SSH connections.
set -euo pipefail
host="${1:?Destination host}"
port="${2:?Destination port}"
[[ "$host" =~ ^[a-zA-Z0-9.-]+$ && "$port" =~ ^[0-9]+$ ]] || exit 2
archive="${3:-$HOME/workspace/brickflow-cinematic/tools/Linux_Unreal_Engine_5.8.4.direct.zip}"
streams="${4:-8}"
[[ "$streams" =~ ^[0-9]+$ && "$streams" -ge 1 && "$streams" -le 32 ]] || exit 2
[[ "$archive" =~ ^[a-zA-Z0-9_./-]+$ ]] || exit 2
root=$(dirname "$archive")
ssh_args=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$HOME/.cache/brickflow-migration/known_hosts" -i "$HOME/.cache/brickflow-migration/id_ed25519" -p "$port" "shadeform@$host")
remote="$root/.engine-transfer-$(basename "$archive")"
ssh "${ssh_args[@]}" "mkdir -p '$remote'"
size=$(stat -c %s "$archive")
test "$size" -gt 0
blocks=$(((size+4194303)/4194304))
per=$(((blocks+streams-1)/streams))
streams=$(((blocks+per-1)/per))
pids=()
parts=''
for ((i=0;i<streams;i++)); do
  parts+=" '$remote/chunk-$i'"
  remaining=$((size-i*per*4194304))
  expected=$((per*4194304))
  if ((remaining<expected)); then expected=$remaining; fi
  test "$expected" -gt 0
  (
    for attempt in 1 2 3; do
      if ionice -c 3 nice -n 15 dd if="$archive" bs=4M skip="$((i*per))" count="$per" status=none |
        nice -n 15 ssh "${ssh_args[@]}" "cat > '$remote/chunk-$i.part' && test \$(stat -c %s '$remote/chunk-$i.part') -eq '$expected' && mv '$remote/chunk-$i.part' '$remote/chunk-$i'"; then exit 0; fi
      sleep 2
    done
    exit 1
  ) &
  pids+=("$!")
  # Avoid sshd MaxStartups drops while keeping authenticated transfers parallel.
  sleep .5
done
failed=false
for pid in "${pids[@]}"; do wait "$pid" || failed=true; done
[[ "$failed" == false ]]
ssh "${ssh_args[@]}" "cat $parts > '$archive.assembling' && test \$(stat -c %s '$archive.assembling') -eq '$size' && mv '$archive.assembling' '$archive'"
printf 'Archive transferred: %s bytes. Checksum/extraction verification follows.\n' "$size"

#!/usr/bin/env bash
# Transfer eight byte ranges over independent authenticated SSH connections.
set -euo pipefail
host="${1:?Destination host}"
port="${2:?Destination port}"
[[ "$host" =~ ^[a-zA-Z0-9.-]+$ && "$port" =~ ^[0-9]+$ ]] || exit 2
archive="${3:-$HOME/workspace/brickflow-cinematic/tools/Linux_Unreal_Engine_5.8.4.direct.zip}"
[[ "$archive" =~ ^[a-zA-Z0-9_./-]+$ ]] || exit 2
root=$(dirname "$archive")
ssh_args=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$HOME/.cache/brickflow-migration/known_hosts" -i "$HOME/.cache/brickflow-migration/id_ed25519" -p "$port" "shadeform@$host")
remote="$root/.engine-transfer"
ssh "${ssh_args[@]}" "mkdir -p '$remote'"
size=$(stat -c %s "$archive")
blocks=$(((size+4194303)/4194304))
per=$(((blocks+7)/8))
pids=()
for i in {0..7}; do
  (
    ionice -c 3 nice -n 15 dd if="$archive" bs=4M skip="$((i*per))" count="$per" status=none |
      nice -n 15 ssh "${ssh_args[@]}" "cat > '$remote/chunk-$i'"
  ) &
  pids+=("$!")
done
for pid in "${pids[@]}"; do wait "$pid"; done
ssh "${ssh_args[@]}" "cat '$remote/chunk-0' '$remote/chunk-1' '$remote/chunk-2' '$remote/chunk-3' '$remote/chunk-4' '$remote/chunk-5' '$remote/chunk-6' '$remote/chunk-7' > '$archive.assembling'; test \$(stat -c %s '$archive.assembling') -eq '$size'; mv '$archive.assembling' '$archive'"
printf 'Archive transferred: %s bytes. Checksum/extraction verification follows.\n' "$size"

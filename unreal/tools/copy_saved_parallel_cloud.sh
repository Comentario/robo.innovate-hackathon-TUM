#!/usr/bin/env bash
# Completed footage and history only; source renders must have closed first.
set -euo pipefail
root="$HOME/workspace"
state="$root/brickflow-native/Saved/Migration"
mkdir -p "$root/.migration" "$state"
trap 'echo failed > "$state/copy.status"' ERR
test -f "$root/brickflow-native/Saved/Films/continuous-4k-v4-delivery/delivery.status"
echo archiving-completed-artifacts > "$state/copy.status"
archive="$root/.migration/brickflow-saved.tar"
if [[ "${1:-}" != --reuse ]]; then
  ionice -c 3 nice -n 15 tar -cf "$archive" --exclude=Saved/Migration --exclude='*.pid' --exclude='transfer-*' \
    -C "$root/brickflow-native" Saved
fi
test -s "$archive"
echo transferring-completed-artifacts > "$state/copy.status"
bash "$HOME/.cache/brickflow-migration/copy-engine.sh" 65.108.33.125 22 "$archive" 32
echo extracting-completed-artifacts > "$state/copy.status"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$HOME/.cache/brickflow-migration/known_hosts" \
  -i "$HOME/.cache/brickflow-migration/id_ed25519" shadeform@65.108.33.125 \
  "tar -xf '$archive' -C '$root/brickflow-native'"
echo complete > "$state/copy.status"

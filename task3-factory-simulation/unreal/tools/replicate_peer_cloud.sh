#!/usr/bin/env bash
# Copy a verified four-GPU workspace to its independent peer; no film rendering.
set -euo pipefail
host="${1:?Destination IP}"
[[ "$host" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 2
root="$HOME/workspace"
state="$root/brickflow-native/Saved/Migration"
trap 'echo failed > "$state/jacob-copy.status"' ERR
python3 - "$state/final-verification.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]));assert p['verified'] and p['historyCopyComplete']
PY
export RSYNC_RSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.cache/brickflow-jacob-migration/known_hosts -i $HOME/.cache/brickflow-jacob-migration/id_ed25519"
destination="shadeform@$host"
echo software > "$state/jacob-copy.status"
rsync -a --partial --stats --exclude=/.migration/ --exclude='.engine-transfer*' \
  --exclude=/brickflow-native/Saved/ --exclude=/brickflow-cinematic/tools/unreal-5.8.4/ \
  "$root/" "$destination:$root/"
echo installing-engine-and-copying-history > "$state/jacob-copy.status"
$RSYNC_RSH "$destination" 'bash /tmp/install_engine_cloud.sh' > "$state/jacob-engine-install.log" 2>&1 &
engine_pid=$!
$RSYNC_RSH "$destination" '"$HOME/workspace/brickflow-cinematic/tools/python/bin/python" -m playwright install --with-deps chromium' \
  > "$state/jacob-browser-install.log" 2>&1 &
browser_pid=$!
rsync -a --partial --stats --exclude=Migration/ --exclude='*.pid' --exclude='transfer-*' \
  "$root/brickflow-native/Saved/" "$destination:$root/brickflow-native/Saved/"
wait "$engine_pid"
wait "$browser_pid"
echo complete > "$state/jacob-copy.status"

#!/usr/bin/env bash
# Run on source VM after installing dependencies/key/verified known_hosts on both ends.
set -euo pipefail
port="${1:?Supply destination SSH port}"
host="${2:-global.prd.ga.run.brev.nvidia.com}"
[[ "$port" =~ ^[0-9]+$ ]] || exit 2
[[ "$host" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 2
root="$HOME/workspace"
state="$root/brickflow-native/Saved/Migration"
mkdir -p "$state"
trap 'echo failed > "$state/copy.status"' ERR
export RSYNC_RSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.cache/brickflow-migration/known_hosts -i $HOME/.cache/brickflow-migration/id_ed25519 -p $port"
destination="shadeform@$host"
copy() { ionice -c 3 nice -n 15 rsync -a --whole-file --partial --bwlimit=80000 --stats "$@"; }
echo application > "$state/copy.status"
copy --exclude=Saved/ "$root/brickflow-native/" "$destination:$root/brickflow-native/"
echo engine-archive > "$state/copy.status"
bash "$HOME/.cache/brickflow-migration/copy-engine.sh" "$host" "$port"
echo engine-install > "$state/copy.status"
# Original checksum-verified owner-supplied distribution, same install paths.
$RSYNC_RSH "$destination" 'bash /tmp/install_engine_cloud.sh' > "$state/replica-engine-install.log" 2>&1
echo runtime-ready > "$state/copy.status"
copy --exclude=tools/unreal-5.8.4/ --exclude=tools/Linux_Unreal_Engine_5.8.4.direct.zip \
  "$root/brickflow-cinematic/" "$destination:$root/brickflow-cinematic/"
copy --exclude=Films/continuous-4k-v4* --exclude=Migration/ --exclude='*.pid' \
  "$root/brickflow-native/Saved/" "$destination:$root/brickflow-native/Saved/"
echo waiting-for-active-render > "$state/copy.status"
while [[ ! -f "$root/brickflow-native/Saved/Films/continuous-4k-v4-delivery/delivery.status" ]]; do sleep 30; done
echo completed-render > "$state/copy.status"
for directory in "$root"/brickflow-native/Saved/Films/continuous-4k-v4*; do
  [[ -d "$directory" ]] || continue
  copy --exclude='transfer-*' "$directory" "$destination:$root/brickflow-native/Saved/Films/"
done
echo complete > "$state/copy.status"

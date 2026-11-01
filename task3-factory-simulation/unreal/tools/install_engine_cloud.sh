#!/usr/bin/env bash
set -euo pipefail
task_root="$HOME/workspace/brickflow-cinematic"
archive="$task_root/tools/Linux_Unreal_Engine_5.8.4.direct.zip"
engine="$task_root/tools/unreal-5.8.4"
mkdir -p "$task_root/logs" "$engine"
exec > >(tee -a "$task_root/logs/unreal-install.log") 2>&1
python3 - "$archive" <<'PY'
from pathlib import Path
import hashlib,sys
p=Path(sys.argv[1]);digest=hashlib.sha256()
with p.open('rb') as source:
    for block in iter(lambda:source.read(16*1024*1024),b''):digest.update(block)
expected='cdff1e0c02010eb4fcf9c38d293cfd0f1afda09272256c146d73db52f570f607'
if digest.hexdigest()!=expected:raise SystemExit('Unreal archive differs from the owner-provided ZIP')
print('Unreal archive SHA-256 matches the original local ZIP',flush=True)
PY
unzip -q -o "$archive" -d "$engine"
python3 - "$engine" <<'PY'
import json,sys,pathlib
root=pathlib.Path(sys.argv[1]);v=json.loads((root/'Engine/Build/Build.version').read_text())
assert (v['MajorVersion'],v['MinorVersion'],v['PatchVersion'])==(5,8,4)
assert (root/'Engine/Binaries/Linux/UnrealEditor').is_file()
print('Installed Unreal Engine',v['MajorVersion'],v['MinorVersion'],v['PatchVersion'],flush=True)
PY
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
printf '\nNative Unreal installation ready: %s\n' "$engine"

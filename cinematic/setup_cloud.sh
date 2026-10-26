#!/usr/bin/env bash
# Run through: brev exec brickflow-cinematic @cinematic/setup_cloud.sh
set -euo pipefail
task_root="$HOME/workspace/brickflow-cinematic"
mkdir -p "$task_root/tools" "$task_root/logs" "$task_root/renders"
exec > >(tee -a "$task_root/logs/setup.log") 2>&1
nvidia-smi
sudo -n apt-get update
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl xz-utils unzip ffmpeg python3-venv \
  libxrender1 libxi6 libxkbcommon0 libsm6 libgl1 libegl1 libxfixes3 \
  libxxf86vm1 libxrandr2 libvulkan1 vulkan-tools xvfb xauth
cd "$task_root/tools"
version=4.5.3
archive="blender-${version}-linux-x64.tar.xz"
if [[ ! -x "blender-${version}-linux-x64/blender" ]]; then
  curl --fail --location --retry 3 \
    "https://download.blender.org/release/Blender4.5/$archive" -o "$archive"
  curl --fail --location --retry 3 \
    "https://download.blender.org/release/Blender4.5/blender-${version}.sha256" -o blender.sha256
  python3 - "$archive" <<'PY'
import hashlib, pathlib, sys
archive = pathlib.Path(sys.argv[1])
entries = [line.split() for line in pathlib.Path('blender.sha256').read_text().splitlines()]
expected = next(parts[0] for parts in entries if parts[-1].lstrip('*') == archive.name)
with archive.open('rb') as source:
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024*1024), b''):
        digest.update(block)
if digest.hexdigest() != expected:
    raise SystemExit('Blender archive checksum mismatch')
print('Official Blender SHA-256 verified')
PY
  tar -xf "$archive"
fi
"$task_root/tools/blender-${version}-linux-x64/blender" --version
python3 -m venv "$task_root/tools/python"
"$task_root/tools/python/bin/pip" install playwright==1.64.1
"$task_root/tools/python/bin/python" -m playwright install --with-deps chromium
printf '\nCloud rendering tools ready: %s\n' "$task_root"

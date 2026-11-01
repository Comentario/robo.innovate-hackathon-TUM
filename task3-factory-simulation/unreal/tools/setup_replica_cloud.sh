#!/usr/bin/env bash
# Install system dependencies only; copy the owner's engine from the source VM.
set -euo pipefail
sudo -n apt-get update
asound=libasound2
if apt-cache show libasound2t64 >/dev/null 2>&1; then asound=libasound2t64; fi
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl xz-utils unzip ffmpeg python3-venv rsync zstd \
  libxrender1 libxi6 libxkbcommon0 libsm6 libgl1 libegl1 libxfixes3 \
  libxxf86vm1 libxrandr2 libvulkan1 vulkan-tools xvfb xauth \
  "$asound" libnss3 libatk1.0-0 libgbm1 openbox x11vnc novnc websockify
mkdir -p "$HOME/workspace/brickflow-native/Saved/Migration"
nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version --format=csv
test "$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)" -eq 4
printf 'Four-GPU system dependencies ready.\n'

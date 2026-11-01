#!/usr/bin/env bash
# Lightweight download/install only. No simulator or compiler is started.
set -euo pipefail
cd "$(dirname "$0")/.."
ISAAC_PYTHON="${ISAAC_PYTHON:-/home/faps/miniforge3/envs/unitree_sim_env/bin/python}"
WHEEL='bricksim-0.1.0.dev645+gcbd5de3-cp311-cp311-linux_x86_64.whl'
mkdir -p downloads
curl --fail --location "https://dl.cloudsmith.io/public/bricksim/bricksim/python/$WHEEL" -o "downloads/$WHEEL"
echo "145e7d838ef8f7ad5f848a5633492b57f5f894a7e9a3dfe7812767c7194af8fb  downloads/$WHEEL" | sha256sum --check
"$ISAAC_PYTHON" -m pip install --no-deps --target .deps "downloads/$WHEEL"

#!/usr/bin/env bash
set -euo pipefail
project=/home/vjhannox/hackathon/robo.innovate-hackathon-TUM
mkdir -p "$HOME/.config/systemd/user" "$project/artifacts/unreal_night37"
cp "$project/unreal/deploy/brickflow-final37-delivery.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now brickflow-final37-delivery.service
systemctl --user status --no-pager brickflow-final37-delivery.service

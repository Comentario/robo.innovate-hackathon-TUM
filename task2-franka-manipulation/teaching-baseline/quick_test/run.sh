#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  --cameras)
    timeout 25s /usr/bin/python3 -s quick_test/cameras.py | tee quick_test/camera_capture.log
    ;;
  --preview|--execute)
    source /opt/ros/humble/setup.bash
    g++ -std=c++17 -O2 -Wall -Wextra \
      -I/home/nshenoy/franka_diagnostics/libfranka/include \
      -I/home/nshenoy/franka_diagnostics/libfranka/common/include \
      quick_test/joints.cpp -L/home/nshenoy/franka_diagnostics/build \
      -Wl,-rpath,/home/nshenoy/franka_diagnostics/build -lfranka -o quick_test/joints
    log="quick_test/joints_$(date -u +%Y%m%dT%H%M%SZ).log"
    ./quick_test/joints "$1" 2>&1 | tee "$log"
    ;;
  *) echo 'Usage: bash quick_test/run.sh --cameras|--preview|--execute'; exit 2 ;;
esac

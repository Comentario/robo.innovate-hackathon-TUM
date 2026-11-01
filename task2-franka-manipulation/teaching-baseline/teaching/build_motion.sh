#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/humble/setup.bash
set -u
franka_root=/home/nshenoy/franka_diagnostics
for helper in read_pose joint_move arc_move move_xyz gripper_width; do
  g++ -std=c++17 -O2 -Wall -Wextra -Wno-maybe-uninitialized \
    -I/usr/include/eigen3 -I"$franka_root/libfranka/include" \
    -I"$franka_root/libfranka/common/include" \
    "teaching/$helper.cpp" -L"$franka_root/build" \
    -Wl,-rpath,"$franka_root/build" -lfranka -pthread -o "teaching/$helper"
done

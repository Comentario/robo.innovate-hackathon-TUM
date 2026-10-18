#!/usr/bin/env bash
set -e
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Only this subprocess is reset; no old workspace is sourced or changed.
exec env -u AMENT_PREFIX_PATH -u CMAKE_PREFIX_PATH -u COLCON_PREFIX_PATH \
  -u PYTHONPATH -u LD_LIBRARY_PATH \
  ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1 ROS_LOG_DIR=/tmp/munich-ros-logs \
  PYTHONDONTWRITEBYTECODE=1 bash --noprofile --norc -c '
    source /opt/ros/humble/setup.bash
    if [ "${1:-}" = rviz ]; then
      exec rviz2 -d ros_bridge/pallet.rviz
    elif [ "${1:-}" = test ]; then
      exec python3 -m unittest discover -s tests_ros -v
    else
      exec python3 -m ros_bridge "$@"
    fi
  ' -- "$@"

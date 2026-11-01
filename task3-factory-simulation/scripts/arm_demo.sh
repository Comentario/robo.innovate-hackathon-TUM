#!/usr/bin/env bash
set -e
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec env -u AMENT_PREFIX_PATH -u CMAKE_PREFIX_PATH -u COLCON_PREFIX_PATH -u PYTHONPATH -u LD_LIBRARY_PATH \
  RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS ROS_DOMAIN_ID=88 ROS_LOCALHOST_ONLY=1 ROS_LOG_DIR=/tmp/munich-arm-logs PYTHONDONTWRITEBYTECODE=1 \
  bash --noprofile --norc -c '
    source /opt/ros/humble/setup.bash
    prefix="$PWD/.deps/moveit"
    overlay="$prefix/opt/ros/humble"
    if [ ! -d "$overlay/share/moveit_ros_move_group" ]; then
      echo "Run python3 scripts/install_local_moveit.py first." >&2; exit 1
    fi
    export AMENT_PREFIX_PATH="$overlay:$AMENT_PREFIX_PATH"
    export LD_LIBRARY_PATH="$overlay/lib:$overlay/lib/x86_64-linux-gnu:$prefix/usr/lib/x86_64-linux-gnu:$prefix/usr/lib/llvm-14/lib:${LD_LIBRARY_PATH:-}"
    export PYTHONPATH="$overlay/local/lib/python3.10/dist-packages:$overlay/lib/python3.10/site-packages:$prefix/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
    export PATH="$overlay/bin:$PATH"
    export LIBGL_ALWAYS_SOFTWARE="${MUNICH_RVIZ_SOFTWARE:-1}" QT_QPA_PLATFORM=xcb QT_X11_NO_MITSHM=1
    if [ "${1:-}" = launch ]; then
      shift
      exec flock -w 10 -o /tmp/munich-arm-server-88.lock ros2 launch arm_bridge/reference.launch.py "$@"
    fi
    if [ "${1:-}" = test ]; then
      exec python3 -m unittest discover -s tests_arm -v
    fi
    if [ "${1:-}" = recovery ]; then
      shift
      exec flock -n -o /tmp/munich-arm-client-88.lock python3 -m arm_bridge.recovery_demo "$@"
    fi
    exec flock -n -o /tmp/munich-arm-client-88.lock python3 -m arm_bridge "$@"
  ' -- "$@"

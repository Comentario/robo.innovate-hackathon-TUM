# Test perception with ROS 2 Humble

Follow **1 → 2 → 3** using **three Ubuntu/WSL terminals**. Copy each complete
block into the indicated terminal. This test uses a dataset image with six
bricks; no camera is needed.

Stop any previous perception node or inventory echo with **Ctrl+C** first.
Leave terminals 1 and 2 running while using terminal 3.

## 1. Terminal 1 — build and start perception

```bash
cd ~/robo.innovate-hackathon-TUM/robo.innovate-hackathon-TUM
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select marmon_perception
source install/setup.bash
export ROS_DOMAIN_ID=87
export FASTRTPS_DEFAULT_PROFILES_FILE="$PWD/ros2/marmon_perception/config/fastdds_images.xml"
ros2 run marmon_perception perception_node --ros-args \
  -p detector_mode:=pallet \
  -p background_path:="$PWD/data/images/zenodo_detection/background_empty.png"
```

What the commands do:

- `cd`: enter this repository. Adjust the path if you moved it.
- First `source`: enable ROS 2 in this terminal.
- `colcon build`: build/install perception. Continue only if it succeeds.
- Second `source`: make the built package available to ROS.
- `ROS_DOMAIN_ID`: use the same ROS communication domain in all terminals.
- `FASTRTPS_DEFAULT_PROFILES_FILE`: load transport settings for large images.
- `ros2 run`: start perception with the empty-pallet reference.

**Wait until you see `Perception ready in pallet mode`.**
The terminal remains occupied: the node is waiting for an image.
Open terminal 2 without stopping terminal 1.

## 2. Terminal 2 — listen for the inventory

```bash
cd ~/robo.innovate-hackathon-TUM/robo.innovate-hackathon-TUM
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=87
export FASTRTPS_DEFAULT_PROFILES_FILE="$PWD/ros2/marmon_perception/config/fastdds_images.xml"
ros2 topic echo /perception/inventory std_msgs/msg/String
```

This listens for the JSON inventory published by perception.
**No output is expected yet:** we have not sent an image.
Keep the command running and open terminal 3.

## 3. Terminal 3 — send one image

First prepare this terminal:

```bash
cd ~/robo.innovate-hackathon-TUM/robo.innovate-hackathon-TUM
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=87
export FASTRTPS_DEFAULT_PROFILES_FILE="$PWD/ros2/marmon_perception/config/fastdds_images.xml"
```

Then copy this **entire block**, including the final `PY` on its own line:

```bash
python3 - <<'PY'
import time
import cv2
import rclpy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from rclpy.qos import qos_profile_sensor_data

rclpy.init()
node = rclpy.create_node('dataset_image_source')
publisher = node.create_publisher(Image, '/camera/image_raw', qos_profile_sensor_data)
image = cv2.imread('data/images/zenodo_detection/bricks_06.png')
assert image is not None, 'Cannot read dataset image'
deadline = time.monotonic() + 15
while publisher.get_subscription_count() == 0:
    if time.monotonic() > deadline:
        raise RuntimeError('No image subscriber discovered')
    rclpy.spin_once(node, timeout_sec=0.1)
message = CvBridge().cv2_to_imgmsg(image, encoding='bgr8')
message.header.stamp = node.get_clock().now().to_msg()
message.header.frame_id = 'dataset_camera'
publisher.publish(message)
print('Published bricks_06.png. Check terminals 1 and 2.')
time.sleep(1)
node.destroy_node()
rclpy.shutdown()
PY
```

This temporary Python program reads `bricks_06.png`, waits for perception,
then publishes one ROS image and exits. It does not create a file or
implement the future camera driver.

## 4. Check the result and stop

- **Terminal 1:** a log line includes `6 bricks, color_estimated`.
- **Terminal 2:** JSON appears in `data`, with six entries in `bricks` and
  `processing_status` equal to `color_estimated`.
- **Terminal 3:** prints `Published bricks_06.png. Check terminals 1 and 2.`

There is no image window: this test checks image transport and JSON output.
No inventory files are written automatically.

Press **Ctrl+C** in terminals 1 and 2 when finished. To repeat the test, keep
those terminals running and execute only the Python block in terminal 3 again.

## If something does not work

| Symptom | What to check |
| --- | --- |
| `ros2: command not found` | Load `/opt/ros/humble/setup.bash` in that Ubuntu terminal. |
| Package not found | Check that the build succeeded, then load `install/setup.bash`. |
| Cannot read an image | Check the `cd` path and files under `data/images/zenodo_detection/`. |
| No image subscriber discovered | Terminal 1 must show that perception is ready. Use the same ROS domain in every terminal. |
| No inventory arrives | Start terminal 2 before sending the image. Load the transport profile in every terminal before starting ROS processes. Check terminal 1 for errors. |

## Node reference

The package lives in `ros2/marmon_perception/`. Its `perception` symlink reuses
the existing Python code. The node calls `pipeline.run_perception` for detection,
relative color estimation, and inventory construction.

| Setting | Value |
| --- | --- |
| Input | `/camera/image_raw`, `sensor_msgs/msg/Image` |
| Output | `/perception/inventory`, JSON in `std_msgs/msg/String.data` |
| Input QoS | Best effort, volatile, keep last 1 |
| Output QoS | Reliable, volatile, keep last 1 |
| `detector_mode` | `pallet` (default) or experimental `wall` |
| `background_path` | Required in `pallet` mode; unused in `wall` mode |

Both parameters are read-only after startup. Restart the node to change them.
Topic names support ROS remapping. The inventory contract is documented in
[interfaces.md](../interfaces.md). Brick IDs are scoped to each image, and
relative color labels are not absolute material names.

A recognized empty pallet returns an empty inventory. Fewer than three valid
color measurements return `color_inconclusive`. Failed frames are logged and
produce no inventory; the node continues waiting for images.

The Fast DDS profile uses a 16 MiB shared-memory segment. It resolved delivery
of the approximately 1.46 MB dataset images in our local tests. See the
[Fast DDS transport documentation](https://fast-dds.docs.eprosima.com/en/2.6.x/fastdds/transport/shared_memory/shared_memory.html).
Other middleware or remote networks may require different settings.

Build artifacts and local results under `build/`, `install/`, `log/`, and
`outputs/` are ignored by Git.

## Optional — automated checks

After stopping terminals 1 and 2, run this in the already prepared terminal 3:

```bash
mkdir -p outputs/ros_test
ROS_LOG_DIR="$PWD/outputs/ros_test/log" \
  python3 -m pytest ros2/marmon_perception/test -v \
  --basetemp=outputs/ros_test/tmp -o cache_dir=outputs/ros_test/cache
```

Expected: **2 passed**. Checks cover ROS transport, invalid-frame recovery,
empty/two/six-brick results, and invalid startup configuration.

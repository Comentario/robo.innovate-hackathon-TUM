"""Exercise the installed executable through real ROS image and JSON topics.

Run after building, sourcing the workspace, and loading fastdds_images.xml:
ROS_DOMAIN_ID=87 python3 -m pytest ros2/marmon_perception/test -v
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from std_msgs.msg import String
from rclpy.qos import qos_profile_sensor_data


ROOT = Path(__file__).resolve().parents[3]
IMAGES = ROOT / "data/images/zenodo_detection"


def test_installed_node_transport_and_recovery(tmp_path):
    rclpy.init()
    client = rclpy.create_node("perception_transport_test")
    publisher = client.create_publisher(Image, "/camera/image_raw", qos_profile_sensor_data)
    received = []
    subscription = client.create_subscription(
        String, "/perception/inventory", lambda msg: received.append(json.loads(msg.data)), 1,
    )
    bridge = CvBridge()

    def wait_until(predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert process.poll() is None, "Perception process exited unexpectedly"
            assert time.monotonic() < deadline, "Timed out waiting for ROS communication"
            rclpy.spin_once(client, timeout_sec=0.1)

    with (tmp_path / "perception.log").open("w") as log:
        process = subprocess.Popen(
            ["ros2", "run", "marmon_perception", "perception_node", "--ros-args",
             "-p", "detector_mode:=pallet", "-p",
             f"background_path:={IMAGES / 'background_empty.png'}"],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            wait_until(lambda: publisher.get_subscription_count() > 0)
            wait_until(lambda: client.count_publishers("/perception/inventory") > 0)
            # Allow endpoint discovery on both sides before a one-shot frame.
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                rclpy.spin_once(client, timeout_sec=0.1)
            invalid = Image(height=1, width=1, encoding="invalid_encoding", step=1, data=[0])
            publisher.publish(invalid)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                rclpy.spin_once(client, timeout_sec=0.1)
            assert not received, "Invalid frame must not publish an empty inventory"

            for name, count, status in (
                ("background_empty", 0, "color_inconclusive"),
                ("bricks_02", 2, "color_inconclusive"),
                ("bricks_06", 6, "color_estimated"),
            ):
                message = bridge.cv2_to_imgmsg(cv2.imread(str(IMAGES / f"{name}.png")), "bgr8")
                message.header.stamp = client.get_clock().now().to_msg()
                previous = len(received)
                publisher.publish(message)
                wait_until(lambda: len(received) > previous)
                inventory = received[-1]
                assert len(inventory["bricks"]) == count
                assert inventory["processing_status"] == status
                assert inventory["schema_version"] == "0.2"
                assert inventory["image_id"].startswith(
                    f"image_{message.header.stamp.sec}_{message.header.stamp.nanosec:09d}_"
                )
                if name == "bricks_02":
                    assert all(b["color_group"] == "unknown" and b["color_score"] == 0.0
                               for b in inventory["bricks"])
        finally:
            # Signal the process group, including the executable started by ros2 run.
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            client.destroy_subscription(subscription)
            client.destroy_node()
            rclpy.shutdown()


def test_invalid_configuration_exits():
    result = subprocess.run(
        ["ros2", "run", "marmon_perception", "perception_node", "--ros-args",
         "-p", "detector_mode:=invalid"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "detector_mode must be 'pallet' or 'wall'" in result.stderr

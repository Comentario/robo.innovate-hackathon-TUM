"""ROS transport for the existing in-memory perception pipeline."""

import json
from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String

from perception.pipeline import run_perception


class PerceptionNode(Node):
    """Process incoming images sequentially and publish JSON inventories."""

    def __init__(self, **kwargs):
        super().__init__("perception", **kwargs)
        self.declare_parameter(
            "detector_mode", "pallet",
            ParameterDescriptor(read_only=True, description="Detector: pallet or wall"),
        )
        self.declare_parameter(
            "background_path", "",
            ParameterDescriptor(read_only=True, description="Empty-pallet reference image"),
        )
        self.detector_mode = self.get_parameter("detector_mode").value
        if self.detector_mode not in ("pallet", "wall"):
            raise ValueError("detector_mode must be 'pallet' or 'wall'")
        self.background = None
        if self.detector_mode == "pallet":
            path = self.get_parameter("background_path").value
            if not path:
                raise ValueError("background_path is required in pallet mode")
            self.background = cv2.imread(str(Path(path).expanduser()))
            if self.background is None:
                raise ValueError(f"Cannot read background image: {path}")

        self.bridge = CvBridge()
        self.image_count = 0
        self.inventory_publisher = self.create_publisher(
            String, "/perception/inventory",
            QoSProfile(
                history=HistoryPolicy.KEEP_LAST, depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            ),
        )
        self.image_subscription = self.create_subscription(
            Image, "/camera/image_raw", self.process_image,
            QoSProfile(
                history=HistoryPolicy.KEEP_LAST, depth=1,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            ),
        )
        self.get_logger().info(f"Perception ready in {self.detector_mode} mode")

    def process_image(self, message: Image) -> None:
        self.image_count += 1
        stamp = message.header.stamp
        image_id = f"image_{stamp.sec}_{stamp.nanosec:09d}_{self.image_count}"
        try:
            image = self.bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
            inventory, _ = run_perception(
                image, image_id, self.detector_mode, self.background,
            )
            payload = json.dumps(inventory, allow_nan=False)
        except Exception as exc:
            # A failed frame must not be reported as an empty pallet.
            self.get_logger().error(f"Failed to process {image_id}: {exc}")
            return
        self.inventory_publisher.publish(String(data=payload))
        self.get_logger().info(
            f"Published {image_id}: {len(inventory['bricks'])} bricks, "
            f"{inventory['processing_status']}"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = PerceptionNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as exc:
        rclpy.logging.get_logger("perception").error(f"Perception stopped: {exc}")
        raise
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

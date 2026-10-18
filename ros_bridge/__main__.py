"""Run the optional ROS 2 inventory-to-plan-to-RViz preview, without hardware."""
import argparse
import json
import math
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', default='examples/faces/inventory.json')
    parser.add_argument('--config', default='examples/faces/config.json')
    parser.add_argument('--per-brick', action='store_true', help='Use legacy per-brick shades instead of observed faces')
    parser.add_argument('--fail-step', type=int)
    parser.add_argument('--period', type=float, default=.8)
    args = parser.parse_args()
    if not math.isfinite(args.period) or args.period <= 0:
        parser.error('--period must be positive')
    if args.fail_step is not None and args.fail_step <= 0:
        parser.error('--fail-step must be positive')
    try:
        request = dict(inventory=json.loads(Path(args.inventory).read_text()),
                       config=json.loads(Path(args.config).read_text()), face_aware=not args.per_brick)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    # Only this optional demo process sets transport defaults; never alter shell setup.
    os.environ.setdefault('ROS_DOMAIN_ID', '87')
    os.environ.setdefault('ROS_LOCALHOST_ONLY', '1')
    try:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from std_msgs.msg import String
        from .nodes import PlannerNode, PreviewNode, retained_qos, string_message
    except ImportError:
        parser.error('ROS 2 is optional. Source /opt/ros/humble/setup.bash before running this adapter.')
    rclpy.init(args=[])
    planner = PlannerNode()
    preview = PreviewNode(period=args.period, fail_step=args.fail_step)
    source = rclpy.create_node('brick_fixture_source')
    publisher = source.create_publisher(String, '/munich_demo/inventory_request', retained_qos())
    executor = SingleThreadedExecutor()
    for node in (planner, preview, source):
        executor.add_node(node)
    publisher.publish(string_message(request))
    print('SIMULATION ONLY | ROS 2 adapter | no arm or robot commands', flush=True)
    print('Topics: /munich_demo/inventory_request → /munich_demo/plan → /munich_demo/markers and /munich_demo/events', flush=True)
    print('RViz: Fixed Frame = world; MarkerArray topic = /munich_demo/markers', flush=True)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        for node in (planner, preview, source):
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

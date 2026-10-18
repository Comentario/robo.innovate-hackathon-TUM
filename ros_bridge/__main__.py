"""Run the optional ROS 2 inventory-to-plan-to-RViz preview, without hardware."""
import argparse
import json
import math
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', help='Canonical perception snapshot; overrides legacy inventory flags')
    parser.add_argument('--state', help='Optional durable cell journal; requires --snapshot and --cell')
    parser.add_argument('--inventory', default='examples/faces/inventory.json')
    parser.add_argument('--config', default='examples/faces/config.json')
    parser.add_argument('--cell', help='Optional synthetic cell layout with pick/place action acknowledgements')
    parser.add_argument('--fail-phase', choices=['approach_pick','pick','lift','orient','approach_place','place','confirm','retreat'], default='pick')
    parser.add_argument('--unknown', action='store_true', help='Inject an uncertain action outcome in cell mode')
    parser.add_argument('--per-brick', action='store_true', help='Use legacy per-brick shades instead of observed faces')
    parser.add_argument('--fail-step', type=int)
    parser.add_argument('--period', type=float, default=.8)
    args = parser.parse_args()
    if not math.isfinite(args.period) or args.period <= 0:
        parser.error('--period must be positive')
    if args.fail_step is not None and args.fail_step <= 0:
        parser.error('--fail-step must be positive')
    if not args.cell and (args.unknown or args.fail_phase != 'pick'):
        parser.error('--unknown and phase-specific failures require --cell')
    if args.state and (not args.cell or not args.snapshot):
        parser.error('--state requires --snapshot and --cell')
    if args.snapshot and args.per_brick:
        parser.error('face mode is declared by the snapshot')
    try:
        cell_config = json.loads(Path(args.cell).read_text()) if args.cell else None
        request = dict(config=json.loads(Path(args.config).read_text()))
        if args.snapshot:
            from integration.intake import normalize_snapshot,execution_source_poses
            snapshot=normalize_snapshot(json.loads(Path(args.snapshot).read_text()))
            request.update(inventory=snapshot['items'],face_aware=snapshot['face_aware'],snapshot=snapshot)
            if cell_config is not None:request['source_poses']=execution_source_poses(snapshot,cell_config)
        else:
            request.update(inventory=json.loads(Path(args.inventory).read_text()),face_aware=not args.per_brick)
    except (OSError, ValueError,KeyError,TypeError) as error:
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
    if cell_config is not None:
        from execution.cell import CellLayout
        try:
            if CellLayout(cell_config).frame != 'world':
                raise ValueError('ROS cell preview requires a world-frame layout')
        except (ValueError,KeyError,TypeError) as error:
            parser.error(str(error))
    journal=None
    if args.state:
        from integration.journal import Journal
        Path(args.state).parent.mkdir(parents=True,exist_ok=True)
        journal=Journal(args.state)
    rclpy.init(args=[])
    planner = PlannerNode()
    if cell_config is not None:
        from .cell_node import CellExecutionNode
        preview = CellExecutionNode(cell_config, period=args.period, fail_step=args.fail_step,
                                    fail_phase=args.fail_phase,unknown=args.unknown,journal=journal)
    else:
        preview = PreviewNode(period=args.period, fail_step=args.fail_step)
    source = rclpy.create_node('brick_fixture_source')
    publisher = source.create_publisher(String, '/munich_demo/inventory_request', retained_qos())
    executor = SingleThreadedExecutor()
    for node in (planner, preview, source):
        executor.add_node(node)
    publisher.publish(string_message(request))
    print('SIMULATION ONLY | ROS 2 adapter | no arm or robot commands', flush=True)
    if getattr(preview,'view_only',False):
        print(f'Checkpoint loaded: {preview.loaded_run_id} | view only; no actions will be replayed',flush=True)
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
        if journal is not None:journal.close()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

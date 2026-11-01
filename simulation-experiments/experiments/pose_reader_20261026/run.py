"""Startup-only probe in the frozen failed workcell; no task control."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-reader', action='store_true')
    args, remainder = parser.parse_known_args()
    sys.argv = [sys.argv[0], '--output', str(args.output), *remainder]
    from experiments.control_alignment_20261026 import run_sim as initializer
    from experiments.control_alignment_20261026 import batched_source as readers
    protocol = json.loads((ROOT/'experiments/pose_reader_20261026/protocol.json').read_text())
    original_reader = readers.BatchedSourcePoses

    def forbidden(*args, **kwargs):
        raise RuntimeError('Task control is forbidden in the pose-reader probe')

    # These constructors are reached only AFTER the reader startup hook.
    initializer.IsaacIO = initializer.JointExecutor = initializer.SharedStack = forbidden

    def capture(scene, names):
        from isaaclab.sim import SimulationContext
        from bricksim.core import compute_connected_component
        sim = SimulationContext.instance()
        out = args.output
        robot = scene['robot']
        arm = [robot.joint_names.index(f'fr3_joint{i}') for i in range(1, 8)]

        def state():
            parts, links = compute_connected_component('/World/envs/env_0/plate_source')
            return {'native_parts_paths': sorted(map(str, parts)),
                'native_connections_paths': sorted(map(str, links)),
                'arm_joint_positions': robot.root_physx_view.get_dof_positions()[0, arm].cpu().numpy().tolist(),
                'physics_time_s': float(sim.current_time),
                'physics_step_index': int(sim.current_time_step_index)}

        before = state()
        proof = readers.capture_startup_comparison(scene, names,
            lambda: float(sim.current_time),
            evidence_sink=lambda packet: write(out/'partial_capture.json', packet))
        after = state()
        write(out/'capture.json', {'pose_readers': proof, 'scene_before': before, 'scene_after': after,
            'control_commands': 0, 'initialized_bricks': len(names),
            'initializer_source_snapshot': protocol['initializer_source_snapshot'],
            'manifest_sha256': hashlib.sha256((ROOT/'manifest.json').read_bytes()).hexdigest()})
        if args.verify_reader:
            try:
                reader = original_reader(scene, names)
            except BaseException as error:
                write(out/'reader_failure.json', {'type': type(error).__name__, 'reason': str(error),
                    'proof': getattr(error, 'proof', None), 'control_commands': 0})
                raise
            reader.proof.update(clock_before_s=after['physics_time_s'], clock_after_s=float(sim.current_time))
            initial = {'names': reader.names, 'poses_world_wxyz': reader.read().tolist()}
            write(out/'reader_confirmation.json', {'proof': reader.proof, 'initial': initial,
                'physics_time_before_s': after['physics_time_s'],
                'physics_time_after_s': float(sim.current_time),
                'physics_step_before': after['physics_step_index'],
                'physics_step_after': int(sim.current_time_step_index), 'control_commands': 0})
        write(out/'capture_complete.json', {'captured': True, 'reader_verified': args.verify_reader,
            'control_commands': 0, 'scope': 'Same-step reader compatibility only'})
        if args.verify_reader:
            # Audit saved evidence before teardown, which timed out in capture1838.
            # This foreground child remains within the SAME finite Pueue job.
            subprocess.run([sys.executable, str(ROOT/'experiments/pose_reader_20261026/evaluate.py'),
                '--input', str(out/'capture.json'), '--output', str(ROOT/'audit')], check=True)
            print('POSE_READER_CLASS_AUDIT_SAVED_BEFORE_SHUTDOWN', flush=True)
        raise initializer.ControlOnlyComplete()

    readers.BatchedSourcePoses = capture
    initializer.main()
    write(args.output/'process_complete.json', {'normal_shutdown': True, 'control_commands': 0})


if __name__ == '__main__':
    main()

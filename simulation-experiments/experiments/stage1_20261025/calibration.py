"""Configured synthetic calibration, with no saved simulator truth input."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.sim_pose_20261024.calibration import configured_calibration

CAMERAS = {'camera_0': 'diagnostic_table_top', 'camera_1': 'diagnostic_oblique'}


def build(geometry, cameras):
    result = configured_calibration(geometry, cameras)
    result['views'] = {key: result['views'][name] for key, name in CAMERAS.items()}
    result['pose_frame'] = 'table: source plate center; +X target, +Y bowl, +Z up'
    result['depth_encoding'] = 'distance_to_image_plane: axial optical Z in meters'
    result['source'] = 'Configured full-design camera reference and presets only; no measured or simulator-state calibration'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--cameras', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(args.geometry, args.cameras), indent=2)+'\n')

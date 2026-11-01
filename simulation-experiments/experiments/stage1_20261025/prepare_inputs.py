"""Queued sensor-only packaging; private source/state mapping is not copied."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def main():
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Sensor preparation requires default Pueue')
    root = Path(__file__).resolve().parent
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.calibration, args.output/'calibration.json')
    shutil.copytree(root/'upstream', args.output/'upstream', ignore=shutil.ignore_patterns('__pycache__'))
    frozen = json.loads((root/'upstream_hashes.json').read_text())
    for name, digest in frozen.items():
        if hashlib.sha256((args.output/'upstream'/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen R3 source/config changed: '+name)
    depth_config = json.loads((args.output/'upstream/depth_config.json').read_text())
    depth_config['source_roi_world_xy_m'] = {'x': [-.128, .128], 'y': [-.128, .128]}
    (args.output/'upstream/depth_config_runtime.json').write_text(json.dumps(depth_config, indent=2)+'\n')
    frames = []
    for row in json.loads(args.sources.read_text()):
        identity = row['id']
        if not identity.isalnum() or any(f['id'] == identity for f in frames):
            raise ValueError('Frame IDs must be unique opaque alphanumeric tokens')
        folder = args.output/'sensors'/identity
        folder.mkdir(parents=True)
        shutil.copy2(row['rgb_source'], folder/'rgb.png')
        operation = row.get('operation')
        if operation is None:
            shutil.copy2(row['depth_source'], folder/'depth.npy')
        else:
            depth = np.load(row['depth_source'], allow_pickle=False)
            if operation == 'all_depth_NaN':
                depth = np.full_like(depth, np.nan)
            elif operation == 'depth_patch_NaN':
                depth = depth.copy()
                x0, y0, x1, y1 = row['pixel_xyxy']
                depth[y0:y1, x0:x1] = np.nan
            else:
                raise ValueError('Unknown frozen sensor control')
            np.save(folder/'depth.npy', depth)
        frames.append({'id': identity, 'camera': row['camera'],
            'rgb': str((folder/'rgb.png').relative_to(args.output)),
            'depth': str((folder/'depth.npy').relative_to(args.output))})
    (args.output/'frames.json').write_text(json.dumps(frames, indent=2)+'\n')
    hashes = {str(path.relative_to(args.output)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in args.output.rglob('*') if path.is_file()}
    (args.output/'input_hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    print('SENSOR_PACKAGE_READY', len(frames), flush=True)


if __name__ == '__main__':
    main()

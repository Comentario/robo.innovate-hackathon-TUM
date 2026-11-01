"""Frozen R3 sensor adapter. Inputs contain no simulator state or references."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

from challenge1_mock import fixtures


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_contract(candidate):
    return {'candidate_id': candidate['id'], 'decision': candidate['decision'],
        'image_polygon': candidate['polygon'], 'box_xyxy': candidate['box_xyxy'],
        'table_xy_m': candidate['center_world_xy_m'],
        'estimated_body_top_from_selected_band_m': candidate['surface_height_world_m'],
        'yaw_table_rad': candidate['yaw_world_rad'],
        'uncertainty': {'kind': 'uncalibrated_evidence', 'metric_covariance': None,
            'reason_flags': candidate['reason_flags'], 'support': candidate['support']},
        'physical_exposure': 'highest_measured_surface_hypothesis',
        'gripper_accessibility': 'unverified',
        'pose_limitations': 'XY and shared ridge yaw with selected-band body-top assumption; no per-brick 6D/root pose or tracking identity'}


def filter_workspace_depth(depth, calibration, workspace):
    """Out-of-volume returns become unknown; no completion or lower-depth fill."""
    import numpy as np
    if depth.ndim != 2 or depth.dtype.kind != 'f':
        raise ValueError('Axial depth must be a floating-point image in meters')
    low, high = workspace['table_z_bounds_m']
    if [low, high] != [-.005, .20]:
        raise ValueError('Only the single declared Stage1 workspace bounds are allowed')
    valid = np.isfinite(depth) & (depth > 0)
    rows, columns = np.nonzero(valid)
    K, R, t = calibration['K'], calibration['R'], calibration['t']
    rays = np.column_stack(((columns-K[0, 2])/K[0, 0],
                            (rows-K[1, 2])/K[1, 1], np.ones(len(rows))))
    world = (depth[valid, None]*rays-t)@R
    below, above = world[:, 2] < low, world[:, 2] > high
    keep = np.isfinite(world).all(axis=1) & ~below & ~above
    filtered = np.full_like(depth, np.nan)
    filtered[rows[keep], columns[keep]] = depth[rows[keep], columns[keep]]
    return filtered, {'kind': 'declared_table_z_working_volume', 'table_z_bounds_m': [low, high],
        'total_pixels': int(depth.size), 'finite_positive_input': int(valid.sum()),
        'invalid_input': int((~valid).sum()), 'below_volume': int(below.sum()),
        'above_volume': int(above.sum()), 'kept_returns': int(keep.sum()),
        'removed_valid_returns': int(valid.sum()-keep.sum()),
        'semantics': 'Removed and invalid returns are NaN/unknown, not physical absence; raw RGB/depth unchanged'}


def main():
    import cv2
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, help='Optional single declared table-Z preprocessing prior')
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Perception batches require default Pueue')
    cv2.setNumThreads(2)
    upstream = args.inputs/'upstream'
    expected = json.loads(Path(__file__).with_name('upstream_hashes.json').read_text())
    for name, digest in expected.items():
        if hashlib.sha256((upstream/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen R3 changed: '+name)
    method = load('stage1_frozen_r3', upstream/'method.py')
    depth_module = load('stage1_frozen_depth', upstream/'depth_module.py')
    Evidence = load('stage1_frozen_evidence', upstream/'evidence.py').Evidence
    config = json.loads((upstream/'config.json').read_text())
    depth_config = json.loads((upstream/'depth_config_runtime.json').read_text())
    expected_depth_config = json.loads((upstream/'depth_config.json').read_text())
    expected_depth_config['source_roi_world_xy_m'] = {'x': [-.128, .128], 'y': [-.128, .128]}
    if depth_config != expected_depth_config:
        raise RuntimeError('Only the approved source ROI translation may change R3 configuration')
    package = json.loads((args.inputs/'calibration.json').read_text())
    workspace = json.loads(args.workspace.read_text()) if args.workspace else None
    frame_records = json.loads((args.inputs/'frames.json').read_text())
    summaries, contracts = [], {}
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    for frame in frame_records:
        cv2.setRNGSeed(26)
        rgb = cv2.imread(str(args.inputs/frame['rgb']))
        depth = np.load(args.inputs/frame['depth'], allow_pickle=False)
        if rgb is None or depth.shape != rgb.shape[:2]:
            raise ValueError('RGB/depth shape mismatch')
        nominal = package['views'][frame['camera']]
        calibration = {'K': np.asarray(package['K'], np.float64),
            'R': np.asarray(nominal['R_world_to_camera'], np.float64),
            't': np.asarray(nominal['t_world_to_camera_m'], np.float64)}
        folder = args.output/frame['id']
        folder.mkdir()
        if workspace is not None:
            depth, preprocessing = filter_workspace_depth(depth, calibration, workspace)
            preprocessing['workspace_spec'] = workspace
            preprocessing['raw_depth_sha256'] = hashlib.sha256((args.inputs/frame['depth']).read_bytes()).hexdigest()
            np.save(folder/'processed_depth.npy', depth)
            (folder/'preprocessing.json').write_text(json.dumps(preprocessing, indent=2, allow_nan=False)+'\n')
        result, mask, ridges = method.analyze(depth, rgb, calibration, depth_module,
            depth_config, config, Evidence, frame['camera'], 'observed')
        payload = {'schema': 'stage1-candidates-v1', 'frame_id': frame['id'],
            'coordinate_frame': 'table', 'image_size': [rgb.shape[1], rgb.shape[0]],
            'candidates': [candidate_contract(c) for c in result['candidates']]}
        (folder/'r3.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
        (folder/'candidates.json').write_text(json.dumps(payload, indent=2, allow_nan=False)+'\n')
        for name, image in (('overlay.png', method.overlay(rgb, result)),
                            ('top_band_world_xy.png', mask.astype(np.uint8)*255),
                            ('ridge_mask_world_xy.png', ridges.astype(np.uint8)*255)):
            if not cv2.imwrite(str(folder/name), image):
                raise OSError('Failed to save '+name)
        contracts[frame['id']] = payload['candidates']
        summary = {'frame_id': frame['id'], 'direction_status': result['direction_status'],
            'counts': {key: sum(c['decision'] == key for c in result['candidates'])
                       for key in ('present', 'missing', 'uncertain')}}
        summaries.append(summary)
        print('STAGE1_FRAME', json.dumps(summary), flush=True)
    (args.output/'mock_results.json').write_text(json.dumps(fixtures(contracts), indent=2)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'complete': True, 'frames': summaries,
        'seconds': time.monotonic()-started, 'opencv': cv2.__version__, 'numpy': np.__version__,
        'r3_source_hashes': expected}, indent=2)+'\n')


if __name__ == '__main__':
    main()

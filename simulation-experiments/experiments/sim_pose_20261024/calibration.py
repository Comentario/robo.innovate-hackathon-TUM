"""Derive nominal virtual calibration from scene DESIGN, never saved simulator truth."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
source = ROOT/'experiments/sim_views_20261024/render_views.py'
spec = importlib.util.spec_from_file_location('configured_view_helpers', source)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def configured_calibration(geometry, cameras):
    geometry_spec, bricks = helpers.load_geometry(geometry)
    config = json.loads(Path(cameras).read_text())
    top = [b.pose(geometry_spec['source_xy_m'], geometry_spec['baseplate_studs'])[0]
           for b in bricks if b.layer == geometry_spec['layers']-1]
    center = [sum(p[i] for p in top)/len(top) for i in range(3)]
    center[2] += helpers.HEIGHT + .0017
    width, height = config['image_size']
    focal = width*config['focal_length_mm']/config['horizontal_aperture_mm']
    views = {}
    for view in config['views']:
        pose = helpers.camera_pose(center, view)
        gl = pose['rotation_camera_to_world']
        # OpenGL camera +X right,+Y up,-Z forward -> OpenCV +X right,+Y down,+Z forward.
        rotation = [[gl[i][j]*(1 if j == 0 else -1) for i in range(3)] for j in range(3)]
        eye = pose['eye_world_m']
        translation = [-sum(row[i]*eye[i] for i in range(3)) for row in rotation]
        views[view['id']] = {'R_world_to_camera': rotation, 't_world_to_camera_m': translation,
                             'eye_world_m': list(eye)}
    return {'schema': 'configured-virtual-camera-v1',
            'source': 'Intended geometry and named camera presets only; no saved camera or brick truth read',
            'calibration_status': 'Configured nominal synthetic calibration; not measured D435i calibration',
            'image_size': [width, height],
            'K': [[focal, 0., width/2], [0., focal, height/2], [0., 0., 1.]],
            'distortion_coefficients': [0., 0., 0., 0., 0.],
            'pose_frame': 'world/robot base; brick body-bottom-center; upright roll/pitch assumption',
            'views': views}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--geometry', type=Path, default=ROOT/'experiments/sim_views_20261024/geometry.json')
    p.add_argument('--cameras', type=Path, default=ROOT/'experiments/sim_views_20261024/cameras.json')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.write_text(json.dumps(configured_calibration(args.geometry, args.cameras), indent=2)+'\n')

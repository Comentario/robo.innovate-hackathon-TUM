"""Queued, deterministic evidence annotations; no photo registration/calibration."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np


def project(points, camera):
    matrix = np.asarray(camera['rotation_camera_to_world'])
    optical = (np.asarray(points)-camera['actual_eye_world_m'])@matrix
    optical *= [1, -1, -1]
    pixels = optical@np.asarray(camera['intrinsics']).T
    return pixels[:, :2]/pixels[:, 2:]


def label(image, text, xy, color=(30, 30, 30)):
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 4)
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, .55, color, 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--photo', type=Path, required=True)
    p.add_argument('--render', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    a = p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Image annotation requires default Pueue')
    cv2.setNumThreads(2)
    a.output.mkdir(parents=True, exist_ok=True)
    before = json.loads((a.baseline/'robot_initialization.json').read_text())
    after = json.loads((a.render/'robot_initialization.json').read_text())
    assert before['joint_names'] == after['joint_names']
    assert before['requested_joint_positions_native_units'] == after['requested_joint_positions_native_units']
    before_states = np.load(a.baseline/'evaluation_truth/active_root_states.npy', allow_pickle=False)
    after_states = np.load(a.render/'evaluation_truth/active_root_states.npy', allow_pickle=False)
    assert before_states.shape == after_states.shape == (300, 13)
    source_delta = float(np.max(np.abs(before_states-after_states)))
    assert source_delta <= 2e-6
    photo = cv2.imread(str(a.photo))
    if photo is None or photo.shape[:2] != (960, 1280):
        raise ValueError('Expected frozen 1280x960 Photo 1')
    # Manually identified fixed features; these are visual labels, not metric picks.
    cv2.rectangle(photo, (542, 21), (612, 116), (0, 110, 230), 2)
    cv2.arrowedLine(photo, (672, 145), (582, 71), (0, 110, 230), 3, tipLength=.15)
    label(photo, 'Fixed lower connector bank', (210, 80), (0, 80, 200))
    label(photo, 'Housing direction: table +X / -Y', (215, 108), (0, 80, 200))
    label(photo, 'Arm bend is not used', (795, 70))
    cv2.rectangle(photo, (590, 133), (780, 207), (0, 140, 40), 2)
    label(photo, 'Visible fixed housing / mounting edge', (805, 192), (0, 110, 30))
    cv2.arrowedLine(photo, (300, 790), (200, 790), (30, 100, 30), 2)
    cv2.arrowedLine(photo, (300, 790), (300, 885), (30, 100, 30), 2)
    label(photo, '+X toward gray plate', (110, 765))
    label(photo, '+Y toward bowl', (310, 870))
    label(photo, 'Table directions are schematic; visual estimate only', (70, 930))
    cv2.imwrite(str(a.output/'photo1_annotated.png'), photo)
    cameras = json.loads((a.render/'evaluation_truth/cameras.json').read_text())
    outputs = []
    for camera in cameras:
        if 'fixed_base_axes' not in camera:
            continue
        image = cv2.imread(str(a.render/'images'/(camera['id']+'.png')))
        axes = np.asarray(camera['fixed_base_axes']['world_points_m'])
        origin, ey = axes[0], (axes[2]-axes[0])/.1
        axis_pixels = np.asarray(camera['fixed_base_axes']['image_points_uv_depth'])[:, :2]
        for endpoint, text, color in zip(axis_pixels[1:], ['+asset X', '+asset Y'], [(0, 0, 220), (0, 140, 0)]):
            cv2.arrowedLine(image, tuple(np.rint(axis_pixels[0]).astype(int)), tuple(np.rint(endpoint).astype(int)), color, 2)
            label(image, text, tuple(np.rint(endpoint+[8, -8]).astype(int)), color)
        normal = -ey
        line = project([origin+[0, 0, .08], origin+[0, 0, .08]+normal*.16], camera)
        cv2.arrowedLine(image, tuple(np.rint(line[0]).astype(int)), tuple(np.rint(line[1]).astype(int)), (220, 80, 0), 3, tipLength=.15)
        label(image, 'Lower connector face: asset -Y', (35, 40), (200, 60, 0))
        label(image, 'Estimated base yaw 45 deg -> table +X / -Y', (35, 70))
        label(image, 'Fixed-base diagnostic; moving links hidden only for this view', (35, 925))
        target = a.output/(camera['id']+'_annotated.png')
        cv2.imwrite(str(target), image)
        outputs.append(str(target))
    # Redraw only the feature marks inside the crop; don't crop full-photo text.
    reference_crop = cv2.imread(str(a.photo))[:245, 500:850].copy()
    cv2.rectangle(reference_crop, (42, 21), (112, 116), (0, 110, 230), 2)
    cv2.rectangle(reference_crop, (90, 133), (280, 207), (0, 140, 40), 2)
    cv2.arrowedLine(reference_crop, (172, 145), (82, 71), (0, 110, 230), 3, tipLength=.15)
    model = cv2.imread(str(a.output/'base_top_annotated.png'))
    model_crop = model[150:750, 350:950]
    cells = []
    for text, crop in [('Photo 1: connector-side cue', reference_crop), ('Model: estimated yaw 45 degrees', model_crop)]:
        height = 500
        resized = cv2.resize(crop, (round(crop.shape[1]*height/crop.shape[0]), height))
        cell = np.full((565, 730, 3), 245, np.uint8)
        cell[50:550, :min(730, resized.shape[1])] = resized[:, :730]
        label(cell, text, (12, 28))
        label(cell, 'Different perspective; no calibrated registration', (12, 555))
        cells.append(cell)
    cv2.imwrite(str(a.output/'comparison.jpg'), np.hstack(cells), [cv2.IMWRITE_JPEG_QUALITY, 95])
    (a.output/'annotation_provenance.json').write_text(json.dumps({
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'photo_sha256': hashlib.sha256(a.photo.read_bytes()).hexdigest(),
        'manual_photo_labels': 'Fixed connector bank and visible lower mounting edge only; no arm-pose inference.',
        'render_axis_source': 'Actual fixed-link0 transform recorded by queued renderer',
        'estimated_yaw_table_deg': 45, 'uncertainty': 'Qualitative approximate photograph-supported diagonal; no numeric accuracy bound.',
        'nominal_joint_configuration_unchanged': True, 'source_state_maximum_absolute_difference': source_delta,
        'calibrated_robot_or_camera_transform': False, 'annotated_renders': outputs}, indent=2)+'\n')
    print('Saved annotated Photo 1, fixed-base renders and unregistered visual comparison.')


if __name__ == '__main__':
    main()

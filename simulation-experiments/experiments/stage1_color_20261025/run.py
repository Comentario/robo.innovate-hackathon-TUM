"""One frozen saved-sensor color benchmark; no simulator truth is an input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import cv2
import numpy as np

from color import build_prototypes, classify

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Saved-image batches require the default Pueue queue')
    cv2.setNumThreads(2)
    started = time.monotonic()
    settings = read(HERE/'settings.json')
    patches = read(HERE/'reference_patches.json')
    frames = read(args.inputs/'frames.json')
    package = read(args.inputs/'calibration.json')
    args.output.mkdir(parents=True)
    calibration_frame = next(row for row in frames if row['id']=='f000')
    reference_rgb = cv2.imread(str(args.inputs/calibration_frame['rgb']))
    if reference_rgb is None:
        raise ValueError('Missing reference RGB')
    prototypes = build_prototypes(reference_rgb, patches, settings)
    save(args.output/'prototypes.json', prototypes)
    if not prototypes['ready']:
        raise ValueError('Reference support failed; preserve prototypes without scoring')
    reference_overlay = reference_rgb.copy()
    for patch in patches:
        x0, y0, x1, y1 = patch['pixel_xyxy']
        cv2.rectangle(reference_overlay, (x0,y0), (x1,y1), (255,255,0), 1)
        cv2.putText(reference_overlay, patch['label'], (x0,y0-5), cv2.FONT_HERSHEY_SIMPLEX,.35,(255,255,0),1)
    if not cv2.imwrite(str(args.output/'reference_patches.png'), reference_overlay):
        raise OSError('Cannot save reference overlay')
    counts = []
    for frame in frames:
        rgb = cv2.imread(str(args.inputs/frame['rgb']))
        depth = np.load(args.inputs/frame['depth'], allow_pickle=False)
        if rgb is None or rgb.shape[:2] != depth.shape:
            raise ValueError('Missing or mismatched RGB-D')
        nominal = package['views'][frame['camera']]
        cal = {'K':np.asarray(package['K']), 'R':np.asarray(nominal['R_world_to_camera']),
               't':np.asarray(nominal['t_world_to_camera_m'])}
        packet = read(args.inputs/frame['candidates'])
        if packet['frame_id'] != frame['id']:
            raise ValueError('Candidate/frame identity mismatch')
        rows = [classify(rgb,depth,cal,candidate,frame['id'],prototypes,settings)
                for candidate in packet['candidates']]
        save(args.output/(frame['id']+'.json'), {'frame_id':frame['id'], 'classifications':rows})
        overlay = rgb.copy()
        for row in rows:
            poly = np.rint(row.get('region_polygon', [])).astype(np.int32)
            if poly.shape != (4,2):
                continue
            known = row['decision']=='known'
            color = (60,220,60) if known else (0,180,255)
            cv2.polylines(overlay,[poly],True,color,1)
            anchor = tuple(poly.mean(0).astype(int))
            cv2.putText(overlay,row['label'] if known else '?',anchor,cv2.FONT_HERSHEY_SIMPLEX,.3,color,1)
        if not cv2.imwrite(str(args.output/(frame['id']+'_overlay.png')),overlay):
            raise OSError('Cannot save prediction overlay')
        counts.append({'frame_id':frame['id'],'candidates':len(rows),
                       'known':sum(row['decision']=='known' for row in rows)})
        if frame['id']=='f000':
            # Deliberate merged-face negative: PRESENT is supplied so the
            # color-evidence screen, rather than the source-decision gate, runs.
            mixed = {'candidate_id':'negative_mixed_tan_ochre','decision':'present',
                     'image_polygon':[[437,297],[475,297],[475,443],[437,443]],
                     'estimated_body_top_from_selected_band_m':packet['candidates'][0]['estimated_body_top_from_selected_band_m']}
            negative = classify(rgb,depth,cal,mixed,'f000',prototypes,settings)
            save(args.output/'negative_mixed.json',negative)
    save(args.output/'complete.json',{'completed':True,'frames':counts,
         'seconds':time.monotonic()-started,'opencv':cv2.__version__,'numpy':np.__version__,
         'settings_sha256':hashlib.sha256((HERE/'settings.json').read_bytes()).hexdigest(),
         'reference_patches_sha256':hashlib.sha256((HERE/'reference_patches.json').read_bytes()).hexdigest(),
         'scope':'Simulation RGB source-color only; no quality, held identity, grasp or hardware claim.'})


if __name__=='__main__':
    main()

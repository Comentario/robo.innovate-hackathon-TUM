"""Replay the final-selection color handoff; no physics or privileged inputs."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from adapter import classify_selection, invalidate, json_digest, make_observation

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Saved-image processing requires default Pueue')
    cv2.setNumThreads(2)
    started = time.monotonic()
    settings, prototypes = read(args.inputs/'settings.json'), read(args.inputs/'prototypes.json')
    refs = {name+'_sha256':sha(args.inputs/filename) for name,filename in
            [('classifier','color.py'),('settings','settings.json'),('prototypes','prototypes.json')]}
    refs.update(settings_content_sha256=json_digest(settings),prototypes_content_sha256=json_digest(prototypes))
    plan = read(HERE/'protocol.json')
    package = read(args.inputs/'calibration.json')
    frames = read(args.inputs/'frames.json')
    transactions, processed = [], []
    args.output.mkdir()
    for identity in plan['frame_ids']:
        frame = next(row for row in frames if row['id']==identity)
        rgb = cv2.imread(str(args.inputs/frame['rgb']))
        depth = np.load(args.inputs/frame['depth'],allow_pickle=False)
        if rgb is None or rgb.shape[:2]!=depth.shape:
            raise ValueError('Missing or inconsistent saved RGB-D')
        view = package['views'][frame['camera']]
        cal = {'K':package['K'],'R':view['R_world_to_camera'],'t':view['t_world_to_camera_m']}
        packet = read(args.inputs/frame['candidates'])
        if packet['frame_id'] != identity:
            raise ValueError('Saved frame/candidate mismatch')
        source = {'frame_id':identity,'measurement_time_s':None,
                  'rgb_sha256':sha(args.inputs/frame['rgb']),'depth_sha256':sha(args.inputs/frame['depth'])}
        observed = make_observation(source,rgb,depth,cal)
        for candidate in packet['candidates']:
            selection = {**source,'candidate':candidate}
            observation = {**observed,'candidate_sha256':json_digest(candidate)}
            transaction = classify_selection(selection,rgb,depth,cal,prototypes,settings,
                observation=observation,reference_hashes=refs,current_time_s=None,case_id='stage1_'+identity)
            transactions.append(transaction)
        processed.append(identity)
    selected_folder = args.inputs/'selected_stage2'
    selection = read(selected_folder/'selection.json')
    rgb = cv2.imread(str(selected_folder/'rgb.png'))
    with np.load(selected_folder/'depth.npz',allow_pickle=False) as saved:
        depth = saved['depth'].copy()
    cal = selection['calibration']
    source = {**selection,'rgb_sha256':sha(selected_folder/'rgb.png'),'depth_sha256':sha(selected_folder/'depth.npz')}
    observation = make_observation(source,rgb,depth,cal)
    observation['candidate_sha256'] = json_digest(selection['candidate'])
    kwargs = dict(observation=observation,reference_hashes=refs,
                  current_time_s=selection['measurement_time_s'],case_id='stage2_selected')
    selected = classify_selection(selection,rgb,depth,cal,prototypes,settings,**kwargs)
    transactions.append(selected)
    controls = []
    def control(identity,sel=selection,image=rgb,z=depth,camera=cal,options=None):
        named = {**kwargs,**(options or {})}
        value = classify_selection(sel,image,z,camera,prototypes,settings,**named)
        controls.append({'id':identity,'transaction':value})
    control('no_candidate',sel={**selection,'candidate':None})
    control('frame_mismatch',sel={**selection,'frame_id':'another_frame'})
    control('stale_frame',options={'current_time_s':selection['measurement_time_s']+1/120})
    changed = rgb.copy(); changed[0,0,0] ^= 1
    control('rgb_content_mismatch',image=changed)
    changed_depth = depth.copy(); changed_depth[0,0] = 0 if depth[0,0] != 0 else 1
    control('depth_content_mismatch',z=changed_depth)
    changed_cal = copy.deepcopy(cal); changed_cal['K'][0][2] += 1
    control('calibration_mismatch',camera=changed_cal)
    changed_selection = copy.deepcopy(selection)
    changed_selection['candidate']['image_polygon'][0][0] += 1
    control('candidate_geometry_mismatch',sel=changed_selection)
    controls += [{'id':name,'transaction':invalidate(selected,name,selection['measurement_time_s']+1/120)}
                 for name in ('abort','slip')]
    actual_end = read(selected_folder/'capture_complete.json')
    if actual_end['controller_status'] != 'aborted':
        raise ValueError('Expected historical aborted pick')
    final = invalidate(selected,'recorded_controller_abort',None)
    controls.append({'id':'historical_abort','transaction':final})
    overlay = rgb.copy()
    poly = np.rint(selection['candidate']['image_polygon']).astype(np.int32)
    cv2.polylines(overlay,[poly],True,(0,200,255),2)
    label = selected['source_color']['label'] if selected['source_color'] else None
    cv2.putText(overlay,'Source color: '+str(label)+'; held: UNKNOWN',tuple(poly.min(0)),
                cv2.FONT_HERSHEY_SIMPLEX,.5,(0,200,255),1)
    if not cv2.imwrite(str(args.output/'selected_source_overlay.png'),overlay):
        raise OSError('Cannot save source overlay')
    report = {'schema':'source-color-handoff-replay-v1','completed':True,
        'processed_frame_ids':processed,'transactions':transactions,'controls':controls,
        'source_pins':{**refs,'adapter_sha256':sha(HERE/'adapter.py')},
        'selected_selection_sha256':selection['original_selection_sha256'],
        'stage2_final_transaction':final,'stage2_recorded_outcome':actual_end,
        'seconds':time.monotonic()-started,'versions':{'python':sys.version.split()[0],'opencv':cv2.__version__,'numpy':np.__version__},
        'scope':'Saved sensor handoff equivalence only. No new color accuracy, live render, grasp or routing claim.'}
    (args.output/'replay.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':
    main()

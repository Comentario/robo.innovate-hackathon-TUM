"""Freeze existing depth sensors and queue uppermost ridge direction in default Pueue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[1]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'
RENDER = ROOT/'runs/20261024T104724.316246Z-sim-views/output'
RGB = ROOT/'experiments/sim_views_20261024/results_300'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-only', action='store_true')
    args = parser.parse_args()
    if subprocess.check_output(['git','status','--porcelain','--',str(EXP.relative_to(ROOT))],cwd=ROOT,text=True):
        parser.error('Commit scoped code, settings and protocol before freezing the depth job')
    calibration = json.loads((EXP/'calibration.json').read_text())
    views = list(calibration['views'])
    if len(views) != 5:
        parser.error('Exactly the five existing corrected-stack views are required')
    source = json.loads((RGB/'provenance.json').read_text())
    if source['job_id'] != 1681 or source['required_bricks'] != 300:
        parser.error('RGB overlays must come from corrected render job1681')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot = ROOT/'runs'/f'{stamp}-depth-ridge-direction'
    inference = snapshot/'inference'
    inputs = inference/'inputs'
    scoring = snapshot/'scoring_only'
    truth = scoring/'truth'
    output = snapshot/'output'
    for path in [inputs/'depth',inputs/'images',truth,output]:
        path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXP/'depth_ridges.py',inference/'depth_ridges.py')
    for name in ['config.json','calibration.json']:
        shutil.copy2(EXP/name,inputs/name)
    for view in views:
        depth = RENDER/'evaluation_truth'/f'{view}_depth.npy'
        image = RGB/'images'/f'{view}.png'
        if sha(image) != source['image_sha256'][f'images/{view}.png']:
            raise ValueError(f'Overlay RGB changed: {view}')
        shutil.copy2(depth,inputs/'depth'/f'{view}.npy')
        shutil.copy2(image,inputs/'images'/image.name)
    for name in ['evaluation.py','protocol.json']:
        shutil.copy2(EXP/name,scoring/name)
    shutil.copy2(RENDER/'evaluation_truth/frozen_physics_state.npy',truth/'frozen_physics_state.npy')
    shutil.copy2(RENDER/'manifest.json',truth/'manifest.json')
    for name in ['submit.py','README.md']:
        shutil.copy2(EXP/name,snapshot/name)
    commands = [shlex.join([PYTHON,str(inference/'depth_ridges.py'),'--inputs',str(inputs),
                           '--config',str(inputs/'config.json'),'--output',str(output/'predictions')]),
                shlex.join([PYTHON,str(scoring/'evaluation.py'),'--predictions',str(output/'predictions'),
                           '--truth',str(truth),'--protocol',str(scoring/'protocol.json'),
                           '--output',str(output/'evaluation')])]
    launch = ['#!/usr/bin/env bash','set -euo pipefail',f'cd {shlex.quote(str(snapshot))}',
              'export ROBO_PUEUE_JOB=1','export PYTHONDONTWRITEBYTECODE=1',
              f'export PYTHONPATH={shlex.quote(str(inference))}',
              'export OMP_NUM_THREADS=2','export OPENBLAS_NUM_THREADS=2','export OPENCV_FOR_THREADS_NUM=2',
              *commands,'test -f output/evaluation/evaluation.json',
              "printf '%s' '{\"complete\":true,\"views\":5,\"direction_only\":true}' > run_complete.json",'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    manifest = {'created_utc':stamp,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'runtime_python':PYTHON,'render_input_job':1681,'source_render':str(RENDER.relative_to(ROOT)),
                'perception_inputs':'Axial depth in meters, configured camera K/R/t and source-plate XY ROI; RGB only for overlays',
                'scoring_only':'Actual simulator brick roots and scene manifest; no layer height/count/yaw/identities in inference inputs',
                'depth_source_role_change':'User explicitly authorized depth as sensor input; original files happened to be under evaluation_truth/',
                'simulation':False,'training':False,'hardware_control':False,
                'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Snapshot:',snapshot,flush=True)
    if args.snapshot_only:
        return
    task = subprocess.run(['pueue','add','--label','robo26-depth-ridge-direction',shlex.join(['bash',str(snapshot/'launch.sh')])],
                          check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(task.stdout)
    print(task.stdout.strip(),flush=True)


if __name__ == '__main__':
    main()

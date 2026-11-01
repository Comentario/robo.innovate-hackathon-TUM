"""Freeze existing RGB views and queue separated inference/evaluation in default Pueue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'
RENDER_RUN = ROOT/'runs/20261024T104724.316246Z-sim-views'
RENDER_RESULTS = ROOT/'experiments/sim_views_20261024/results_300'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-only', action='store_true')
    args = parser.parse_args()
    scope = [str(EXPERIMENT.relative_to(ROOT)), 'perception/algorithm.py',
             'experiments/sim_views_20261024/render_views.py',
             'experiments/sim_views_20261024/geometry.json',
             'experiments/sim_views_20261024/cameras.json', 'challenge2/layout.py']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT,text=True):
        parser.error('Commit scoped source, settings and independent protocol before freezing the batch')
    from calibration import configured_calibration
    geometry = ROOT/'experiments/sim_views_20261024/geometry.json'
    cameras = ROOT/'experiments/sim_views_20261024/cameras.json'
    expected = configured_calibration(geometry, cameras)
    calibration = json.loads((EXPERIMENT/'calibration.json').read_text())
    if calibration != expected:
        parser.error('Nominal calibration differs from frozen public design/presets; do not use evaluation truth to repair it')
    provenance = json.loads((RENDER_RESULTS/'provenance.json').read_text())
    if provenance['job_id'] != 1681 or provenance['required_bricks'] != 300:
        parser.error('This experiment requires the validated corrected render inputs from job1681')
    view_ids = list(calibration['views'])
    if len(view_ids) != 5:
        parser.error('Exactly five existing view presets are required')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot = ROOT/'runs'/f'{stamp}-sim-rgb-pose'
    inference = snapshot/'inference'
    inputs = inference/'inputs'
    scoring = snapshot/'scoring_only'
    truth = scoring/'truth'
    output = snapshot/'output'
    for path in [inputs/'images',inputs/'upstream',truth,output]:
        path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXPERIMENT/'batch.py',inference/'batch.py')
    shutil.copy2(EXPERIMENT/'config.json',inputs/'config.json')
    shutil.copy2(EXPERIMENT/'calibration.json',inputs/'calibration.json')
    shutil.copy2(geometry,inputs/'geometry.json')
    shutil.copy2(ROOT/'perception/algorithm.py',inputs/'upstream/evidence.py')
    for view in view_ids:
        image = RENDER_RESULTS/'images'/f'{view}.png'
        if sha(image) != provenance['image_sha256'][f'images/{view}.png']:
            raise ValueError(f'Saved RGB input changed: {view}')
        shutil.copy2(image,inputs/'images'/image.name)
    for name in ['evaluate.py','base_evaluation.py','protocol.json']:
        shutil.copy2(EXPERIMENT/'evaluation'/name,scoring/name)
    for name in ['annotations.json','cameras.json','frozen_physics_state.npy']:
        shutil.copy2(RENDER_RUN/'output/evaluation_truth'/name,truth/name)
    shutil.copy2(RENDER_RUN/'output/manifest.json',truth/'manifest.json')
    shutil.copy2(geometry,truth/'geometry.json')
    for name in ['submit.py','calibration.py','README.md']:
        shutil.copy2(EXPERIMENT/name,snapshot/name)
    # Retain the source of nominal calibration, without making it an inference input.
    for relative in ['experiments/sim_views_20261024/render_views.py',
                     'experiments/sim_views_20261024/geometry.json',
                     'experiments/sim_views_20261024/cameras.json', 'challenge2/layout.py']:
        target = snapshot/'source_provenance'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/relative,target)
    commands = [shlex.join([PYTHON,str(inference/'batch.py'),'--inputs',str(inputs),
                           '--config',str(inputs/'config.json'),
                           '--output',str(output/'predictions')]),
                shlex.join([PYTHON,str(scoring/'evaluate.py'),'--predictions',str(output/'predictions'),
                           '--truth',str(truth),'--protocol',str(scoring/'protocol.json'),
                           '--output',str(output/'evaluation')])]
    launch = ['#!/usr/bin/env bash','set -euo pipefail',f'cd {shlex.quote(str(snapshot))}',
              'export ROBO_PUEUE_JOB=1','export PYTHONDONTWRITEBYTECODE=1',
              f'export PYTHONPATH={shlex.quote(str(inference))}',
              'export OMP_NUM_THREADS=2','export OPENBLAS_NUM_THREADS=2','export OPENCV_FOR_THREADS_NUM=2',
              *commands,'test -f output/evaluation/evaluation.json',
              "printf '%s' '{\"complete\":true,\"views\":5,\"conditions\":3}' > run_complete.json",'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    manifest = {'created_utc':stamp,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'runtime':PYTHON,'render_input_job':1681,'render_snapshot':str(RENDER_RUN.relative_to(ROOT)),
                'perception_inputs_only':'Five RGB images, public intended geometry, configured nominal camera calibration, frozen config and unchanged Evidence helper',
                'scoring_only':'Actual camera records, visibility annotations, frozen simulator brick poses and capture manifest; never passed to inference',
                'conditions':['nominal','perturbed','blank_nominal'],
                'model_inference':False,'training':False,'simulation':False,
                'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Snapshot:',snapshot,flush=True)
    if args.snapshot_only:
        return
    task = subprocess.run(['pueue','add','--label','robo26-sim-rgb-pose',shlex.join(['bash',str(snapshot/'launch.sh')])],
                          capture_output=True,text=True,check=True)
    (snapshot/'submission.txt').write_text(task.stdout)
    print(task.stdout.strip(),flush=True)


if __name__ == '__main__':
    main()

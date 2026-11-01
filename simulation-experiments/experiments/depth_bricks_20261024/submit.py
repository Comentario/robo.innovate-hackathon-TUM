"""Freeze depth-assisted brick inputs and queue one separated perception/evaluation job."""
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
DEPTH_EXP = ROOT/'experiments/depth_ridges_20261024'
DEPTH_RUN = ROOT/'runs/20261024T125255.987070Z-depth-ridge-direction'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot-only', action='store_true')
    args = p.parse_args()
    scope = [str(EXP.relative_to(ROOT)),str((DEPTH_EXP/'depth_ridges.py').relative_to(ROOT)),
             str((DEPTH_EXP/'config.json').relative_to(ROOT)),'perception/algorithm.py']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT,text=True):
        p.error('Commit scoped source/settings/protocol before freezing a batch')
    upstream_manifest = json.loads((DEPTH_RUN/'manifest.json').read_text())
    for current, frozen in [(DEPTH_EXP/'depth_ridges.py','inference/depth_ridges.py'),
                            (DEPTH_EXP/'config.json','inference/inputs/config.json')]:
        if sha(current) != upstream_manifest['sha256'][frozen]:
            p.error('Successful depth module/settings changed; no silent upstream retuning')
    calibration = json.loads((EXP/'calibration.json').read_text())
    if calibration != json.loads((DEPTH_EXP/'calibration.json').read_text()):
        p.error('Use the same allowed configured camera calibration as the depth experiment')
    views = list(calibration['views'])
    if len(views) != 5:
        p.error('The bounded batch requires the same five views')
    provenance = json.loads((RGB/'provenance.json').read_text())
    if provenance['job_id'] != 1681 or provenance['required_bricks'] != 300:
        p.error('Require corrected source render job1681')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot = ROOT/'runs'/f'{stamp}-depth-brick-detection'
    inference = snapshot/'inference'; inputs = inference/'inputs'
    scoring = snapshot/'scoring_only'; truth = scoring/'truth'; output = snapshot/'output'
    for folder in [inputs/'depth',inputs/'images',inputs/'upstream',truth,output]:
        folder.mkdir(parents=True,exist_ok=True)
    shutil.copy2(EXP/'batch.py',inference/'batch.py')
    for name in ['config.json','calibration.json']:
        shutil.copy2(EXP/name,inputs/name)
    shutil.copy2(DEPTH_EXP/'depth_ridges.py',inputs/'upstream/depth_ridges.py')
    shutil.copy2(DEPTH_EXP/'config.json',inputs/'upstream/depth_config.json')
    shutil.copy2(ROOT/'perception/algorithm.py',inputs/'upstream/evidence.py')
    for view in views:
        image = RGB/'images'/f'{view}.png'
        if sha(image) != provenance['image_sha256'][f'images/{view}.png']:
            raise ValueError(f'Original RGB changed: {view}')
        shutil.copy2(image,inputs/'images'/image.name)
        shutil.copy2(RENDER/'evaluation_truth'/f'{view}_depth.npy',inputs/'depth'/f'{view}.npy')
    for name in ['evaluate.py','protocol.json','base_evaluation.py']:
        shutil.copy2(EXP/'evaluation'/name,scoring/name)
    for name in ['annotations.json','cameras.json','frozen_physics_state.npy']:
        shutil.copy2(RENDER/'evaluation_truth'/name,truth/name)
    shutil.copy2(RENDER/'manifest.json',truth/'manifest.json')
    shutil.copy2(ROOT/'experiments/sim_pose_20261024/results/evaluation/evaluation.json',
                 truth/'prior_rgb_pose_evaluation.json')
    for name in ['submit.py','README.md']:
        shutil.copy2(EXP/name,snapshot/name)
    commands = [shlex.join([PYTHON,str(inference/'batch.py'),'--inputs',str(inputs),
                           '--config',str(inputs/'config.json'),'--output',str(output/'predictions')]),
                shlex.join([PYTHON,str(scoring/'evaluate.py'),'--predictions',str(output/'predictions'),
                           '--truth',str(truth),'--protocol',str(scoring/'protocol.json'),
                           '--output',str(output/'evaluation')])]
    launch = ['#!/usr/bin/env bash','set -euo pipefail',f'cd {shlex.quote(str(snapshot))}',
              'export ROBO_PUEUE_JOB=1','export PYTHONDONTWRITEBYTECODE=1',
              f'export PYTHONPATH={shlex.quote(str(inference))}',
              'export OMP_NUM_THREADS=2','export OPENBLAS_NUM_THREADS=2','export OPENCV_FOR_THREADS_NUM=2',
              *commands,'test -f output/evaluation/evaluation.json',
              "printf '%s' '{\"complete\":true,\"views\":5,\"individual_brick_detection\":true}' > run_complete.json",'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    manifest = {'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'created_utc':stamp,'runtime_python':PYTHON,'source_render_job':1681,'unchanged_depth_module_job':1684,
                'inference_inputs':'Original RGB/axial depth, nominal calibration/ROI, fixed2x4footprint, unchanged depth+Evidence modules; no layout/count/brick poses/labels',
                'scoring_only':'Simulator roots, annotations, actual camera records, source scene manifest and previous RGB-pose evaluation',
                'training':False,'new_render':False,'hardware_control':False,
                'sha256':{str(f.relative_to(snapshot)):sha(f) for f in sorted(snapshot.rglob('*')) if f.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Snapshot:',snapshot,flush=True)
    if args.snapshot_only:
        return
    task = subprocess.run(['pueue','add','--label','robo26-depth-brick-detection',
                           shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(task.stdout)
    print(task.stdout.strip(),flush=True)


if __name__ == '__main__':
    main()

"""Copy the frozen color benchmark and submit one <=60s default-queue job."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'
SOURCE = ROOT/'runs/20261025T003437.436801Z-stage1-development-workspace_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):
        raise RuntimeError('Commit reviewed code/config before freezing')
    protocol = json.loads((HERE/'protocol.json').read_text())
    if protocol['execution_authorized'] is not True:
        raise RuntimeError('Source review required')
    if protocol['maximum_active_seconds'] != 60:
        raise RuntimeError('Unexpected resource scope')
    for relative,digest in protocol['frozen_sources_sha256'].items():
        if sha(ROOT/relative) != digest:
            raise RuntimeError('Frozen input changed: '+relative)
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage1-color')
    snapshot.mkdir()
    shutil.copytree(HERE,snapshot/'code',ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    public,private = snapshot/'public',snapshot/'private'
    public.mkdir();private.mkdir()
    shutil.copy2(SOURCE/'sensors/calibration.json',public/'calibration.json')
    records = json.loads((SOURCE/'sensors/frames.json').read_text())
    frames = []
    for identity in protocol['frame_ids']:
        row = next(row for row in records if row['id']==identity)
        folder=public/identity;folder.mkdir()
        for name in ('rgb','depth'):
            destination=folder/Path(row[name]).name
            shutil.copy2(SOURCE/'sensors'/row[name],destination)
        shutil.copy2(SOURCE/'inference'/identity/'candidates.json',folder/'candidates.json')
        shutil.copy2(SOURCE/'inference'/identity/'overlay.png',folder/'raw_r3_overlay.png')
        frames.append({'id':identity,'camera':row['camera'],'rgb':identity+'/rgb.png',
                       'depth':identity+'/depth.npy','candidates':identity+'/candidates.json'})
    (public/'frames.json').write_text(json.dumps(frames,indent=2)+'\n')
    shutil.copy2(SOURCE/'private/frames.json',private/'frames.json')
    shutil.copy2(SOURCE/'evaluation/evaluation.json',private/'existing_stage1_evaluation.json')
    shutil.copy2(SOURCE/'evaluation/references.json',private/'references.json')
    for case in ('I_mix','H_mix','E_mix'):
        shutil.copy2(SOURCE/'private/truth'/case/'evaluation_truth/active_bricks.json',private/('inventory_'+case+'.json'))
    pipeline = ['#!/usr/bin/env bash','set -eo pipefail','cd '+shlex.quote(str(snapshot)),
       'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
       shlex.join([PYTHON,str(snapshot/'code/run.py'),'--inputs',str(public),'--output',str(snapshot/'predictions')]),
       shlex.join([PYTHON,str(snapshot/'code/evaluation/evaluate.py'),'--inputs',str(public),
                   '--private',str(private),'--predictions',str(snapshot/'predictions'),'--output',str(snapshot/'audit')]),'']
    (snapshot/'pipeline.sh').write_text('\n'.join(pipeline))
    launch=['#!/usr/bin/env bash','set -eo pipefail',
            'exec timeout --signal=TERM --kill-after=3s 57s bash '+shlex.quote(str(snapshot/'pipeline.sh')),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'runtime_python':PYTHON,
        'source_snapshot':str(SOURCE),'maximum_active_seconds':60,'maximum_jobs_this_version':1,
        'truth_separation':'run.py gets public RGB-D/candidates/calibration only; private files only evaluator arguments',
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    submitted = subprocess.run(['pueue','add','--label','robo26-pregrasp-color',
                              shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(submitted.stdout)
    print(snapshot);print(submitted.stdout.strip())


if __name__=='__main__':
    main()

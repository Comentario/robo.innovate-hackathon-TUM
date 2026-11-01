"""Freeze one numeric-only measured-camera frame bridge and use default Pueue."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol=json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Review and freeze the bounded check first')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):
        raise RuntimeError('Commit reviewed code/config before snapshot')
    for previous in (ROOT/'runs').glob('*-munich-optical-bridge'):
        if (previous/'submission.txt').exists():raise RuntimeError('The one fixed metadata check was already submitted')
    for item in [*protocol['files'].values(),*protocol['pairings'],*protocol['acquisitions']]:
        if sha(item['path'])!=item['sha256']:raise RuntimeError('Pinned input changed: '+item['path'])
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-munich-optical-bridge')
    snapshot.mkdir();code=snapshot/'code'
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    command=[PYTHON,str(code/'check_bridge.py'),'--inputs',str(code/'protocol.json'),'--output',str(snapshot/'output')]
    launch=['#!/usr/bin/env bash','set -eo pipefail','cd '+shlex.quote(str(snapshot)),
            'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
            'exec timeout --signal=TERM --kill-after=2s 8s '+shlex.join(command),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'maximum_active_seconds':10,'maximum_jobs':1,'scope':'Metadata-only frame/model bridge; no images/NPZ/hardware/ROS/network/simulation',
        'data_provenance':'SHA-pinned original bundle JSON/XML/YAML and1807 exported numeric chain; exported software never imported/executed',
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-munich-optical-frame-bridge',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

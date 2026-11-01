"""Freeze and queue one tiny standalone-USD authoring check, no simulator."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol=json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:raise RuntimeError('Final source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed source first')
    if any((p/'submission.txt').exists() for p in (ROOT/'runs').glob('*-brick-material-authoring')):raise RuntimeError('One source-contract check; no automatic retry')
    for path,digest in protocol['source_pins'].items():
        if sha(path)!=digest:raise RuntimeError('Pinned source changed: '+path)
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-brick-material-authoring')
    snapshot.mkdir()
    shutil.copytree(HERE,snapshot/'code',ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json','artifacts'))
    extension=protocol['usd_extension']
    script=['#!/usr/bin/env bash','set -eo pipefail','cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(extension),
        'export LD_LIBRARY_PATH='+shlex.quote('/home/faps/miniforge3/envs/unitree_sim_env/lib:'+extension+'/bin'),
        'exec timeout --signal=TERM --kill-after=2s 7s '+shlex.join([protocol['runtime_python'],str(snapshot/'code/test_authoring.py'),'--output',str(snapshot/'output')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(script))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'maximum_active_seconds':10,'maximum_jobs':1,'Kit_started':False,'physics_steps':0,
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-brick-material-authoring',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__=='__main__':main()

"""One fixed saved-point job; no new physics, cook or contact retry."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol=json.loads((HERE/'protocol.json').read_text())
    if protocol['execution_authorized'] is not True:
        raise RuntimeError('Review the one saved-data diagnostic before execution')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):
        raise RuntimeError('Commit reviewed diagnostic sources/config first')
    for old in (ROOT/'runs').glob('*-stage2-contact-point-diagnostic'):
        if (old/'submission.txt').exists():raise RuntimeError('Fixed one-job diagnostic already submitted; no automatic retry')
    source=Path(protocol['source_snapshot']);base=json.loads((source/'manifest.json').read_text())
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-contact-point-diagnostic')
    snapshot.mkdir()
    for relative,digest in base['sha256'].items():
        if relative=='launch.sh':continue
        origin=source/relative
        if sha(origin)!=digest:raise RuntimeError('Immutable source changed: '+relative)
        destination=snapshot/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(origin,destination)
    code=snapshot/'experiments/stage2_exploratory_20261025/diagnostics'
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    command=[PYTHON,str(code/'contact_points.py'),'--inputs',str(code/'protocol.json'),'--output',str(snapshot/'output')]
    launch=['#!/usr/bin/env bash','set -eo pipefail','cd '+shlex.quote(str(snapshot)),
            'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
            'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
            'exec timeout --signal=TERM --kill-after=2s 8s '+shlex.join(command),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'maximum_active_seconds':10,'maximum_jobs':1,'source_snapshot':str(source),
        'prior_case_seconds':protocol['prior_case_seconds'],'aggregate_case_ceiling_seconds':1800,
        'physics_steps':0,'source_data':'Fixed absolute prior-run artifacts, each SHA-pinned in copied protocol; no mutable code dependency',
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-failed-contact-point-diagnostic',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

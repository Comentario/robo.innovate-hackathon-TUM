"""Freeze the bounded native static benchmark and submit it in default Pueue."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXP=Path(__file__).resolve().parent;ROOT=EXP.parents[1]
PYTHON=Path('/home/faps/miniforge3/envs/unitree_sim_env/bin/python')


def main():
    scope=[str(EXP.relative_to(ROOT)),'experiments/sim_views_20261024/render_views.py',
           'experiments/sim_views_20261024/geometry.json','experiments/sim_views_20261024/cameras.json',
           'challenge2','configs/workcell.json']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT,text=True):
        raise SystemExit('Commit scoped benchmark/render source before freezing')
    protocol=json.loads((EXP/'evaluation/protocol.json').read_text())
    if hashlib.sha256((EXP/'benchmark.json').read_bytes()).hexdigest()!=protocol['benchmark_sha256']:
        raise ValueError('Frozen benchmark changed')
    benchmark=json.loads((EXP/'benchmark.json').read_text())
    for relative in ['experiments/sim_views_20261024/geometry.json','experiments/sim_views_20261024/cameras.json']:
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=benchmark['frozen_sources_sha256'][relative]:
            raise ValueError(f'Frozen geometry/camera settings changed: {relative}')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot=ROOT/'runs'/f'{stamp}-partial-disassembly-render';code=snapshot/'experiments/partial_disassembly_20261024';code.mkdir(parents=True)
    for folder in ['challenge2','.deps']:
        shutil.copytree(ROOT/folder,snapshot/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (snapshot/'configs').mkdir();shutil.copy2(ROOT/'configs/workcell.json',snapshot/'configs/workcell.json')
    legacy=snapshot/'experiments/sim_views_20261024';legacy.mkdir(parents=True)
    for name in ['render_views.py','geometry.json','cameras.json']:
        shutil.copy2(ROOT/'experiments/sim_views_20261024'/name,legacy/name)
    for name in ['render_adapter.py','render_supervisor.py','benchmark.json','submit_render.py']:
        shutil.copy2(EXP/name,code/name)
    out=snapshot/'render_output'
    command=[str(PYTHON),str(code/'render_supervisor.py'),'--benchmark',str(code/'benchmark.json'),
             '--geometry',str(legacy/'geometry.json'),'--cameras',str(legacy/'cameras.json'),
             '--output',str(out),'--python',str(PYTHON)]
    prefix=PYTHON.parent.parent;conda=prefix.parent.parent/'etc/profile.d/conda.sh'
    launch=['#!/usr/bin/env bash','set -eo pipefail',f'source {shlex.quote(str(conda))}',
            f'conda activate {shlex.quote(str(prefix))}','set -u',f'cd {shlex.quote(str(snapshot))}',
            f'export PYTHONPATH={shlex.quote(str(snapshot/".deps")+":"+str(snapshot))}',
            'export ROBO_PUEUE_JOB=1','export PYTHONDONTWRITEBYTECODE=1','export OMP_NUM_THREADS=2','export OPENBLAS_NUM_THREADS=2',
            shlex.join(command),'test -f render_output/run_complete.json','']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'created_utc':stamp,'benchmark_sha256':protocol['benchmark_sha256'],'runtime_python':str(PYTHON),
              'reserved_policy':'Capture integrity only; reserved sensor/prediction/score feedback sealed until finalmethodfreeze',
              'sha256':{str(f.relative_to(snapshot)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snapshot.rglob('*')) if f.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    task=subprocess.run(['pueue','add','--label','robo26-partial-render',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(task.stdout);print('Snapshot:',snapshot);print(task.stdout.strip())


if __name__=='__main__':main()

"""Freeze ONE eccentric diagnostic and add it to the default Pueue queue."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EXP = Path(__file__).resolve().parent
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def main():
    scope = [str(EXP.relative_to(ROOT)), 'challenge2/layout.py',
             'experiments/partial_disassembly_20261024/render_supervisor.py']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT):
        raise SystemExit('Commit reviewed source/protocol before freezing')
    protocol = json.loads((EXP/'protocol.json').read_text())
    if protocol['maximum_steps'] != 8 or protocol['wall_limit_s'] != 180:
        raise RuntimeError('Diagnostic budget differs from the frozen one-case plan')
    for path, digest in {**protocol['frozen_helpers'],'.deps/bricksim/core.cpython-311-x86_64-linux-gnu.so':protocol['native_core_sha256']}.items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen helper/native input changed: '+path)
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-eccentric-diagnostic')
    snapshot.mkdir()
    for name in ('.deps','challenge2'):
        shutil.copytree(ROOT/name,snapshot/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(EXP,snapshot/'experiments'/EXP.name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    supervisor = snapshot/'experiments/partial_disassembly_20261024'; supervisor.mkdir()
    shutil.copy2(ROOT/'experiments/partial_disassembly_20261024/render_supervisor.py',supervisor/'render_supervisor.py')
    command = [PYTHON,str(snapshot/'experiments'/EXP.name/'supervise.py'),'--python',PYTHON,'--output',str(snapshot/'output')]
    lines = ['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        shlex.join(command),'test -f output/diagnostic_complete.json','']
    (snapshot/'launch.sh').write_text('\n'.join(lines))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'scope':'ONE eccentric2actor/1link8step native diagnostic; no parameter sweep and never replacement for failed full300 idle',
        'sha256':{str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result = subprocess.run(['pueue','add','--label','robo26-stage2-eccentric-diagnostic',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print('Snapshot:',snapshot); print(result.stdout.strip())


if __name__ == '__main__': main()

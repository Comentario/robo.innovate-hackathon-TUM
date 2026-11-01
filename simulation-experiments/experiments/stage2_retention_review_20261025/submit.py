"""One immutable saved-sample diagnosis in the default hardware queue."""
from datetime import datetime, timezone
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
    plan=json.loads((HERE/'protocol.json').read_text())
    if not plan['execution_authorized']:raise RuntimeError('Final independent source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed source first')
    if any((p/'submission.txt').exists() for p in (ROOT/'runs').glob('*-stage2-retention-review')):raise RuntimeError('One saved-only job; no automatic retry')
    if [c['steps'] for c in plan['cases']] != [[1853,1900,1950,2000,2050,2100,2112,2113],[1853]]:raise RuntimeError('Fixed sample list changed')
    for path,digest in plan['input_sha256'].items():
        if sha(path)!=digest:raise RuntimeError('Saved input changed: '+path)
    prior=plan['prior_supervisor']
    if sha(prior['path'])!=prior['sha256']:raise RuntimeError('Prior clock changed')
    if json.loads(Path(prior['path']).read_text())['cumulative_case_seconds']!=plan['prior_case_seconds']:raise RuntimeError('Retain prior clock')
    if plan['prior_case_seconds']+30>2200 or plan['aggregate_case_ceiling_seconds']!=2200:raise RuntimeError('No budget extension')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-retention-review')
    snapshot.mkdir()
    shutil.copytree(HERE,snapshot/'code',ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    launch=['#!/usr/bin/env bash','set -euo pipefail','cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'exec timeout --signal=TERM --kill-after=2s 25s '+shlex.join([PYTHON,str(snapshot/'code/diagnose.py'),'--output',str(snapshot/'output')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'physics_steps':0,'maximum_jobs':1,'maximum_active_seconds':30,'prior_case_seconds':plan['prior_case_seconds'],'case_limit_seconds':2200,'automatic_retry':False,'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-saved-retention-review',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot);print(result.stdout.strip())

if __name__=='__main__':main()

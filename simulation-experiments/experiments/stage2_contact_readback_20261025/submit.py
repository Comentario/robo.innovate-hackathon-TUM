"""Queue one immutable startup-only readback in the default scheduler."""
from datetime import datetime,timezone
import hashlib,json,shlex,shutil,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    p=json.loads((HERE/'protocol.json').read_text())
    if not p['execution_authorized']:raise RuntimeError('Final independent source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed source first')
    if any((s/'submission.txt').exists() for s in (ROOT/'runs').glob('*-stage2-contact-readback')):raise RuntimeError('One startup readback only; no retry')
    for name,digest in p['input_sha256'].items():
        if sha(name)!=digest:raise RuntimeError('Pinned input changed: '+name)
    prior=json.loads(Path(p['prior_supervisor']['path']).read_text())
    if prior['cumulative_case_seconds']!=p['prior_case_seconds'] or prior['retention_fixture_passed'] is not False:raise RuntimeError('Retain failed prior/clock')
    if p['maximum_active_seconds']!=90 or p['aggregate_case_ceiling_seconds']!=2500 or p['prior_case_seconds']+90>2500:raise RuntimeError('No budget extension')
    source=Path(p['source_snapshot']);parent=json.loads((source/'manifest.json').read_text())
    for name,digest in parent['sha256'].items():
        if sha(source/name)!=digest:raise RuntimeError('Immutable initializer dependency changed: '+name)
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-contact-readback');snapshot.mkdir()
    shutil.copytree(HERE,snapshot/'code',ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    launch=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(source/'.deps')+':'+str(source)),
        'exec timeout --signal=TERM --kill-after=3s 85s '+shlex.join([PYTHON,str(snapshot/'code/pipeline.py')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_snapshot':str(source),'source_manifest_sha256':sha(source/'manifest.json'),'maximum_active_seconds':90,
        'maximum_jobs':1,'measured_physics_steps':0,'prior_case_seconds':p['prior_case_seconds'],'case_limit_seconds':2500,
        'automatic_retry':False,'sha256':{str(f.relative_to(snapshot)):sha(f) for f in sorted(snapshot.rglob('*')) if f.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-startup-contact-readback',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())
if __name__=='__main__':main()

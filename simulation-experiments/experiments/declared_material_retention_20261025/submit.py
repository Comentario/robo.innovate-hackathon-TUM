"""Freeze ONE corrected-model regression, retaining the full historical ledger."""
from datetime import datetime,timezone
import hashlib,json,shlex,shutil,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=json.loads((HERE/'protocol.json').read_text())
    if not p['execution_authorized']:raise RuntimeError('Final independent source and budget review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed case first')
    if any((s/'submission.txt').exists() for s in (ROOT/'runs').glob('*-declared-material-retention')):raise RuntimeError('One corrected-model baseline only; no retry')
    def verify(v):
        if isinstance(v,dict):
            if 'path' in v and 'sha256' in v and sha(v['path'])!=v['sha256']:raise RuntimeError('Changed pinned evidence: '+v['path'])
            for child in v.values():verify(child)
        elif isinstance(v,list):
            for child in v:verify(child)
    verify(p)
    for path,digest in p['input_sha256'].items():
        if sha(path)!=digest:raise RuntimeError('Changed pinned input: '+path)
    clock=json.loads(Path(p['prior_supervisor']['path']).read_text())
    if clock['cumulative_case_seconds']!=p['prior_case_seconds']:raise RuntimeError('Prior ledger must remain authoritative')
    if (p['maximum_active_seconds']!=300 or p['aggregate_case_ceiling_seconds']!=3000
        or p['previous_case_ceiling_seconds']!=2800 or p['prior_case_seconds']+300>3000
        or p['maximum_jobs']!=1 or p['maximum_improvement_rounds']!=0):raise RuntimeError('Frozen prospective amendment differs')
    source=Path(p['source_snapshot']);old=json.loads((source/'manifest.json').read_text())
    for relative,digest in old['sha256'].items():
        if sha(source/relative)!=digest:raise RuntimeError('Frozen1825 dependency changed: '+relative)
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-declared-material-retention');snapshot.mkdir()
    for relative in old['sha256']:
        if relative=='launch.sh':continue
        target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/relative,target)
    code=snapshot/'experiments'/HERE.name
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json','artifacts'))
    shutil.copy2(p['binding_helper']['path'],code/'materials.py')
    if sha(code/'source_science.json')!=p['source_science_sha256']:raise RuntimeError('1825 science changed')
    launch=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=5s 290s '+shlex.join([PYTHON,str(code/'pipeline.py')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_snapshot':str(source),'maximum_active_seconds':300,'maximum_jobs':1,'prior_case_seconds':p['prior_case_seconds'],
        'previous_case_limit_seconds':2800,'case_limit_seconds':3000,'old_fixture_improvements_closed':True,'maximum_new_improvements':0,
        'fresh_control_steps':1500,'maximum_pick_steps':1500,'automatic_retry':False,
        'sha256':{str(f.relative_to(snapshot)):sha(f) for f in sorted(snapshot.rglob('*')) if f.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-declared-material-retention',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())

if __name__=='__main__':main()

"""Snapshot and queue one final fixed-target response-criterion reassessment."""
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
    plan=json.loads((HERE/'protocol.json').read_text())
    if not plan['execution_authorized']:raise RuntimeError('Final independent review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed fixture first')
    if any((p/'submission.txt').exists() for p in (ROOT/'runs').glob('*-stage2-finger-response')):raise RuntimeError('One final response-criterion pick, no retry')
    def verify(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                if sha(value['path'])!=value['sha256']:raise RuntimeError('Pinned evidence changed: '+value['path'])
            for nested in value.values():verify(nested)
        elif isinstance(value,list):
            for nested in value:verify(nested)
    verify(plan)
    prior=json.loads(Path(plan['prior_supervisor']['path']).read_text())
    if prior['cumulative_case_seconds']!=plan['prior_case_seconds'] or prior['control_passed'] is not True or prior['retention_fixture_passed'] is not False:raise RuntimeError('Retain failed fixture and passed control/clock')
    if plan['maximum_active_seconds']!=150 or plan['aggregate_case_ceiling_seconds']!=2800 or plan['prior_case_seconds']+150>2800:raise RuntimeError('Prospective retained budget differs')
    if plan['control_steps']!=plan['maximum_physics_steps'] or plan['control_steps']!=1500:raise RuntimeError('Matched frozen12.5s observation horizon differs')
    old=json.loads(Path(plan['original_control_protocol']['path']).read_text())
    if not plan['position_only_admission'] or (plan['improvement_round']!=3 or plan['maximum_authorized_improvement_rounds']!=3):raise RuntimeError('One final response-criterion round')
    if any(plan[k]!=old[k] for k in plan['control_physical_equivalence_keys']):raise RuntimeError('Control-active physical parameter changed')
    control=json.loads(Path(plan['original_control_audit']['path']).read_text())
    if control['proceed_gate_passed'] is not True or control['steps']!=1500:raise RuntimeError('Original control did not pass')
    source=Path(plan['source_snapshot']);parent=json.loads((source/'manifest.json').read_text())
    for rel,digest in plan['helper_pins'].items():
        if sha(source/rel)!=digest:raise RuntimeError('Frozen helper changed: '+rel)
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-finger-response');snapshot.mkdir()
    for rel,digest in parent['sha256'].items():
        if rel=='launch.sh':continue
        origin=source/rel
        if sha(origin)!=digest:raise RuntimeError('Parent snapshot changed: '+rel)
        target=snapshot/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(origin,target)
    code=snapshot/'experiments'/HERE.name
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json'))
    if sha(code/'source_science.json')!=plan['source_science_sha256']:raise RuntimeError('Original control/contact science changed')
    launch=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=5s 140s '+shlex.join([PYTHON,str(code/'pipeline.py')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_snapshot':str(source),'protocol_sha256':sha(code/'protocol.json'),'maximum_active_seconds':150,'maximum_jobs':1,
        'prior_case_seconds':plan['prior_case_seconds'],'case_limit_seconds':2800,'previous_case_limit_seconds':2800,
        'fixture_only':True,'matched_control_steps':1500,'control_reused':True,'improvement_round':3,'maximum_pick_steps':1500,'automatic_retry':False,'H_authorized':False,
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-fixed-target-finger-response',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())
if __name__=='__main__':main()

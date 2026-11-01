"""Freeze one final-round initialization diagnostic; no control/pick submission."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
TEMPLATE=ROOT/'runs/20261025T105902.347591Z-stage2-pick-I-pick'
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol=json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Independent source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):
        raise RuntimeError('Commit reviewed initialization code before freezing')
    prior=Path(protocol['prior_supervisor']);nominal=Path(protocol['nominal_capture_metadata'])
    if sha(prior)!=protocol['prior_supervisor_sha256'] or sha(nominal)!=protocol['nominal_capture_metadata_sha256']:
        raise RuntimeError('Retained cost/nominal robot provenance changed')
    clock=json.loads(prior.read_text())
    if clock['cumulative_case_seconds']!=protocol['prior_case_seconds'] or clock['proceed_gate_passed'] is not False:
        raise RuntimeError('Preserve failed prior trial and full cost')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-initialization-r3')
    snapshot.mkdir()
    base=json.loads((TEMPLATE/'manifest.json').read_text())
    for relative,digest in base['sha256'].items():
        if relative=='launch.sh':continue
        source=TEMPLATE/relative
        if sha(source)!=digest:raise RuntimeError('Frozen template changed: '+relative)
        destination=snapshot/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
    destination=snapshot/'experiments/stage2_pick_20261025/initialization'
    shutil.copytree(HERE,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','results.json','inputs'))
    inputs=destination/'inputs';inputs.mkdir()
    shutil.copy2(nominal,inputs/'nominal_capture_metadata.json')
    robot_initialization=TEMPLATE/'output/robot_initialization.json'
    shutil.copy2(robot_initialization,inputs/'nominal_robot_initialization.json')
    shutil.copy2(prior,inputs/'prior_supervisor.json')
    state=json.loads(nominal.read_text())['initial_proprioception']
    seed={'joint_names':json.loads(robot_initialization.read_text())['joint_names'],
          'q':state['q'],'tcp_pose_world_wxyz':state['tcp_pose_world_wxyz']}
    (inputs/'nominal_proprioception.json').write_text(json.dumps(seed,indent=2)+'\n')
    launch=['#!/usr/bin/env bash','set -eo pipefail',
            'source /home/faps/miniforge3/etc/profile.d/conda.sh',
            'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u',
            'cd '+shlex.quote(str(snapshot)),
            'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
            'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
            'exec timeout --signal=TERM --kill-after=3s 57s '+shlex.join([PYTHON,str(destination/'pipeline.py')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'reused_template':str(TEMPLATE),'template_source_commit':base['source_commit'],
       'prior_case_wall_seconds':protocol['prior_case_seconds'],'maximum_active_seconds':60,'aggregate_case_ceiling_seconds':1800,
       'maximum_diagnostic_jobs':1,'maximum_candidates_tested':1,
       'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-final-pregrasp-initialization',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

"""One fresh control then one conditional exploratory I pick, default queue only."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TEMPLATE=ROOT/'runs/20261025T105902.347591Z-stage2-pick-I-pick'
SOURCE=ROOT/'runs/20261025T115521.846258Z-stage2-initialization-r3'
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--mode',choices=['control','pick'],required=True)
    parser.add_argument('--predecessor-control',type=Path)
    args=parser.parse_args();science=read(HERE/'protocol.json');science_sha=sha(HERE/'protocol.json')
    if not science['execution_authorized']:
        raise RuntimeError('Independent source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):
        raise RuntimeError('Commit reviewed experiment before snapshot')
    for previous in (ROOT/'runs').glob('*-stage2-exploratory-I-'+args.mode):
        manifest=previous/'manifest.json'
        if manifest.exists() and read(manifest).get('protocol_sha256')==science_sha and (previous/'submission.txt').exists():
            raise RuntimeError('This fixed phase was already submitted; no retry is authorized')
    prior_path=SOURCE/'pipeline_supervisor.json'
    if args.mode=='pick':
        if args.predecessor_control is None:
            parser.error('Fresh matched control is required')
        report=read(args.predecessor_control);prior_path=args.predecessor_control.parent.parent/'pipeline_supervisor.json';clock=read(prior_path)
        if (report.get('case')!='I' or report.get('mode')!='control' or report.get('proceed_gate_passed') is not True
            or report.get('protocol_sha256')!=science_sha or report.get('stationary_guard_passed') is not True
            or clock.get('proceed_gate_passed') is not True or clock.get('within_budget') is not True
            or clock.get('audit_sha256')!=sha(args.predecessor_control)):
            raise RuntimeError('Only current-protocol passing control can authorize the conditional pick')
    elif args.predecessor_control is not None:
        parser.error('Control has no control predecessor')
    clock=read(prior_path);prior=float(clock['cumulative_case_seconds'])
    if prior<science['prior_case_clock']['prior_case_seconds'] or prior>=1800:
        raise RuntimeError('Invalid remaining aggregate budget')
    if sha(SOURCE/'pipeline_supervisor.json')!=science['prior_case_clock']['source_sha256']:
        raise RuntimeError('Old cost must remain immutable')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-exploratory-I-'+args.mode)
    snapshot.mkdir();base=read(TEMPLATE/'manifest.json')
    for relative,digest in base['sha256'].items():
        if relative=='launch.sh':continue
        source=TEMPLATE/relative
        if sha(source)!=digest:raise RuntimeError('Immutable base source changed: '+relative)
        destination=snapshot/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    code=snapshot/'experiments'/HERE.name
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','inputs','results.json'))
    inputs=code/'inputs';inputs.mkdir()
    # Reuse frozen model evidence. The prior control bridge is not an admission
    # source: a new matched control is required for this fixed q and policy.
    for p in (snapshot/'experiments/stage2_pick_20261025/inputs').iterdir():
        if p.is_file():shutil.copy2(p,inputs/p.name)
    shutil.copy2(TEMPLATE/'experiments/stage2_pick_20261025/protocol.json',inputs/'original_science.json')
    shutil.copy2(HERE/'pregrasp_authorization.json',inputs/'pregrasp_authorization.json')
    files={'source_1807_audit.json':'audit/evaluation.json','source_1807_derivation.json':'output/kinematic_derivation.json',
           'source_1807_chain.json':'output/kinematic_chain.json','source_1807_robot_initialization.json':'output/robot_initialization.json',
           'source_1807_metadata.json':'output/diagnostic_metadata.json','source_1807_graph.json':'output/evaluation_truth/graph.json',
           'source_1807_supervisor.json':'pipeline_supervisor.json'}
    for name,relative in files.items():shutil.copy2(SOURCE/relative,inputs/name)
    shutil.copy2(prior_path,inputs/'prior_case_pipeline_supervisor.json')
    command=[PYTHON,str(code/'pipeline.py'),'--case','I','--mode',args.mode,
             '--prior-wall-seconds',repr(prior),'--prior-case-supervisor',str(inputs/'prior_case_pipeline_supervisor.json')]
    if args.predecessor_control is not None:
        shutil.copy2(args.predecessor_control,inputs/'predecessor_control.json')
        shutil.copy2(prior_path,inputs/'predecessor_control_pipeline_supervisor.json')
        command+=['--predecessor-control',str(inputs/'predecessor_control.json')]
    launch=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
            'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
            'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
            'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),shlex.join(command),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'base_source_commit':base['source_commit'],'immutable_source_scene':str(TEMPLATE),'case':'I','mode':args.mode,
        'protocol_sha256':science_sha,'prior_case_wall_seconds':prior,'case_limit_seconds':1800,
        'maximum_attempts_this_phase':1,'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-exploratory-I-'+args.mode,shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

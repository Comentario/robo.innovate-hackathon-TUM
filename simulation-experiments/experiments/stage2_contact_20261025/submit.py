"""Freeze one authorized stock or independently gated proxy phase in default Pueue."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy-stage',choices=('G','D','R'))
    parser.add_argument('--predecessor-audit',type=Path)
    parser.add_argument('--approved-proxy',type=Path)
    args=parser.parse_args()
    scope=['experiments/stage2_contact_20261025','experiments/stage2_idle_20261025',
           'experiments/final_workcell_20261024','challenge2','experiments/partial_disassembly_20261024/render_supervisor.py']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT):raise SystemExit('Commit reviewed B0 and independent protocol before freezing')
    protocol=json.loads((HERE/'protocol.json').read_text())
    if args.proxy_stage:
        if args.proxy_stage=='G':
            if args.predecessor_audit or args.approved_proxy:raise RuntimeError('G has no predecessor')
        else:
            if args.predecessor_audit is None or args.approved_proxy is None:raise RuntimeError('D/R require independent predecessor audit and approved G geometry')
            previous=json.loads(args.predecessor_audit.read_text())
            expected='G' if args.proxy_stage=='D' else 'D'
            if (previous['phase']!=expected or not previous['proceed_gate_passed']
                or previous['protocol_sha256']!=hashlib.sha256((HERE/'evaluation/proxy_protocol.json').read_bytes()).hexdigest()):
                raise RuntimeError('Predecessor did not pass the frozen R3 audit')
            expected_hash=previous['proxy_geometry_sha256'] if expected=='G' else previous['approved_G_proxy_geometry_sha256']
            if hashlib.sha256(args.approved_proxy.read_bytes()).hexdigest()!=expected_hash:raise RuntimeError('Approved G geometry is not the audited artifact')
    elif protocol['execution_authorized_cases']!=['B0_stock']:raise RuntimeError('Only the gated final R3 phases are authorized now')
    for name,digest in protocol['input_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Frozen B0 input changed: '+name)
    suffix='-stage2-contact-B0-stock' if args.proxy_stage is None else '-stage2-contact-R3-'+args.proxy_stage
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+suffix)
    snapshot.mkdir()
    for name in ('.deps','challenge2','configs'):
        shutil.copytree(ROOT/name,snapshot/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('stage2_contact_20261025','stage2_idle_20261025','final_workcell_20261024'):
        shutil.copytree(ROOT/'experiments'/name,snapshot/'experiments'/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    partial=snapshot/'experiments/partial_disassembly_20261024';partial.mkdir()
    shutil.copy2(ROOT/'experiments/partial_disassembly_20261024/render_supervisor.py',partial/'render_supervisor.py')
    command=[PYTHON,str(snapshot/'experiments'/HERE.name/'supervise.py'),'--python',PYTHON,'--output',str(snapshot/'output')]
    if args.proxy_stage:command+=['--proxy-stage',args.proxy_stage]
    if args.approved_proxy:
        shutil.copy2(args.approved_proxy,snapshot/'approved_G_proxy.json')
        command+=['--approved-proxy',str(snapshot/'approved_G_proxy.json')]
        shutil.copy2(args.predecessor_audit,snapshot/'predecessor_audit.json')
    lines=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        shlex.join(command),'']
    (snapshot/'launch.sh').write_text('\n'.join(lines))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'case':'B0_stock' if args.proxy_stage is None else 'R3_proxy_'+args.proxy_stage,
        'scope':'Final contact round3: one proxy, G cooked-fidelity audit then conditional D centered contact and R reserved offset. No retries, coarsening, fourth round, tangent motion or extraction.',
        'sha256':{str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-stage2-contact'+suffix,shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print('Snapshot:',snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

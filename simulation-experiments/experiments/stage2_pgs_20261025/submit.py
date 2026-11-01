"""Freeze and queue one explicitly gated final-round PGS phase."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('A','B','C'),required=True)
    parser.add_argument('--predecessor-audit',type=Path)
    args=parser.parse_args()
    protocol=json.loads((HERE/'protocol.json').read_text())
    scope=['experiments/stage2_pgs_20261025','experiments/stage2_eccentric_20261025',
        'experiments/stage2_idle_20261025','experiments/final_workcell_20261024','challenge2',
        'experiments/partial_disassembly_20261024/render_adapter.py',
        'experiments/partial_disassembly_20261024/render_supervisor.py','experiments/stage1_20261025/benchmark.json']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT):
        raise SystemExit('Commit reviewed sources and all A/B/C protocols before freezing')
    if args.phase=='A':
        if args.predecessor_audit: parser.error('PhaseA has no predecessor')
    else:
        if args.predecessor_audit is None: parser.error('An independent passing predecessor audit is required')
        previous=json.loads(args.predecessor_audit.read_text())
        if (previous['phase'] != ('A' if args.phase=='B' else 'B') or not previous['proceed_gate_passed']
            or previous['protocol_sha256'] != sha(HERE/'evaluation/protocol.json')):
            raise RuntimeError('Predecessor phase has not passed the frozen independent audit')
    for path,digest in protocol['frozen_inputs'].items():
        if sha(ROOT/path)!=digest: raise RuntimeError('Frozen input differs: '+path)
    if (sha(ROOT/'.deps/bricksim/core.cpython-311-x86_64-linux-gnu.so') != protocol['native_core_sha256']
        or sha(ROOT/protocol['reserved_manifest']) != protocol['reserved_manifest_sha256']):
        raise RuntimeError('Native binary/reserved state manifest differs')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-round3-PGS-'+args.phase)
    snapshot.mkdir()
    for name in ('.deps','challenge2','configs'):
        shutil.copytree(ROOT/name,snapshot/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('stage2_pgs_20261025','stage2_eccentric_20261025','stage2_idle_20261025',
                 'final_workcell_20261024','sim_views_20261024'):
        shutil.copytree(ROOT/'experiments'/name,snapshot/'experiments'/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    partial=snapshot/'experiments/partial_disassembly_20261024'; partial.mkdir()
    for filename in ('render_supervisor.py','render_adapter.py'):
        shutil.copy2(ROOT/'experiments/partial_disassembly_20261024'/filename,partial/filename)
    stage1=snapshot/'experiments/stage1_20261025';stage1.mkdir()
    shutil.copy2(ROOT/protocol['reserved_manifest'],stage1/'benchmark.json')
    if args.predecessor_audit: shutil.copy2(args.predecessor_audit,snapshot/'predecessor_audit.json')
    command=[PYTHON,str(snapshot/'experiments'/HERE.name/'supervise.py'),'--phase',args.phase,
        '--python',PYTHON,'--output',str(snapshot/'output')]
    lines=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        shlex.join(command),'']
    (snapshot/'launch.sh').write_text('\n'.join(lines))
    (snapshot/'manifest.json').write_text(json.dumps({'phase':args.phase,'improvement_round':3,'last_round':True,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'scope':'One PGS configuration; gated A8→Bfull300120→CreservedH120, no retry/sweep or contact/manipulation claim',
        'capture_protocol_sha256':sha(HERE/'protocol.json'),
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-stage2-round3-PGS-'+args.phase,
        shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print('Snapshot:',snapshot); print(result.stdout.strip())


if __name__=='__main__': main()

"""Freeze the unchanged full-stack idle protocol and queue it in default Pueue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic',action='store_true',help='Observe native utilization/debug dumps for at most8steps; no idle pass')
    parser.add_argument('--osqp-epsilon',choices=('1e-4','1e-6'),help='Existing coupled numerical-epsilon diagnostic only; not a physical parameter')
    parser.add_argument('--contact-observer',action='store_true',help='One raw-contact diagnostic at explicit default epsilon')
    parser.add_argument('--velocity16',action='store_true',help='Round2 single source velocity4→16 full120-step comparison')
    args=parser.parse_args()
    if args.osqp_epsilon and not (args.diagnostic or args.velocity16):
        parser.error('--osqp-epsilon is restricted to the bounded diagnostic')
    if args.velocity16 and (args.diagnostic or args.contact_observer or args.osqp_epsilon != '1e-4'):
        parser.error('--velocity16 requires --osqp-epsilon 1e-4 and excludes diagnostic/contact modes')
    if args.contact_observer and (not args.diagnostic or args.osqp_epsilon != '1e-4'):
        parser.error('--contact-observer requires --diagnostic --osqp-epsilon 1e-4')
    scope=['experiments/stage2_idle_20261025','experiments/final_workcell_20261024','challenge2']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT):
        raise SystemExit('Commit scoped idle source and configuration before freezing')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    suffix=('-stage2-native-epsilon-'+args.osqp_epsilon) if args.osqp_epsilon else ('-stage2-native-diagnostic' if args.diagnostic else '-stage2-full300-idle')
    if args.contact_observer: suffix='-stage2-native-contacts-1e-4'
    if args.velocity16: suffix='-stage2-round2-source-velocity16'
    snap=ROOT/'runs'/(stamp+suffix);snap.mkdir()
    for name in ('.deps','challenge2','configs'):
        shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('stage2_idle_20261025','final_workcell_20261024'):
        shutil.copytree(ROOT/'experiments'/name,snap/'experiments'/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    supervisor=snap/'experiments/partial_disassembly_20261024';supervisor.mkdir()
    shutil.copy2(ROOT/'experiments/partial_disassembly_20261024/render_supervisor.py',supervisor/'render_supervisor.py')
    command=[PYTHON,str(snap/'experiments/stage2_idle_20261025'/('supervise_velocity16.py' if args.velocity16 else 'supervise_diagnostic.py' if args.diagnostic else 'supervise_idle.py')),'--python',PYTHON,'--output',str(snap/'output')]
    if args.osqp_epsilon:
        command += ['--osqp-epsilon',args.osqp_epsilon]
    if args.contact_observer:
        command += ['--contact-observer']
    lines=['#!/usr/bin/env bash','set -eo pipefail',
           'source /home/faps/miniforge3/etc/profile.d/conda.sh',
           'conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snap)),
           'export PYTHONPATH='+shlex.quote(str(snap/'.deps')+':'+str(snap)),
           'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
           shlex.join(command),'test -f output/'+('velocity16_complete.json' if args.velocity16 else 'diagnostic_complete.json' if args.diagnostic else 'idle_complete.json'),'']
    (snap/'launch.sh').write_text('\n'.join(lines))
    (snap/'manifest.json').write_text(json.dumps({
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'numerical_epsilon_requested':args.osqp_epsilon,
        'contact_observer_requested':args.contact_observer,
        'velocity16_round2_requested':args.velocity16,
        'scope':('Round2 source-only velocity4→16 constraint-quality sensitivity, full300/930,120steps firstfailure,180s; unchanged physical/native break settings; surviving is an idle candidate only' if args.velocity16 else 'Public raw tensor contact observation, max8/firstfailure; process-local disableContactProcessing=False is potentially perturbing and requires baseline-equivalence evaluation; no idle/contact-load validation claim'
            if args.contact_observer else ('Samephysicalparameters,debugloggingandcouplednumericalepsilonvariant,max8,noidlepass' if args.osqp_epsilon else 'Samephysicalparameters,debugloggingonly,max8,noidlepass') if args.diagnostic else 'One120-stepnativefull300idle-STOCKcollisionbaseline,noimageorgraspclaims'),
        'sha256':{str(p.relative_to(snap)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(snap.rglob('*')) if p.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-stage2-round2-velocity16' if args.velocity16 else 'robo26-stage2-native-contacts' if args.contact_observer else ('robo26-stage2-epsilon-'+args.osqp_epsilon) if args.osqp_epsilon else ('robo26-stage2-native-diagnostic' if args.diagnostic else 'robo26-stage2-full300-idle'),shlex.join(['bash',str(snap/'launch.sh')])],check=True,capture_output=True,text=True)
    (snap/'submission.txt').write_text(result.stdout);print('Snapshot:',snap);print(result.stdout.strip())


if __name__=='__main__':main()

"""Freeze and queue the two bounded control-alignment stages in default Pueue."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import re
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['A','B'],required=True);parser.add_argument('--predecessor',type=Path);parser.add_argument('--corrected-from',type=Path);args=parser.parse_args()
    source_paths=[HERE,ROOT/'challenge2/jacob_control',ROOT/'vendor',ROOT/'tests/test_jacob_control.py',ROOT/'tests/test_control_alignment_audit.py',ROOT/'tests/test_batched_source.py']
    if subprocess.check_output(['git','status','--porcelain','--',*map(str,source_paths)],cwd=ROOT):raise RuntimeError('Commit reviewed source first')
    policy=json.loads((HERE/'protocol.json').read_text());correction=policy['setup_correction'];prior_seconds=0.;previous=None
    recording=policy.get('recording_correction');recording_repair=bool(args.phase=='B' and args.corrected_from)
    source_bridge={}
    if recording_repair and (recording is None or args.corrected_from.resolve()!=(ROOT/recording['failed_snapshot']).resolve()):raise RuntimeError('Unknown recording correction')
    if args.phase=='B':
        if args.predecessor is None:raise RuntimeError('Phase B requires the passing phase-A snapshot')
        previous=args.predecessor.resolve();audit=json.loads((previous/'audit/evaluation.json').read_text())
        if not audit['control_alignment_passed'] or audit['phase']!='A':raise RuntimeError('Expected passing phase-A audit')
        if not (previous/'output/run_complete.json').exists():raise RuntimeError('Phase-A completion marker missing')
        old_manifest=json.loads((previous/'manifest.json').read_text())
        if old_manifest['phase']!='A':raise RuntimeError('Wrong predecessor snapshot phase')
        allowed=set(recording['allowed_existing_source_changes']) if recording_repair else set()
        if any(Path(name).parts[0] not in ('experiments','tests') for name in allowed):raise RuntimeError('Control/vendor changes are forbidden in recorder repair')
        for relative,digest in old_manifest['sha256'].items():
            if Path(relative).parts[0] in ('challenge2','configs','vendor','tests','experiments'):
                current=sha(ROOT/relative)
                if current!=digest:
                    if relative not in allowed:raise RuntimeError('Source differs from audited phase A: '+relative)
                    source_bridge[relative]={'passing_A_sha256':digest,'recording_repair_sha256':current}
        if recording_repair:
            for relative,digest in recording['reviewed_sha256'].items():
                if sha(ROOT/relative)!=digest:raise RuntimeError('Reviewed recording repair changed: '+relative)
        native=json.loads((previous/'native/build.json').read_text())
        for name,digest in native['sha256'].items():
            if sha(previous/'native'/name)!=digest:raise RuntimeError('Audited native artifact changed: '+name)
        if audit.get('native_build_sha256')!=sha(previous/'native/build.json'):
            raise RuntimeError('Phase-A audit is not bound to this native build')
        match=re.search(r'id (\d+)',(previous/'submission.txt').read_text())
        tasks=json.loads(subprocess.check_output(['pueue','status','--json'],text=True))['tasks']
        terminal=tasks[match.group(1)]['status'].get('Done') if match else None
        if not terminal or terminal['result']!='Success':raise RuntimeError('Phase-A scheduler job is not successful')
        spent=(datetime.fromisoformat(terminal['end'])-datetime.fromisoformat(terminal['start'])).total_seconds()
        prior_seconds=float(old_manifest.get('prior_case_seconds',0.))
        if recording_repair:
            failed=ROOT/recording['failed_snapshot'];failed_manifest=json.loads((failed/'manifest.json').read_text())
            if failed_manifest['source_commit']!=recording['failed_source_commit']:raise RuntimeError('Wrong original recording snapshot')
            failed_id=re.search(r'id (\d+)',(failed/'submission.txt').read_text()).group(1)
            failed_status=tasks[failed_id]['status'].get('Done')
            if not failed_status or failed_status['result']!={'Failed':124}:raise RuntimeError('Expected preserved timeout')
            failed_cost=(datetime.fromisoformat(failed_status['end'])-datetime.fromisoformat(failed_status['start'])).total_seconds()
            prior_seconds+=spent+failed_cost
            if abs(prior_seconds-recording['prior_spent_seconds'])>1e-5:raise RuntimeError('Full retained ledger differs')
            if prior_seconds+recording['maximum_corrected_seconds']>270:raise RuntimeError('Insufficient remaining recording-repair budget')
        elif prior_seconds+spent+180>270:raise RuntimeError('Insufficient aggregate budget for phase B')
    existing=[p for p in (ROOT/'runs').glob('*-control-alignment-'+args.phase.lower()) if (p/'submission.txt').exists()]
    if args.phase=='A' and existing:
        failed=ROOT/correction['failed_snapshot']
        if len(existing)!=1 or args.corrected_from is None or args.corrected_from.resolve()!=failed.resolve() or existing[0]!=failed:
            raise RuntimeError('Only the explicitly reviewed setup correction is allowed')
        if json.loads((failed/'manifest.json').read_text())['source_commit']!=correction['failed_source_commit']:raise RuntimeError('Wrong preserved setup failure')
        prior_seconds=correction['failed_full_seconds']
    elif existing:
        if not recording_repair or len(existing)!=1 or existing[0]!=(ROOT/recording['failed_snapshot']):raise RuntimeError('One baseline per phase; no automatic retry')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-control-alignment-'+args.phase.lower());snapshot.mkdir()
    for name in ('challenge2','configs','vendor','tests','experiments'):
        shutil.copytree(ROOT/name,snapshot/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.git'))
    if args.phase=='B':shutil.copytree(ROOT/'.deps',snapshot/'.deps',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    code=snapshot/HERE.relative_to(ROOT);output=snapshot/'output';commands=[]
    if args.phase=='A':
        commands.append(shlex.join([PYTHON,str(code/'build_native.py'),'--output',str(snapshot/'native')]))
        commands.append(shlex.join([PYTHON,str(code/'phase_a.py'),'--output',str(output)]))
    else:
        shutil.copytree(previous/'native',snapshot/'native');shutil.copyfile(previous/'audit/evaluation.json',snapshot/'phase_A_evaluation.json')
        commands.append(shlex.join([PYTHON,str(code/'run_sim.py'),'--output',str(output),'--headless','--enable_cameras']))
    evaluation=[PYTHON,str(code/'evaluate.py'),'--phase',args.phase,'--input',str(output),'--output',str(snapshot/'audit')]
    if args.phase=='B':evaluation+=['--predecessor-A',str(snapshot/'phase_A_evaluation.json')]
    commands.append(shlex.join(evaluation))
    (snapshot/'pipeline.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\n'+'\n'.join(commands)+'\n')
    limit=(80 if prior_seconds else 85) if args.phase=='A' else (65 if recording_repair else 175)
    lines=['#!/usr/bin/env bash','set -eo pipefail','source /home/faps/miniforge3/etc/profile.d/conda.sh','conda activate /home/faps/miniforge3/envs/unitree_sim_env','set -u','cd '+shlex.quote(str(snapshot)),
           'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OSQP_EPSILON=1e-4',
           'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
           'exec timeout --signal=TERM --kill-after=5s '+str(limit)+'s bash '+shlex.quote(str(snapshot/'pipeline.sh'))]
    (snapshot/'launch.sh').write_text('\n'.join(lines)+'\n')
    manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'phase':args.phase,'maximum_active_seconds':limit+5,'aggregate_case_ceiling_seconds':270,'prior_case_seconds':prior_seconds,'explicit_correction_from':str(args.corrected_from) if args.corrected_from else None,'recording_only_source_bridge':source_bridge,'queue':'default','predecessor':str(previous) if previous else None,'upstream_commit':'13f37dad1980bcbc4491b7f27d8962602e49fea0','predecessor_audit_sha256':sha(previous/'audit/evaluation.json') if previous else None,'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-control-alignment-'+args.phase.lower(),shlex.join(['bash',str(snapshot/'launch.sh')])],capture_output=True,text=True,check=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

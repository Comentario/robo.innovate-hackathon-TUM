"""One immutable saved-data comparison; no simulation or policy installation."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--manifest-repair', action='store_true')
    args = parser.parse_args()
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Independent source review required')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE)], cwd=ROOT):
        raise RuntimeError('Commit reviewed comparison before snapshot')
    previous = [p for p in (ROOT/'runs').glob('*-stage2-contact-screen-comparison') if (p/'submission.txt').exists()]
    if not args.manifest_repair or len(previous) != 1 or protocol['maximum_jobs'] != 2:
        raise RuntimeError('Original comparison closed; only one explicit reviewed manifest repair remains')
    repair = protocol['manifest_repair']
    evidence = repair['original_result']
    if sha(evidence['path']) != evidence['sha256']:
        raise RuntimeError('Original failed comparison changed')
    failure = json.loads(Path(evidence['path']).read_text())
    if failure.get('evaluation_complete') is not False or not failure.get('error', '').startswith('Unpinned contact array:'):
        raise RuntimeError('Repair is only for the pinned input-dependency failure')
    for relative, digest in repair['candidate_and_evaluator_unchanged'].items():
        if sha(HERE/relative) != digest:
            raise RuntimeError('Candidate/scorer must remain unchanged during manifest repair')
    clock = protocol['prior_supervisor']
    if sha(clock['path']) != clock['sha256'] or json.loads(Path(clock['path']).read_text())['cumulative_case_seconds'] != protocol['prior_case_seconds']:
        raise RuntimeError('Retain the authoritative prior clock')
    if protocol['prior_case_seconds']+15 > protocol['aggregate_case_ceiling_seconds']:
        raise RuntimeError('Insufficient retained aggregate budget')
    source = Path(protocol['source_snapshot'])
    base = json.loads((source/'manifest.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-contact-screen-comparison')
    snapshot.mkdir()
    for relative, digest in base['sha256'].items():
        if relative == 'launch.sh':
            continue
        origin = source/relative
        if sha(origin) != digest:
            raise RuntimeError('Immutable source changed: '+relative)
        destination = snapshot/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    code = snapshot/'experiments'/HERE.name
    shutil.copytree(HERE, code, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'results.json'))
    command = [PYTHON, str(code/'run.py')]
    launch = ['#!/usr/bin/env bash', 'set -eo pipefail', 'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=2s 12s '+shlex.join(command), '']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'protocol_sha256': sha(code/'protocol.json'), 'source_snapshot': str(source),
        'maximum_active_seconds': 15, 'maximum_jobs': 1, 'physics_steps': 0,
        'phase': 'one_manifest_dependency_repair', 'original_failed_job': 1816,
        'maximum_original_plus_repair_jobs': 2, 'additional_retry': False,
        'prior_case_seconds': protocol['prior_case_seconds'], 'case_limit_seconds': 1800,
        'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    }, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-saved-contact-screen-comparison',
        shlex.join(['bash', str(snapshot/'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

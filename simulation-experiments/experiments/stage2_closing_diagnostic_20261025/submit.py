"""One frozen closing-only physical diagnostic, in the default Pueue queue."""
from datetime import datetime, timezone
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
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Final independent source review required')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE)], cwd=ROOT):
        raise RuntimeError('Commit reviewed diagnostic before snapshotting')
    for previous in (ROOT/'runs').glob('*-stage2-closing-diagnostic'):
        if (previous/'submission.txt').exists():
            raise RuntimeError('One additional closing diagnostic only; no retry')
    evidence = [protocol[k] for k in ('prior_supervisor', 'source_metadata', 'original_selection', 'original_binding')]
    evidence.append(protocol['observer_validation']['audit'])
    for record in evidence:
        if sha(record['path']) != record['sha256']:
            raise RuntimeError('Pinned evidence changed: '+record['path'])
    prior = json.loads(Path(protocol['prior_supervisor']['path']).read_text())['cumulative_case_seconds']
    if prior != protocol['prior_case_seconds'] or prior+protocol['maximum_active_seconds'] > 1800:
        raise RuntimeError('Preserve full prior costs and aggregate ceiling')
    validated = json.loads(Path(protocol['observer_validation']['audit']['path']).read_text())
    if validated.get('observation_contract_passed') is not True:
        raise RuntimeError('Actual report-mechanism validation required')
    source = Path(protocol['source_snapshot'])
    base = json.loads((source/'manifest.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-closing-diagnostic')
    snapshot.mkdir()
    for relative, digest in base['sha256'].items():
        if relative == 'launch.sh':
            continue
        origin = source/relative
        if sha(origin) != digest:
            raise RuntimeError('Immutable 1809 source changed: '+relative)
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    code = snapshot/'experiments'/HERE.name
    shutil.copytree(HERE, code, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'results.json'))
    if sha(code/'science.json') != protocol['science_sha256']:
        raise RuntimeError('Original physical science changed')
    # Reuse the accepted callback and pure independent mapping helpers verbatim.
    validated = Path(protocol['observer_validation']['source_snapshot'])
    target = snapshot/'experiments/stage2_collider_probe_20261025'
    target.mkdir(exist_ok=True)
    for name, key in [('native_observer.py', 'native_observer_sha256'),
                      ('evaluate.py', 'mapping_helpers_sha256'), ('protocol.json', 'protocol_sha256')]:
        origin = validated/'experiments/stage2_collider_probe_20261025'/name
        if sha(origin) != protocol['observer_validation'][key]:
            raise RuntimeError('Frozen reporting implementation changed')
        shutil.copy2(origin, target/name)
    shutil.copy2(protocol['prior_supervisor']['path'], code/'prior_supervisor.json')
    command = [PYTHON, str(code/'pipeline.py')]
    launch = ['#!/usr/bin/env bash', 'set -eo pipefail',
        'source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env', 'set -u',
        'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=5s 230s '+shlex.join(command), '']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_snapshot': str(source), 'protocol_sha256': sha(code/'protocol.json'),
        'science_sha256': sha(code/'science.json'), 'maximum_active_seconds': 240,
        'maximum_jobs': 1, 'physical_closing_executions': 1, 'lift_or_extraction_authorized': False,
        'prior_case_seconds': prior, 'case_limit_seconds': 1800,
        'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    }, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-private-closing-diagnostic',
        shlex.join(['bash', str(snapshot/'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

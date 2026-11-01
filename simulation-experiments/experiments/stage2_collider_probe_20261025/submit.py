"""One immutable default-queue observation probe; no automatic retries."""
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
    parser.add_argument('--instrumentation-repair', action='store_true')
    args = parser.parse_args()
    protocol = json.loads((HERE/'protocol.json').read_text())
    if protocol['execution_authorized'] is not True:
        raise RuntimeError('Independent source review required before submission')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE)], cwd=ROOT):
        raise RuntimeError('Commit the reviewed probe before snapshotting')
    previous = [p for p in (ROOT/'runs').glob('*-stage2-collider-probe') if (p/'submission.txt').exists()]
    history = protocol['capture_attempt_history']
    if not args.instrumentation_repair or len(previous) != 1 or protocol['maximum_jobs'] != 2:
        raise RuntimeError('Original phase closed. Only one explicitly reviewed instrumentation repair is available, with no further retry')
    evidence = history['saved_audit']
    if sha(evidence['path']) != evidence['sha256']:
        raise RuntimeError('Saved original failure audit changed')
    failure = json.loads(Path(evidence['path']).read_text())
    if (failure.get('status') != 'UNKNOWN' or failure.get('steps') != 1
            or failure.get('observation_contract_passed') is not False
            or set(failure.get('roles', {})) != {'BODY', 'WHITE', 'HEAD'}
            or any(v['loaded_frames'] != 0 for v in failure['roles'].values())):
        raise RuntimeError('Correction is bound to the fixed pre-contact instrumentation failure only')
    clock_path = Path(protocol['prior_supervisor'])
    if sha(clock_path) != protocol['prior_supervisor_sha256']:
        raise RuntimeError('Authoritative prior clock changed')
    for evidence in protocol['source_api_evidence']:
        if sha(evidence['path']) != evidence['sha256']:
            raise RuntimeError('Reviewed installed API/native source changed')
    evidence = protocol['source_metadata']
    if sha(evidence['path']) != evidence['sha256']:
        raise RuntimeError('Prior physical settings evidence changed')
    clock = json.loads(clock_path.read_text())
    prior = float(clock['cumulative_case_seconds'])
    if prior != protocol['prior_case_seconds'] or prior+protocol['maximum_active_seconds'] > protocol['aggregate_case_ceiling_seconds']:
        raise RuntimeError('Prior contact costs and remaining aggregate budget must be preserved')
    source = Path(protocol['source_snapshot'])
    base = json.loads((source/'manifest.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-collider-probe')
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
    shutil.copy2(clock_path, code/'prior_supervisor.json')
    command = [PYTHON, str(code/'pipeline.py')]
    launch = [
        '#!/usr/bin/env bash', 'set -eo pipefail',
        'source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env', 'set -u',
        'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=5s 235s '+shlex.join(command), ''
    ]
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'immutable_source_snapshot': str(source), 'protocol_sha256': sha(code/'protocol.json'),
        'maximum_active_seconds': protocol['maximum_active_seconds'], 'maximum_jobs': 1,
        'phase': 'one_instrumentation_corrected_capture',
        'previous_capture_jobs': [1812], 'saved_failure_audit_job': 1813,
        'maximum_original_plus_corrected_captures': 2, 'additional_retry': False,
        'prior_case_seconds': prior, 'aggregate_case_ceiling_seconds': 1800,
        'prior_supervisor_sha256': sha(clock_path),
        'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    }, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-native-collider-observer',
                             shlex.join(['bash', str(snapshot/'launch.sh')])],
                            check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

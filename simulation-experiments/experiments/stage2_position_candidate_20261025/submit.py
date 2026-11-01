"""One explicitly reviewed position-candidate improvement after the failed baseline."""
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
        raise RuntimeError('Final independent source and control-bridge review required')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE)], cwd=ROOT):
        raise RuntimeError('Commit reviewed baseline before snapshot')
    for previous in (ROOT/'runs').glob('*-stage2-position-candidate-I-r1'):
        if (previous/'submission.txt').exists():
            raise RuntimeError('One explicit round1 only; no automatic retry or H')
    pins = [protocol['prior_supervisor'], protocol['source_metadata']]
    for name in ('control_evidence', 'diagnostic_evidence', 'screen_evidence', 'baseline_failure_evidence'):
        pins += [v for v in protocol[name].values() if isinstance(v, dict) and 'path' in v and 'sha256' in v]
    for evidence in pins:
        if sha(evidence['path']) != evidence['sha256']:
            raise RuntimeError('Pinned evidence changed: '+evidence['path'])
    prior = json.loads(Path(protocol['prior_supervisor']['path']).read_text())['cumulative_case_seconds']
    if (prior != protocol['prior_case_seconds'] or protocol['aggregate_case_ceiling_seconds'] != 2200
            or prior+protocol['maximum_active_seconds'] > protocol['aggregate_case_ceiling_seconds']):
        raise RuntimeError('Retain all old costs under the prospectively reviewed aggregate')
    failure = json.loads(Path(protocol['baseline_failure_evidence']['audit']['path']).read_text())
    if (protocol.get('improvement_round') != 1 or protocol.get('maximum_authorized_improvement_rounds') != 1
            or failure.get('physics_extraction_passed') is not False
            or failure.get('frame_failure_counts') or failure.get('private_native_failures')
            or failure.get('endpoint_settle_completed_commands') != 30
            or failure.get('checks', {}).get('positive_force_trigger') is not False):
        raise RuntimeError('Round1 is bound to the accepted endpoint-without-force-confirmation baseline only')
    source = Path(protocol['source_snapshot'])
    base = json.loads((source/'manifest.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-position-candidate-I-r1')
    snapshot.mkdir()
    for relative, digest in base['sha256'].items():
        if relative == 'launch.sh':
            continue
        origin = source/relative
        if sha(origin) != digest:
            raise RuntimeError('Immutable parent source changed: '+relative)
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    code = snapshot/'experiments'/HERE.name
    shutil.copytree(HERE, code, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'results.json'))
    if sha(code/'source_science.json') != protocol['source_science_sha256']:
        raise RuntimeError('Original numerical science changed')
    screen = protocol['screen_evidence']
    origin = Path(screen['source_snapshot'])/'experiments/stage2_contact_screen_20261025/screen.py'
    if sha(origin) != screen['screen_sha256']:
        raise RuntimeError('Frozen pure screen changed')
    target = snapshot/'experiments/stage2_contact_screen_20261025'
    target.mkdir(exist_ok=True)
    shutil.copy2(origin, target/'screen.py')
    # Parent1815 already contains the exact callback/mapper. Verify each, never
    # replace it with mutable worktree code.
    for name, key in [('native_observer.py', 'observer_sha256'), ('evaluate.py', 'mapper_sha256'), ('protocol.json', 'mapper_protocol_sha256')]:
        path = snapshot/'experiments/stage2_collider_probe_20261025'/name
        if sha(path) != protocol['native_mapping_evidence'][key]:
            raise RuntimeError('Frozen native reporting helper changed')
    shutil.copy2(protocol['prior_supervisor']['path'], code/'prior_supervisor.json')
    launch = ['#!/usr/bin/env bash', 'set -eo pipefail',
        'source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env', 'set -u',
        'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 OSQP_EPSILON=1e-4 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=5s 340s '+shlex.join([PYTHON, str(code/'pipeline.py')]), '']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_snapshot': str(source), 'protocol_sha256': sha(code/'protocol.json'),
        'source_science_sha256': sha(code/'source_science.json'), 'maximum_active_seconds': 350,
        'prior_case_seconds': prior, 'case_limit_seconds': 2200, 'previous_case_limit_seconds': 2200,
        'maximum_jobs': 1, 'case': 'I', 'improvement_round': 1, 'maximum_authorized_improvement_rounds': 1,
        'H_authorized': False, 'automatic_retry': False,
        'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    }, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-position-candidate-I-round1',
        shlex.join(['bash', str(snapshot/'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

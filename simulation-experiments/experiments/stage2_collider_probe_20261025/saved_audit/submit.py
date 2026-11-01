"""One frozen audit-only replay of the failed sensing probe."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    protocol = json.loads((HERE/'protocol.json').read_text())
    if not protocol['execution_authorized']:
        raise RuntimeError('Saved-audit launcher review required')
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE.parent)], cwd=ROOT):
        raise RuntimeError('Commit reviewed repair and launcher first')
    for old in (ROOT/'runs').glob('*-stage2-collider-saved-audit'):
        if (old/'submission.txt').exists():
            raise RuntimeError('One saved audit only; no automatic retry')
    if protocol['prior_case_seconds']+10 > protocol['aggregate_ceiling_seconds']:
        raise RuntimeError('Insufficient retained aggregate budget')
    source = Path(protocol['source_snapshot'])
    base = json.loads((source/'manifest.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-stage2-collider-saved-audit')
    snapshot.mkdir()
    for relative, digest in base['sha256'].items():
        if relative == 'launch.sh':
            continue
        origin = source/relative
        if sha(origin) != digest:
            raise RuntimeError('Original source changed: '+relative)
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    # Keep original physical capture protocol and inputs. Only evaluator JSON
    # serialization is repaired; runtime is never invoked by this launcher.
    code = snapshot/'experiments/stage2_collider_probe_20261025'
    shutil.copy2(HERE.parent/'evaluate.py', code/'evaluate.py')
    shutil.copytree(HERE, code/'saved_audit', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    command = [PYTHON, str(code/'saved_audit/run.py')]
    launch = ['#!/usr/bin/env bash', 'set -eo pipefail', 'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
        'exec timeout --signal=TERM --kill-after=2s 8s '+shlex.join(command), '']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'maximum_active_seconds': 10, 'maximum_jobs': 1, 'physics_steps': 0,
        'immutable_capture': str(source), 'prior_case_seconds': protocol['prior_case_seconds'],
        'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    }, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-collider-saved-failure-audit',
        shlex.join(['bash', str(snapshot/'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

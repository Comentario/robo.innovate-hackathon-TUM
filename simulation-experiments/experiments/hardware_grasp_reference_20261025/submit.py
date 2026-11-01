"""Freeze reference inputs and queue one data-only comparison in default Pueue."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(HERE)], cwd=ROOT):
        raise RuntimeError('Commit reviewed reference source before snapshotting')
    protocol = json.loads((HERE / 'protocol.json').read_text())
    snapshot = ROOT / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-hardware-grasp-reference')
    snapshot.mkdir()
    shutil.copytree(HERE, snapshot / 'code', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'artifacts', 'results.json'))
    frozen = dict(protocol, files={})
    for name, record in protocol['files'].items():
        source = (ROOT / record['path']).resolve()
        if sha(source) != record['sha256']:
            raise RuntimeError('Pinned input changed: ' + name)
        target = snapshot / 'inputs' / (name + source.suffix)
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        frozen['files'][name] = dict(record, path=str(target.relative_to(snapshot)))
    (snapshot / 'protocol.json').write_text(json.dumps(frozen, indent=2) + '\n')
    command = [protocol['runtime_python'], str(snapshot / 'code/extract_and_check.py'), '--inputs', str(snapshot / 'protocol.json'), '--output', str(snapshot / 'output')]
    (snapshot / 'launch.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd ' + shlex.quote(str(snapshot)) + '\nexport ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1\nexec timeout --signal=TERM --kill-after=2s 10s ' + shlex.join(command) + '\n')
    manifest = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'maximum_active_seconds': 12, 'physics_steps': 0, 'hardware_control': False, 'queue': 'default', 'sha256': {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-hardware-grasp-reference', shlex.join(['bash', str(snapshot / 'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot / 'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

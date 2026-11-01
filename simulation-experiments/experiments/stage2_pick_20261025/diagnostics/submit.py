"""Freeze and queue the one reviewed first-candidate30s CPU diagnostic."""
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
    stage = HERE.parent.relative_to(ROOT)
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(stage)], cwd=ROOT):
        raise RuntimeError('Commit reviewed diagnostic source before freezing')
    original = ROOT/'runs/20261025T100014.190794Z-stage2-pick-I-pick'
    prior = json.loads((original/'pipeline_supervisor.json').read_text())
    if prior['case'] != 'I' or prior['mode'] != 'pick' or prior['proceed_gate_passed'] is not False:
        raise RuntimeError('Only the original abstained I-pick is this diagnostic input')
    scope = json.loads((HERE/'clearance_protocol.json').read_text())
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
                           +'-stage2-pick-clearance-diagnostic-r2')
    code = snapshot/stage
    code.mkdir(parents=True)
    # This CPU diagnostic imports only its own frozen pure helpers; it needs
    # no Kit, BrickSim asset tree, model checkpoint or simulated scene.
    for name in ('diagnostics', 'evaluation'):
        shutil.copytree(HERE.parent/name, code/name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(HERE.parent/'protocol.json', code/'protocol.json')
    inputs = snapshot/'inputs'
    data = inputs/'capture_1802'
    data.mkdir(parents=True)
    for name, digest in scope['input_sha256'].items():
        source = original/'output'/name
        if sha(source) != digest:
            raise RuntimeError('Frozen input differs: '+name)
        target = data/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(original/'pipeline_supervisor.json', inputs/'prior_pipeline_supervisor.json')
    command = [PYTHON, str(code/'diagnostics/run.py'), '--input', str(data),
               '--output', str(snapshot/'output'),
               '--prior-supervisor', str(inputs/'prior_pipeline_supervisor.json')]
    lines = ['#!/usr/bin/env bash', 'set -eo pipefail',
             'source /home/faps/miniforge3/etc/profile.d/conda.sh',
             'conda activate /home/faps/miniforge3/envs/unitree_sim_env', 'set -u',
             'cd '+shlex.quote(str(snapshot)),
             'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
             shlex.join(['timeout', '--signal=TERM', '--kill-after=2s', '28s', *command]), '']
    (snapshot/'launch.sh').write_text('\n'.join(lines))
    manifest = {'scope': scope['scope'], 'source_commit': subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'case': 'I', 'mode': 'diagnostic', 'maximum_attempts': 1,
                'new_physics_steps': 0, 'maximum_active_seconds': 30,
                'prior_case_wall_seconds': prior['cumulative_case_seconds'],
                'case_limit_seconds': 1200,
                'sha256': {str(p.relative_to(snapshot)): sha(p)
                           for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    submitted = subprocess.run(['pueue', 'add', '--label', 'robo26-native-pick-clearance-diagnostic-r2',
                                shlex.join(['bash', str(snapshot/'launch.sh')])],
                               check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(submitted.stdout)
    print(snapshot)
    print(submitted.stdout.strip())


if __name__ == '__main__':
    main()

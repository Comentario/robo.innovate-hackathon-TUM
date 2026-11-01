"""Freeze the editable workcell and queue a fresh preview without overwrites."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[1]
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cameras', type=Path, default=EXP/'cameras.json')
    parser.add_argument('--appearance', type=Path, help='Optional visual-only material preset')
    args = parser.parse_args()
    camera_relative = args.cameras.resolve().relative_to(EXP)
    if subprocess.check_output(['git', 'status', '--porcelain', '--', str(EXP.relative_to(ROOT))], cwd=ROOT):
        raise SystemExit('Commit scoped code/configuration before freezing a queued preview')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot = ROOT/'runs'/f'{stamp}-final-workcell-preview'
    snapshot.mkdir(parents=True)
    for name in ('.deps', 'challenge2', 'configs'):
        shutil.copytree(ROOT/name, snapshot/name, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(EXP, snapshot/'experiments'/EXP.name, ignore=shutil.ignore_patterns('__pycache__'))
    supervisor = snapshot/'experiments/partial_disassembly_20261024'
    supervisor.mkdir(parents=True)
    shutil.copy2(ROOT/'experiments/partial_disassembly_20261024/render_supervisor.py', supervisor/'render_supervisor.py')
    evidence = snapshot/'photo_evidence'
    evidence.mkdir()
    for number in (8, 9):
        shutil.copy2(ROOT/f'resources/setup_images/final_workcell_20261024/photo_{number:02d}.jpg',
                     evidence/f'photo_{number:02d}.jpg')
    command = [PYTHON, str(snapshot/'experiments'/EXP.name/'capture_supervisor.py'),
               '--python', PYTHON, '--output', str(snapshot/'output'),
               '--cameras', str(snapshot/'experiments'/EXP.name/camera_relative)]
    if args.appearance is not None:
        appearance_relative = args.appearance.resolve().relative_to(EXP)
        command += ['--appearance', str(snapshot/'experiments'/EXP.name/appearance_relative)]
    board = json.loads((snapshot/'experiments'/EXP.name/'scene_config.json').read_text())['final_layout']['marker_board']
    center = list(board['center_table_m'])
    center[2] += .00025
    uv_check = [PYTHON, str(snapshot/'experiments'/EXP.name/'verify_charuco_render.py'),
                '--asset-audit', str(snapshot/'experiments'/EXP.name/board['provenance_file']),
                '--cameras', str(snapshot/'output/evaluation_truth/cameras.json'),
                '--images', str(snapshot/'output/images'), '--center', *map(str, center),
                '--yaw-deg', str(board['pattern_rotation_table_deg']),
                '--output', str(snapshot/'output/charuco_uv_check.json')]
    lines = ['#!/usr/bin/env bash', 'set -eo pipefail',
             'source /home/faps/miniforge3/etc/profile.d/conda.sh',
             'conda activate /home/faps/miniforge3/envs/unitree_sim_env', 'set -u',
             'cd '+shlex.quote(str(snapshot)),
             'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot)),
             'export ROBO_PUEUE_JOB=1', 'export PYTHONDONTWRITEBYTECODE=1',
             'export OMP_NUM_THREADS=2', 'export OPENBLAS_NUM_THREADS=2',
             shlex.join(command), 'test -f output/supervisor.json', shlex.join(uv_check), '']
    (snapshot/'launch.sh').write_text('\n'.join(lines))
    manifest = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'scope': 'static approximate final workcell; no control', 'runtime_python': PYTHON,
                'camera_configuration': str(camera_relative),
                'sha256': {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-final-workcell-preview',
                             shlex.join(['bash', str(snapshot/'launch.sh')])], check=True, capture_output=True, text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print('Snapshot:', snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

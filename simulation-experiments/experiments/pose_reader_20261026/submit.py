"""Explicit finite startup diagnostics on the default queue; no retry loop."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PYTHON = '/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--stage', choices=['capture', 'audit', 'confirm'], required=True)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    protocol = json.loads((HERE/'protocol.json').read_text())
    for path, digest in protocol['installed_cache_implementation_sha256'].items():
        if sha(Path(path)) != digest:
            raise RuntimeError('Installed cache implementation changed: '+path)
    paths = [HERE, ROOT/'experiments/control_alignment_20261026/batched_source.py',
        ROOT/'tests/test_batched_source.py', ROOT/'experiments/control_alignment_20261026/evaluate.py',
        ROOT/'tests/test_control_alignment_audit.py']
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *map(str, paths)], cwd=ROOT):
        raise RuntimeError('Commit reviewed diagnostic source first')
    base = ROOT/protocol['initializer_source_snapshot']
    historical = json.loads((base/'manifest.json').read_text())
    if historical['source_commit'] != 'b07f930ed22d18350fe97d513ca75bb8e3c596bf':
        raise RuntimeError('Wrong failed-workcell initializer')
    existing = [p for p in (ROOT/'runs').glob('*-pose-reader-*') if (p/'submission.txt').exists()]
    if any(p.name.endswith('-'+args.stage) for p in existing):
        raise RuntimeError('Only one explicit job per stage; no automatic retries')
    tasks = json.loads(subprocess.check_output(['pueue', 'status', '--json'], text=True))['tasks']
    spent = 0.
    for p in existing:
        task = tasks[str(json.loads((p/'job.json').read_text())['job_id'])]
        done = task['status'].get('Done')
        if not done:
            raise RuntimeError('Previous reader case job must finish first')
        # Pueue retains nanoseconds; datetime truncates sub-microsecond residue.
        spent += (datetime.fromisoformat(done['end'])-datetime.fromisoformat(done['start'])).total_seconds()
    limit = protocol['stage_maximum_seconds'][args.stage]
    if spent+limit > protocol['new_case_ceiling_seconds']:
        raise RuntimeError('Insufficient bounded reader-case budget')
    if args.stage != 'capture':
        if args.capture is None or not (args.capture/'output/capture_complete.json').exists():
            raise RuntimeError('A complete startup capture is required')
    if args.stage == 'confirm':
        if args.audit is None:
            raise RuntimeError('Independent audit required before confirmation')
        report = json.loads((args.audit/'audit/evaluation.json').read_text())
        if not report['diagnostic_complete'] or report['reader_status'] != 'CACHE_ONLY_DISCREPANCY':
            raise RuntimeError('No evidence-supported cache-only correction admission')
        if report['capture_sha256'] != sha(args.capture/'output/capture.json'):
            raise RuntimeError('Audit belongs to another capture')
    snapshot = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-pose-reader-'+args.stage)
    snapshot.mkdir()
    # Reuse the exact historical scene/controller runtime, not a fresh rollout.
    for name in ('challenge2', 'configs', 'vendor', 'experiments', 'tests', '.deps'):
        shutil.copytree(base/name, snapshot/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative, digest in historical['sha256'].items():
        copied = snapshot/relative
        if copied.exists() and sha(copied) != digest:
            raise RuntimeError('Historical source changed: '+relative)
    shutil.copytree(HERE, snapshot/HERE.relative_to(ROOT), dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative in ('experiments/control_alignment_20261026/batched_source.py', 'tests/test_batched_source.py',
            'experiments/control_alignment_20261026/evaluate.py', 'tests/test_control_alignment_audit.py'):
        shutil.copyfile(ROOT/relative, snapshot/relative)
    code = snapshot/HERE.relative_to(ROOT)
    output = snapshot/'output'
    if args.stage == 'audit':
        commands = [[PYTHON, str(code/'evaluate.py'), '--input', str(args.capture.resolve()/'output/capture.json'),
            '--output', str(snapshot/'audit')]]
    else:
        command = [PYTHON, str(code/'run.py'), '--output', str(output), '--headless', '--enable_cameras']
        if args.stage == 'confirm':
            command += ['--verify-reader']
        commands = [command]
    source = {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}
    write(snapshot/'manifest.json', {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'initializer_source_snapshot': protocol['initializer_source_snapshot'],
        'base_snapshot_manifest_sha256': sha(base/'manifest.json'), 'source_sha256': source,
        'stage': args.stage, 'prior_case_seconds': spent, 'maximum_seconds': limit, 'queue': 'default',
        'protocol_sha256': sha(HERE/'protocol.json')})
    script = ['#!/usr/bin/env bash', 'set -eo pipefail',
        'source /home/faps/miniforge3/etc/profile.d/conda.sh',
        'conda activate /home/faps/miniforge3/envs/unitree_sim_env',
        'set -u',
        'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1',
        'export PYTHONPATH='+shlex.quote(str(snapshot/'.deps')+':'+str(snapshot))]
    (snapshot/'pipeline.sh').write_text('\n'.join(script+list(map(shlex.join, commands)))+'\n')
    seconds = {'capture': 80, 'audit': 10, 'confirm': 65}[args.stage]
    launch = ['timeout', '--signal=TERM', '--kill-after=5s', str(seconds)+'s', 'bash', str(snapshot/'pipeline.sh')]
    (snapshot/'launch.sh').write_text('#!/usr/bin/env bash\nexec '+shlex.join(launch)+'\n')
    result = subprocess.run(['pueue', 'add', '--label', 'robo26-pose-reader-'+args.stage,
        shlex.join(['bash', str(snapshot/'launch.sh')])], capture_output=True, text=True, check=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    import re
    job = int(re.search(r'id (\d+)', result.stdout).group(1))
    write(snapshot/'job.json', {'job_id': job, 'stage': args.stage})
    print(snapshot)
    print(result.stdout.strip())


if __name__ == '__main__':
    main()

"""Freeze one source-color handoff replay and submit to default Pueue."""
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
    plan = json.loads((HERE/'protocol.json').read_text())
    if not plan['execution_authorized']:
        raise RuntimeError('Final independent source review required')
    tracked = [str(HERE), 'experiments/stage2_pick_20261025/sensors.py',
               'experiments/stage2_position_candidate_20261025/run_pick.py']
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *tracked], cwd=ROOT):
        raise RuntimeError('Commit reviewed source and integration first')
    if any((p/'submission.txt').exists() for p in (ROOT/'runs').glob('*-stage1-handoff')):
        raise RuntimeError('One replay only; no automatic retry')
    for relative, digest in {**plan['frozen_inputs_sha256'], **plan['frozen_runtime_sources_sha256']}.items():
        if sha(ROOT/relative) != digest:
            raise RuntimeError('Frozen input changed: '+relative)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    snapshot = ROOT/'runs'/(stamp+'-stage1-handoff')
    snapshot.mkdir()
    shutil.copytree(HERE, snapshot/'code', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'results.json'))
    prior = Path(plan['source_color_snapshot'])
    public = snapshot/'public'
    public.mkdir()
    shutil.copy2(prior/'public/calibration.json', public/'calibration.json')
    shutil.copy2(prior/'public/frames.json', public/'frames.json')
    for frame in plan['frame_ids']:
        shutil.copytree(prior/'public'/frame, public/frame)
    for name, source in [('prototypes.json', prior/'predictions/prototypes.json'),
                         ('settings.json', prior/'code/settings.json'),
                         ('color.py', prior/'code/color.py')]:
        shutil.copy2(source, public/name)
    classifier_package = snapshot/'experiments/stage1_color_20261025'
    classifier_package.mkdir(parents=True)
    shutil.copy2(prior/'code/color.py', classifier_package/'color.py')
    stage2 = Path(plan['selected_pick_snapshot'])/'output'
    selection = json.loads((stage2/'online/selection.json').read_text())
    camera = next(v for v in selection['geometry_views'] if v['frame_id']==selection['frame_id'])
    selected = public/'selected_stage2'
    selected.mkdir()
    for key in ('rgb', 'depth'):
        shutil.copy2(stage2/selection[key], selected/Path(selection[key]).name)
    reduced = {key:selection[key] for key in ('frame_id', 'measurement_time_s', 'candidate')}
    reduced['calibration'] = {key:camera['calibration'][key] for key in ('K', 'R', 't')}
    reduced['original_selection_sha256'] = sha(stage2/'online/selection.json')
    (selected/'selection.json').write_text(json.dumps(reduced, indent=2)+'\n')
    shutil.copy2(stage2/'position_pick_complete.json', selected/'capture_complete.json')
    baselines = snapshot/'baselines'
    baselines.mkdir()
    for frame in plan['frame_ids']:
        shutil.copy2(prior/'predictions'/(frame+'.json'), baselines/(frame+'.json'))
    (snapshot/'integration_sources').mkdir()
    for rel in tracked[1:]:
        shutil.copy2(ROOT/rel, snapshot/'integration_sources'/Path(rel).name)
    commands = [
        [PYTHON, str(snapshot/'code/replay.py'), '--inputs', str(public), '--output', str(snapshot/'output')],
        [PYTHON, str(snapshot/'code/evaluate.py'), '--inputs', str(public), '--baselines', str(baselines),
         '--predictions', str(snapshot/'output'), '--output', str(snapshot/'audit')],
    ]
    pipeline = ['#!/usr/bin/env bash', 'set -eo pipefail', 'cd '+shlex.quote(str(snapshot)),
        'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2',
        'export PYTHONPATH='+shlex.quote(str(snapshot))]
    pipeline += [shlex.join(command) for command in commands]
    (snapshot/'pipeline.sh').write_text('\n'.join(pipeline)+'\n')
    launch = '#!/usr/bin/env bash\nset -eo pipefail\nexec timeout --signal=TERM --kill-after=3s 27s bash '+shlex.quote(str(snapshot/'pipeline.sh'))+'\n'
    (snapshot/'launch.sh').write_text(launch)
    manifest = {'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'runtime_python':PYTHON, 'maximum_active_seconds':30, 'maximum_jobs':1,
        'scope':'Saved observation handoff only; no physics or manipulation',
        'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result = subprocess.run(['pueue','add','--label','robo26-pregrasp-color-handoff',
                             shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout)
    print(snapshot)
    print(result.stdout.strip())


if __name__=='__main__':
    main()

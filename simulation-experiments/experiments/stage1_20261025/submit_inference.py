"""Freeze sensor-only Stage1 inference and independent offline scoring."""
import argparse
from datetime import datetime, timezone
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--render-snapshot',type=Path,required=True)
    p.add_argument('--intact',type=Path,help='Explicit I_mix capture; required with custom camera/benchmark/protocol options')
    p.add_argument('--split',choices=('development','reserved'),required=True)
    p.add_argument('--workspace',type=Path,help='Optional frozen sensor working-volume prior')
    p.add_argument('--cameras',type=Path,help='Camera JSON relative to this Stage1 experiment')
    p.add_argument('--benchmark',type=Path,help='Benchmark JSON relative to this Stage1 experiment')
    p.add_argument('--protocol',type=Path,help='Evaluation protocol JSON relative to this Stage1 experiment')
    a = p.parse_args()
    custom = any(value is not None for value in (a.cameras,a.benchmark,a.protocol))
    if a.intact is None:
        if custom:
            p.error('Custom configurations require --intact pointing to the matching newly captured I_mix directory')
        a.intact = ROOT/'runs/20261025T000918.719244Z-final-workcell-preview/output'
    cameras = (EXP/a.cameras).resolve() if a.cameras else ROOT/'experiments/final_workcell_20261024/cameras_realism.json'
    benchmark = (EXP/a.benchmark).resolve() if a.benchmark else EXP/'benchmark.json'
    protocol_path = (EXP/a.protocol).resolve() if a.protocol else EXP/'evaluation/protocol.json'
    camera_relative, benchmark_relative, protocol_relative = (path.relative_to(ROOT) for path in (cameras,benchmark,protocol_path))
    protocol = json.loads(protocol_path.read_text())
    spec = json.loads(benchmark.read_text())
    if hashlib.sha256(benchmark.read_bytes()).hexdigest() != protocol['benchmark_sha256']:
        p.error('Selected benchmark does not match its frozen protocol pin')
    if spec['frozen_sources_sha256'].get(str(camera_relative)) != hashlib.sha256(cameras.read_bytes()).hexdigest():
        p.error('Selected camera configuration does not match its frozen benchmark pin')
    scope = ['experiments/stage1_20261025','experiments/final_workcell_20261024',
             'experiments/sim_pose_20261024/calibration.py','experiments/sim_views_20261024/render_views.py','challenge2']
    if subprocess.check_output(['git','status','--porcelain','--',*scope],cwd=ROOT):
        raise SystemExit('Commit scoped code/configuration before freezing')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    version = '-'+a.workspace.stem if a.workspace else ''
    snap = ROOT/'runs'/(stamp+'-stage1-'+a.split+version)
    snap.mkdir()
    for name in ('stage1_20261025','final_workcell_20261024','sim_pose_20261024','sim_views_20261024'):
        shutil.copytree(ROOT/'experiments'/name,snap/'experiments'/name,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc','results','results_300'))
    shutil.copytree(ROOT/'challenge2',snap/'challenge2',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    private = snap/'private';private.mkdir();truth = private/'truth';truth.mkdir()
    cases = protocol[a.split+'_cases']
    locations = {case:(a.intact.resolve() if case == 'I_mix' else
                       a.render_snapshot.resolve()/'render_output'/a.split/case) for case in cases}
    for case,path in locations.items():
        (truth/case).symlink_to(path,target_is_directory=True)
    rows, frames = [], []
    def add(case,view,control=None):
        identity = f'f{len(rows):03d}'
        source = locations[case]
        row = {'id':identity,'camera':'camera_0' if view == 'diagnostic_table_top' else 'camera_1',
               'rgb_source':str(source/'images'/(view+'.png')),
               'depth_source':str(source/'evaluation_truth'/(view+'_depth.npy'))}
        frame = {'id':identity,'case_id':case,'view':view,'control_id':control['id'] if control else None}
        if control:
            row['operation'] = control['operation']
            if 'pixel_xyxy' in control:row['pixel_xyxy'] = control['pixel_xyxy']
            frame['depth_input_path'] = str(snap/'sensors/sensors'/identity/'depth.npy')
        rows.append(row);frames.append(frame)
    for case in cases:
        for view in protocol['views']:add(case,view)
    if a.split == 'development':
        for control in protocol['controls']:add(control['case_id'],control['view'],control)
    (private/'sources.json').write_text(json.dumps(rows,indent=2)+'\n')
    (private/'frames.json').write_text(json.dumps(frames,indent=2)+'\n')
    code = snap/'experiments/stage1_20261025'; final = snap/'experiments/final_workcell_20261024'
    commands = [
        [PYTHON,str(code/'calibration.py'),'--geometry',str(final/'geometry.json'),'--cameras',str(snap/camera_relative),'--output',str(snap/'calibration.json')],
        [PYTHON,str(code/'prepare_inputs.py'),'--sources',str(private/'sources.json'),'--calibration',str(snap/'calibration.json'),'--output',str(snap/'sensors')],
        [PYTHON,str(code/'online.py'),'--inputs',str(snap/'sensors'),'--output',str(snap/'inference')],
        [PYTHON,str(code/'evaluation/evaluate.py'),'--truth',str(truth),'--predictions',str(snap/'inference'),
         '--frames',str(private/'frames.json'),'--geometry',str(final/'geometry.json'),'--benchmark',str(snap/benchmark_relative),
         '--protocol',str(snap/protocol_relative),'--mock-results',str(snap/'inference/mock_results.json'),
         '--split',a.split,'--output',str(snap/'evaluation')]]
    if a.workspace is not None:
        relative = a.workspace.resolve().relative_to(EXP)
        commands[2] += ['--workspace',str(code/relative)]
    lines = ['#!/usr/bin/env bash','set -eo pipefail','cd '+shlex.quote(str(snap)),
             'export PYTHONPATH='+shlex.quote(str(snap)),
             'export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2']
    lines += [shlex.join(c) for c in commands]
    (snap/'launch.sh').write_text('\n'.join(lines)+'\n')
    files = [f for f in snap.rglob('*') if f.is_file() and not f.is_relative_to(truth)]
    (snap/'manifest.json').write_text(json.dumps({
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'split':a.split,'workspace':str(a.workspace) if a.workspace else None,'render_snapshot':str(a.render_snapshot.resolve()),'intact_capture':str(a.intact.resolve()),
        'cameras':str(camera_relative),'benchmark':str(benchmark_relative),'protocol':str(protocol_relative),
        'truth_separation':'Only sensor package/configuration given to online.py; private frame/truth mapping only given to evaluator',
        'sha256':{str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}},indent=2)+'\n')
    result = subprocess.run(['pueue','add','--label','robo26-stage1-'+a.split,
                             shlex.join(['bash',str(snap/'launch.sh')])],check=True,capture_output=True,text=True)
    (snap/'submission.txt').write_text(result.stdout)
    print('Snapshot:',snap); print(result.stdout.strip())


if __name__ == '__main__':
    main()

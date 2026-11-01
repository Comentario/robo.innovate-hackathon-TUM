"""Freeze one bounded detector version on development or sealed-final reserved sensors."""
import argparse
from datetime import datetime,timezone
import hashlib,json,shlex,shutil,subprocess
from pathlib import Path

EXP=Path(__file__).resolve().parent;ROOT=EXP.parents[1];PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--version',required=True,choices=['B0','R1','R2','R3']);p.add_argument('--split',default='development',choices=['development','reserved']);p.add_argument('--previous-evaluation',type=Path);a=p.parse_args()
    if subprocess.check_output(['git','status','--porcelain','--',str(EXP.relative_to(ROOT))],cwd=ROOT,text=True):raise SystemExit('Commit scoped code/config/dataset/ledger before freezing')
    ledger=json.loads((EXP/'rounds.json').read_text());benchmark=json.loads((EXP/'benchmark.json').read_text());protocol=json.loads((EXP/'evaluation/protocol.json').read_text());dataset=json.loads((EXP/'dataset.json').read_text())
    if sha(EXP/'benchmark.json')!=protocol['benchmark_sha256'] or dataset['benchmark_sha256']!=protocol['benchmark_sha256']:raise ValueError('Frozen benchmark changed')
    if sha(EXP/'frozen/calibration.json')!=protocol['baseline_settings_sha256']['frozen/calibration.json']:raise ValueError('Frozen calibration changed')
    if sha(ROOT/'experiments/sim_views_20261024/geometry.json')!=benchmark['frozen_sources_sha256']['experiments/sim_views_20261024/geometry.json']:raise ValueError('Frozen scoring geometry changed')
    if a.split=='reserved' and not ledger['final_method_frozen']:raise ValueError('Reserved evidence is sealed until final method freeze')
    if a.split=='reserved' and a.version not in ledger.get('retained_versions',['B0']):raise ValueError('Only baseline/retained versions enter final reserved evaluation')
    if sha(EXP/'versions/B0/depth_module.py')!=benchmark['frozen_sources_sha256']['experiments/depth_ridges_20261024/depth_ridges.py']:raise ValueError('Frozen control generator changed')
    if a.version!='B0':
        if not ledger['baseline_complete'] or int(a.version[1:])>ledger['improvement_rounds_started'] or ledger['improvement_rounds_started']>3:raise ValueError('Round budget/order violation')
    if a.split=='development' and ledger['reserved_released']:raise ValueError('No development after reserved release')
    version=EXP/'versions'/a.version;metadata=json.loads((version/'version.json').read_text())
    if metadata['id']!=a.version:raise ValueError('Version identity mismatch')
    if a.version=='B0':
        for filename,original in [('method.py','experiments/depth_bricks_20261024/batch.py'),('depth_module.py','experiments/depth_ridges_20261024/depth_ridges.py'),('evidence.py','perception/algorithm.py'),('config.json','experiments/depth_bricks_20261024/config.json'),('depth_config.json','experiments/depth_ridges_20261024/config.json')]:
            if sha(version/filename)!=benchmark['frozen_sources_sha256'][original]:raise ValueError('Baseline must remain byte-identical')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');snapshot=ROOT/'runs'/f'{stamp}-partial-{a.version}-{a.split}'
    inference=snapshot/'inference';inputs=inference/'inputs';generator=snapshot/'generator';sources=generator/'source_sensors';scoring=snapshot/'scoring_only';captures=scoring/'captures';output=snapshot/'output'
    for folder in [inputs/'upstream',sources,captures,output]:folder.mkdir(parents=True,exist_ok=True)
    for source,destination in [(EXP/'perception_batch.py',inference/'perception_batch.py'),(version/'method.py',inference/'method.py'),(version/'config.json',inputs/'config.json'),(version/'depth_module.py',inputs/'upstream/depth_module.py'),(version/'depth_config.json',inputs/'upstream/depth_config.json'),(version/'evidence.py',inputs/'upstream/evidence.py'),(EXP/'frozen/calibration.json',inputs/'calibration.json'),(EXP/'prepare_inputs.py',generator/'prepare_inputs.py'),(EXP/'versions/B0/depth_module.py',generator/'original_depth.py')]:shutil.copy2(source,destination)
    render_root=Path(dataset['render_root']);public=[];private=[];recipes=[];copied={}
    def source_case(case):
        if case['id'] in copied:return
        source=render_root/case['split']/case['id'];target=captures/case['id'];(target/'evaluation_truth').mkdir(parents=True)
        gt=['active_bricks.json','active_root_states.npy','annotations.json','cameras.json','native_graph.json','case_state.json']+[f'{v}_depth.npy' for v in benchmark['views']]
        for rel in ['manifest.json']+[f'evaluation_truth/{f}' for f in gt]:
            f=source/rel
            if sha(f)!=dataset['sha256'][str(f.relative_to(render_root))]:raise ValueError(f'Frozen render truth changed:{f}')
            shutil.copy2(f,target/rel)
        for view in benchmark['views']:
            rgb=source/'images'/f'{view}.png';depth=source/'evaluation_truth'/f'{view}_depth.npy'
            for f in [rgb,depth]:
                if sha(f)!=dataset['sha256'][str(f.relative_to(render_root))]:raise ValueError('Frozen sensor changed')
            folder=sources/case['id'];folder.mkdir(exist_ok=True);shutil.copy2(rgb,folder/f'{view}.png');shutil.copy2(depth,folder/f'{view}.npy')
        copied[case['id']]=source
    selected=[c for c in benchmark['cases'] if c['split']==a.split]
    def add_frame(case,view,control=None):
        source_case(case);identity=f'obs{len(public):03d}';folder=sources/case['id']
        public.append({'id':identity,'camera':view,'rgb':f'images/{identity}.png','depth':f'depth/{identity}.npy'})
        recipe={'id':identity,'camera':view,'rgb_source':str(folder/f'{view}.png'),'depth_source':str(folder/f'{view}.npy')}
        if control:recipe.update({key:control[key] for key in ['operation','height_m','pixel_xyxy'] if key in control})
        recipes.append(recipe);private.append({'id':identity,'case_id':case['id'],'view':view,'control_id':control['id'] if control else None,'depth_input_path':str(inputs/f'depth/{identity}.npy')})
    for case in selected:
        for view in benchmark['views']:add_frame(case,view)
    if a.split=='development':
        lookup={c['id']:c for c in selected}
        for control in benchmark['development_controls']:
            case_id,view=control['source'].split('/');add_frame(lookup[case_id],view,control)
    (inputs/'frames.json').write_text(json.dumps(public,indent=2)+'\n');(generator/'recipes.json').write_text(json.dumps(recipes,indent=2)+'\n');(scoring/'frames.json').write_text(json.dumps(private,indent=2)+'\n')
    for f in (EXP/'evaluation').glob('*.py'):shutil.copy2(f,scoring/f.name)
    for source,name in [(EXP/'evaluation/protocol.json','protocol.json'),(EXP/'benchmark.json','benchmark.json'),(ROOT/'experiments/sim_views_20261024/geometry.json','geometry.json')]:shutil.copy2(source,scoring/name)
    previous=None
    if a.previous_evaluation:
        previous=scoring/'previous_evaluation.json';shutil.copy2(a.previous_evaluation,previous)
    commands=[shlex.join([PYTHON,str(generator/'prepare_inputs.py'),'--manifest',str(generator/'recipes.json'),'--inputs',str(inputs),'--depth-helper',str(generator/'original_depth.py')]),shlex.join([PYTHON,str(inference/'perception_batch.py'),'--inputs',str(inputs),'--method',str(inference/'method.py'),'--config',str(inputs/'config.json'),'--output',str(output/'predictions')])]
    scoring_command=[PYTHON,str(scoring/'evaluate.py'),'--captures',str(captures),'--predictions',str(output/'predictions'),'--frames',str(scoring/'frames.json'),'--benchmark',str(scoring/'benchmark.json'),'--geometry',str(scoring/'geometry.json'),'--protocol',str(scoring/'protocol.json'),'--split',a.split,'--output',str(output/'evaluation')]
    if previous:scoring_command+=['--previous-evaluation',str(previous)]
    commands.append(shlex.join(scoring_command));launch=['#!/usr/bin/env bash','set -euo pipefail',f'cd {shlex.quote(str(snapshot))}','export ROBO_PUEUE_JOB=1','export PYTHONDONTWRITEBYTECODE=1',f'export PYTHONPATH={shlex.quote(str(inference))}','export OMP_NUM_THREADS=2','export OPENBLAS_NUM_THREADS=2','export OPENCV_FOR_THREADS_NUM=2',*commands,'test -f output/evaluation/evaluation.json',"printf '%s' '{\"complete\":true}' > run_complete.json",'']
    (snapshot/'launch.sh').write_text('\n'.join(launch));manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'created_utc':stamp,'version':a.version,'split':a.split,'version_metadata':metadata,'frame_count':len(public),'benchmark_sha256':protocol['benchmark_sha256'],'render_job':1686,'render_root':str(render_root),'reserved_feedback_allowed':ledger['final_method_frozen'] if a.split=='reserved' else False,'sha256':{str(f.relative_to(snapshot)):sha(f) for f in sorted(snapshot.rglob('*')) if f.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');task=subprocess.run(['pueue','add','--label',f'robo26-partial-{a.version}-{a.split}',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True);(snapshot/'submission.txt').write_text(task.stdout);print('Snapshot:',snapshot);print(task.stdout.strip())


if __name__=='__main__':main()

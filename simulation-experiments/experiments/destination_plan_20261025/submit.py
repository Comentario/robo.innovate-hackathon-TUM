"""Snapshot the small destination-reference plan and queue its export/audit."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    tracked=[HERE,ROOT/'challenge2/destination_plan.py',ROOT/'tests/test_destination_plan.py']
    if subprocess.check_output(['git','status','--porcelain','--',*map(str,tracked)],cwd=ROOT):raise RuntimeError('Commit reviewed source first')
    protocol=json.loads((HERE/'protocol.json').read_text())
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-destination-plan')
    snapshot.mkdir();code=snapshot/HERE.relative_to(ROOT)
    shutil.copytree(HERE,code,ignore=shutil.ignore_patterns('__pycache__','*.pyc','artifacts','results.json'))
    (snapshot/'challenge2').mkdir()
    for name in ('__init__.py','layout.py','destination_plan.py'):
        shutil.copyfile(ROOT/'challenge2'/name,snapshot/'challenge2'/name)
    frozen=dict(protocol,files={})
    for name,record in protocol['files'].items():
        source=ROOT/record['path']
        if sha(source)!=record['sha256']:raise RuntimeError('Pinned input changed: '+name)
        target=snapshot/'inputs'/(name+source.suffix);target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source,target);frozen['files'][name]=dict(record,path=str(target.relative_to(snapshot)))
    (snapshot/'protocol.json').write_text(json.dumps(frozen,indent=2)+'\n')
    commands=[shlex.join([protocol['runtime_python'],str(code/'export.py'),'--inputs',str(snapshot/'protocol.json'),'--output',str(snapshot/'output')]),
              shlex.join([protocol['runtime_python'],str(code/'evaluate.py'),'--inputs',str(snapshot/'protocol.json'),'--predictions',str(snapshot/'output'),'--output',str(snapshot/'audit')])]
    (snapshot/'pipeline.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\n'+'\n'.join(commands)+'\n')
    (snapshot/'launch.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd '+shlex.quote(str(snapshot))+'\nexport ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1\nexport PYTHONPATH='+shlex.quote(str(snapshot))+'\nexec timeout --signal=TERM --kill-after=2s 25s bash '+shlex.quote(str(snapshot/'pipeline.sh'))+'\n')
    manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'maximum_active_seconds':27,'maximum_jobs':1,'queue':'default','physics_steps':0,'hardware_control':False,'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-destination-plan',shlex.join(['bash',str(snapshot/'launch.sh')])],capture_output=True,text=True,check=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

"""One reviewed saved-output audit; never regenerates destination predictions."""
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
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed audit correction first')
    request=json.loads((HERE/'saved_audit_protocol.json').read_text());parent=ROOT/request['parent_snapshot']
    for relative,digest in request['parent_sha256'].items():
        if sha(parent/relative)!=digest:raise RuntimeError('Original input changed: '+relative)
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-destination-saved-audit')
    snapshot.mkdir();shutil.copyfile(HERE/'evaluate.py',snapshot/'evaluate.py')
    shutil.copyfile(HERE/'saved_audit_protocol.json',snapshot/'saved_audit_protocol.json')
    shutil.copyfile(parent/'protocol.json',snapshot/'protocol.json');shutil.copytree(parent/'inputs',snapshot/'inputs')
    shutil.copyfile(parent/'audit/evaluation.json',snapshot/'original_failed_evaluation.json')
    (snapshot/'predictions').mkdir();shutil.copyfile(parent/'output/destinations.json',snapshot/'predictions/destinations.json')
    command=[request['runtime_python'],str(snapshot/'evaluate.py'),'--inputs',str(snapshot/'protocol.json'),'--predictions',str(snapshot/'predictions'),'--output',str(snapshot/'audit')]
    (snapshot/'launch.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd '+shlex.quote(str(snapshot))+'\nexport ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1\nexec timeout --signal=TERM --kill-after=2s 10s '+shlex.join(command)+'\n')
    manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'parent_job_id':1832,'queue':'default','maximum_active_seconds':12,'predictions_regenerated':False,'sha256':{str(p.relative_to(snapshot)):sha(p) for p in sorted(snapshot.rglob('*')) if p.is_file()}}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-destination-saved-audit',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())


if __name__=='__main__':main()

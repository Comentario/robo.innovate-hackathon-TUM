"""Queue one <=5 s saved-JSON adjudication, with no simulation rerun."""
from datetime import datetime,timezone
import hashlib,json,shlex,shutil,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PYTHON='/home/faps/miniforge3/envs/unitree_sim_env/bin/python'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=json.loads((HERE/'adjudication_protocol.json').read_text())
    if not p['execution_authorized']:raise RuntimeError('Final source review required')
    if subprocess.check_output(['git','status','--porcelain','--',str(HERE)],cwd=ROOT):raise RuntimeError('Commit reviewed adjudication first')
    if any((s/'submission.txt').exists() for s in (ROOT/'runs').glob('*-brick-material-adjudication')):raise RuntimeError('One saved adjudication; no retry')
    for path,digest in p['pinned_inputs_sha256'].items():
        if sha(path)!=digest:raise RuntimeError('Pinned input changed: '+path)
    if sha(HERE/'evaluate.py')!=p['auditor_sha256'] or p['maximum_active_seconds']!=5 or p['prior_case_seconds']+5>2800:raise RuntimeError('Frozen auditor/budget differs')
    snapshot=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-brick-material-adjudication');snapshot.mkdir();(snapshot/'code').mkdir()
    for name in ('evaluate.py','adjudicate.py','adjudication_protocol.json'):shutil.copy2(HERE/name,snapshot/'code'/name)
    launch=['#!/usr/bin/env bash','set -eo pipefail','export ROBO_PUEUE_JOB=1 PYTHONDONTWRITEBYTECODE=1',
        'exec timeout --signal=TERM --kill-after=1s 3s '+shlex.join([PYTHON,str(snapshot/'code/adjudicate.py'),'--output',str(snapshot/'audit')]),'']
    (snapshot/'launch.sh').write_text('\n'.join(launch))
    (snapshot/'manifest.json').write_text(json.dumps({'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'scope':'Saved JSON only; original runtime audit FAIL retained','maximum_active_seconds':5,'maximum_jobs':1,
        'sha256':{str(f.relative_to(snapshot)):sha(f) for f in sorted(snapshot.rglob('*')) if f.is_file()}},indent=2)+'\n')
    result=subprocess.run(['pueue','add','--label','robo26-material-saved-adjudication',shlex.join(['bash',str(snapshot/'launch.sh')])],check=True,capture_output=True,text=True)
    (snapshot/'submission.txt').write_text(result.stdout);print(snapshot);print(result.stdout.strip())

if __name__=='__main__':main()

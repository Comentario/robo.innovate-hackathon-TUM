#!/usr/bin/python3
"""Visit all 30 upper poses of layer 9; stop on any unverified move."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True)
    parser.add_argument('--resume',type=Path,help='Existing sequence directory')
    args=parser.parse_args()
    targets=[f'a_{n}_{m}_9' for n in range(6) for m in range(5)]
    raw=(HERE/'positions.json').read_bytes();signature=hashlib.sha256(raw).hexdigest()
    directory=args.resume or HERE/'sequences'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_layer9')
    directory.mkdir(parents=True,exist_ok=True)
    summary_path=directory/'summary.json'
    summary=json.loads(summary_path.read_text()) if args.resume else dict(layer=9,order=targets,reached=[],completed=False,gripper_commands_sent=False)
    if summary['order']!=targets or summary.get('catalog_sha256',signature)!=signature:
        parser.error('Sequence order/catalog changed; cannot resume')
    if summary.get('failed_target'):
        summary.setdefault('previous_stops',[]).append({k:summary[k] for k in ('failed_target','failure_returncode','failure_outcome') if k in summary})
    for k in ('failed_target','failure_returncode','failure_outcome'):summary.pop(k,None)
    summary['catalog_sha256']=signature
    (directory/'driver_pid.txt').write_text(str(os.getpid()))
    log=(directory/'execution.log').open('a',buffering=1)
    def report(msg):print(msg,flush=True);log.write(msg+'\n')
    def save():summary_path.write_text(json.dumps(summary,indent=2)+'\n')
    report('SEQUENCE_DIRECTORY '+str(directory));save()
    for i in range(len(summary['reached']),len(targets)):
        target=targets[i];report(f'VISIT {i+1}/30 {target}')
        if i==0:
            captured=subprocess.run([str(HERE/'read_pose')],capture_output=True,text=True,timeout=10)
            if captured.returncode:
                report('STOP read-only start capture failed: '+captured.stderr);return 1
            capture=json.loads(captured.stdout);(directory/'resumed_start_capture.json').write_text(captured.stdout)
            s=capture['state'];a=s['O_T_EE'];b=json.loads(raw)['input_bricks'][target]['O_T_EE']
            trace=sum(a[c*4+r]*b[c*4+r] for c in range(3) for r in range(3))
            distance=math.dist(a[12:15],b[12:15]);angle=math.acos(max(-1,min(1,(trace-1)/2)))
            if s['robot_mode']=='Idle' and s['current_errors'] in ([], '[]') and distance<=.001 and angle<=math.pi/180:
                summary['reached'].append(dict(target=target,already_at_start=True,actual_xyz_m=a[12:15],position_error_mm=distance*1000))
                report('REACHED initial verified pose');save();continue
        child=subprocess.Popen(['/usr/bin/python3','-s',str(HERE/'move_xyz.py'),target,'--execute'],
                               stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (directory/'active_child_pid.txt').write_text(str(child.pid));move_log=None
        try:
            for line in child.stdout:
                log.write(line)
                if line.startswith('Motion log:'):
                    move_log=line.split('Motion log:',1)[1].strip();print('RUN_LOG '+move_log,flush=True)
                elif line.startswith(('STOP','ENDPOINT','PASS','Certified arc:','JOINT_METRICS')):print(line,end='',flush=True)
            code=child.wait()
        except KeyboardInterrupt:
            child.send_signal(signal.SIGINT);child.wait();code=130
        outcome_file=Path(move_log).parent/'outcome.json' if move_log else None
        outcome=json.loads(outcome_file.read_text()) if outcome_file and outcome_file.exists() else None
        if code or not outcome or not outcome.get('completed'):
            summary.update(failed_target=target,failure_returncode=code,failure_outcome=outcome)
            save();report('SEQUENCE_STOP '+target);return code or 1
        summary['reached'].append(dict(target=target,already_at_start=False,move_log=move_log,outcome=outcome))
        save();report(f'REACHED {len(summary["reached"])}/30 {target}')
    summary['completed']=True;save();report('SEQUENCE_PASS 30/30 layer 9 positions visited')
    return 0


if __name__=='__main__':sys.exit(main())

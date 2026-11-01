#!/usr/bin/python3
"""Apply configured approach/close finger widths; preview sends no commands."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent


def command_width(action,execute=False):
    config=json.loads((HERE/'motion_config.json').read_text())['gripper']
    width=config['approach_opening_m' if action in ('approach','release') else 'close_target_m']
    speed=config['position_speed_m_s'];tolerance=config['opening_tolerance_m']
    if not all(math.isfinite(v) for v in (width,speed,tolerance)) or not 0<=width<=.08 or not 0<speed<=.1 or not 0<tolerance<=.001:
        raise ValueError('Invalid configured gripper width, speed or tolerance')
    if not execute:
        print(f'PREVIEW gripper {action}: {width*1000:g} mm; no connection or command',flush=True)
        return 0
    directory=HERE/'gripper_moves'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');directory.mkdir(parents=True)
    (directory/'request.json').write_text(json.dumps(dict(action=action,config=config,target_width_m=width,
        command='finger position; no pick verification',arm_motion_sent=False),indent=2)+'\n')
    mode=1 if action=='approach' else 2 if action=='close' else 0
    frozen=directory/'input.txt';payload=f'{width:.17g}\n{speed:.17g}\n{tolerance:.17g}\n{mode}\n'
    if mode==2:payload+=format(config['close_contact_upper_m'],'.17g')+'\n'
    frozen.write_text(payload)
    print('Gripper log:',directory/'execution.log',flush=True)
    result=subprocess.run([str(HERE/'gripper_width'),str(frozen),'--execute'],capture_output=True,text=True)
    output=result.stdout+result.stderr;(directory/'execution.log').write_text(output);print(output,end='',flush=True)
    passed=result.returncode==0 and 'PASS gripper width' in output.splitlines()
    (directory/'outcome.json').write_text(json.dumps(dict(completed=passed,returncode=result.returncode,
        target_width_m=width,pick_verified=False,contact_width_accepted=(action=='close' and passed)),indent=2)+'\n')
    return 0 if passed else result.returncode or 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['approach','close','release']);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    sys.exit(command_width(args.action,args.execute))

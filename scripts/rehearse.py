#!/usr/bin/env python3
"""Own one fresh MoveIt/RViz rehearsal and its output directory."""
import argparse
from datetime import datetime
import fcntl
import json
from html import escape
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def stop(process):
    if process is None or process.poll() is not None:return
    os.killpg(process.pid,signal.SIGINT)
    try:process.wait(timeout=12)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario',choices=['normal','recovery','person1'],nargs='?',default='normal')
    parser.add_argument('--speed',type=float,default=3.)
    parser.add_argument('--hold',type=float,default=600.)
    parser.add_argument('--headless',action='store_true',help='verify without opening RViz')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--inventory',type=Path,default=Path('examples/person1/inventory_with_color.json'),help='Person 1 delivered JSON for person1 scenario')
    parser.add_argument('--recipe',type=Path,help='optional Person 1 recipe; default equal weights across received groups')
    args=parser.parse_args()
    if not 0<args.speed<=20 or not 0<=args.hold<=7200:parser.error('invalid speed or hold duration')
    def interrupted(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    os.chdir(ROOT)
    # Existing servers/clients must be closed deliberately: never kill another session.
    rehearsal_lock=open('/tmp/munich-arm-rehearsal-88.lock','a')
    try:fcntl.flock(rehearsal_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:parser.error('Another rehearsal is already running.')
    locks=[]
    for name in ('server','client'):
        handle=open(f'/tmp/munich-arm-{name}-88.lock','a')
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error(f'An arm {name} is already running. Close that session before rehearsing.')
        locks.append(handle)
    directory=args.output_dir or Path('artifacts')/datetime.now().strftime('rehearsal_%Y%m%d_%H%M%S_%f')
    directory=directory.resolve()
    directory.mkdir(parents=True,exist_ok=False)
    server=client=None
    summary=dict(scenario=args.scenario,status='starting',physical_validation=False,validation_status='awaiting_observation')
    print(f'Rehearsal: {args.scenario}. Evidence: {directory}',flush=True)
    try:
        # arm_demo.sh owns these same locks for each launched process.
        for handle in locks:handle.close()
        with (directory/'server.log').open('w') as log:
            server=subprocess.Popen(['scripts/arm_demo.sh','launch',f'rviz:={str(not args.headless).lower()}'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            # Fail early if the launch cannot start; the adapter then waits for services.
            time.sleep(2)
            if server.poll() is not None:raise RuntimeError('MoveIt launch failed; inspect server.log')
            command=['scripts/arm_demo.sh']
            if args.scenario=='recovery':command+=['recovery','--output-dir',str(directory)]
            else:command+=['--state',str(directory/'state.sqlite3'),'--output',str(directory/'result.json')]
            if args.scenario=='person1':
                command+=['--person1-inventory',str(args.inventory.resolve())]
                if args.recipe:command+=['--person1-config',str(args.recipe.resolve())]
            command+=['--speed',str(args.speed),'--hold',str(args.hold)]
            with (directory/'client.log').open('w') as client_log:
                client=subprocess.Popen(command,stdout=client_log,stderr=subprocess.STDOUT,start_new_session=True)
                print('RViz shows each action and placement count. Logs: client.log. Ctrl+C closes this rehearsal.',flush=True)
                while client.poll() is None:
                    if server.poll() is not None:raise RuntimeError('MoveIt server exited during rehearsal')
                    time.sleep(.5)
                summary['status']='finished' if client.returncode==0 else 'failed'
                summary['client_exit_code']=client.returncode
                if client.returncode:raise RuntimeError('Demo failed; inspect client.log and the preserved journal')
    except KeyboardInterrupt:
        summary['status']='interrupted'
        print('Stopping rehearsal; journal and reports are preserved.',flush=True)
    except Exception as exc:
        summary.update(status='failed',error=str(exc))
        raise
    finally:
        stop(client)
        stop(server)
        result_path=directory/'result.json'
        if result_path.exists():
            result=json.loads(result_path.read_text())
            outcome=result.get('outcome',result)
            summary['execution_status']=outcome['status']
            summary['confirmed']=outcome.get('confirmed',len(outcome.get('confirmed_placements',[])))
            if 'person1_handoff' in result:summary['person1_handoff']=result['person1_handoff']
        (directory/'rehearsal.json').write_text(json.dumps(summary,indent=2)+'\n')
        (directory/'summary.html').write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Robot rehearsal</title>'
            '<style>body{background:#1a2228;color:#eee;font:20px sans-serif;max-width:850px;margin:60px auto}a{color:#9de}</style>'
            '<h1>Robot rehearsal</h1><pre>'+escape(json.dumps(summary,indent=2))+'</pre>'
            '<p>Synthetic Panda playback. Independent pallet validation pending.</p>'
            '<p><a href="client.log">Execution log</a> · <a href="server.log">MoveIt log</a> · '
            + ('<a href="result.json">Execution evidence</a>' if result_path.exists() else 'No final report: inspect the preserved journal before recovery.')+'</p></html>')
    print(f'Rehearsal {summary["status"]}. Evidence: {directory}',flush=True)


if __name__=='__main__':main()

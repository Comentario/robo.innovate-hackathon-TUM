"""Execute a synthetic pick-and-place action contract without ROS or hardware."""
import argparse
import json
from pathlib import Path
from planning.faces import make_face_plan
from . import compile_job, ExecutionSession, SimulatedAdapter, PHASES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',default='examples/faces/inventory.json')
    parser.add_argument('--config',default='examples/faces/config.json')
    parser.add_argument('--cell',default='config/cell.json')
    parser.add_argument('--fail-step',type=int)
    parser.add_argument('--fail-phase',choices=PHASES,default='pick')
    parser.add_argument('--unknown',action='store_true',help='Inject an uncertain outcome requiring reconciliation')
    parser.add_argument('--output',default='artifacts/execution_run.json')
    args=parser.parse_args()
    try:
        read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
        inventory,config,cell=read(args.inventory),read(args.config),read(args.cell)
        plan=make_face_plan(inventory,**config)
        job=compile_job(plan,inventory,cell)
        if args.fail_step is not None and not 1 <= args.fail_step <= len(plan['placements']):
            raise ValueError('fail-step must identify a placement')
        session=ExecutionSession(job,SimulatedAdapter(args.fail_step,args.fail_phase,args.unknown))
        while session.status not in ('stopped','completed'):
            event=session.advance()
            print(f"Step {event['step']:02} | {event['phase']:14} | {event['outcome']}")
        output=Path(args.output)
        if output.resolve() in {Path(p).resolve() for p in (args.inventory,args.config,args.cell)}:
            raise ValueError('output must not overwrite inputs')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(dict(job=job,report=session.report()),indent=2)+'\n')
    except (OSError,ValueError,KeyError,TypeError) as error:
        parser.error(str(error))
    print(f"SIMULATION ONLY | {session.status} | confirmed={len(session.confirmed)} | held={session.held_brick} | uncertain={session.uncertain_brick}")
    print(f'Report: {output}')
    return 0 if session.status=='completed' else 3


if __name__=='__main__':
    raise SystemExit(main())

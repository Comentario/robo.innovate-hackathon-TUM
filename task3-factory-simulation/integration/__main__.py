"""Run, inspect and validate the perception-to-execution integration without ROS."""
import argparse
import json
from pathlib import Path
import sqlite3

from execution import SimulatedAdapter,PHASES
from . import prepare
from .journal import Journal
from .validation import validate_final,plan_digest
from .report import render_report


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ('run','plan','resume','inspect','validate'):
        sub=subs.add_parser(name)
        if name in ('run','plan'):
            sub.add_argument('--snapshot',default='examples/perception/snapshot.json')
            sub.add_argument('--config',default='examples/faces/config.json')
        if name=='run':sub.add_argument('--cell',default='config/cell.json')
        if name!='plan':
            sub.add_argument('--state',default='artifacts/integration.sqlite3')
            if name!='run':sub.add_argument('--run-id')
        if name in ('run','resume'):
            sub.add_argument('--pause-after',type=int)
            sub.add_argument('--fail-step',type=int)
            sub.add_argument('--fail-phase',choices=PHASES,default='pick')
            sub.add_argument('--unknown',action='store_true')
        if name=='validate':sub.add_argument('--observations',required=True)
        sub.add_argument('--output',help='JSON report path; an English HTML report is generated beside it')
    args=parser.parse_args()
    journal=None
    try:
        if args.output:
            candidate=Path(args.output)
            protected={Path(getattr(args,name)).resolve() for name in ('snapshot','config','cell','observations','state') if getattr(args,name,None)}
            if candidate.suffix.lower()!='.json' or candidate.resolve() in protected or candidate.with_suffix('.html').resolve() in protected:
                raise ValueError('output must be a separate .json report')
        if args.command=='plan':
            snapshot,plan,_=prepare(read(args.snapshot),read(args.config))
            result=dict(snapshot_id=snapshot['snapshot_id'],plan_digest=plan_digest(plan),plan=plan)
            if args.output:
                output=Path(args.output)
                if output.resolve() in {Path(args.snapshot).resolve(),Path(args.config).resolve()}:
                    raise ValueError('output must not overwrite inputs')
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text(json.dumps(result,indent=2)+'\n')
                print(f'Plan: {output}')
            else:print(json.dumps(result,indent=2))
            return 0
        state=Path(args.state)
        if args.command!='run' and not state.exists():raise ValueError('state journal does not exist')
        state.parent.mkdir(parents=True,exist_ok=True)
        journal=Journal(state)
        if args.command in ('run','resume'):
            if args.pause_after is not None and args.pause_after<0:raise ValueError('pause-after must be nonnegative')
            adapter=SimulatedAdapter(args.fail_step,args.fail_phase,args.unknown)
            if args.command=='run':
                snapshot,plan,job=prepare(read(args.snapshot),read(args.config),read(args.cell))
                if args.fail_step is not None and args.fail_step>len(plan['placements']):raise ValueError('fail-step is outside the plan')
                runner=journal.create(snapshot,job,adapter)
            else:
                runner=journal.resume_simulation(args.run_id or journal.latest_run_id(),adapter)
            count=0
            while runner.session.status not in ('stopped','completed') and (args.pause_after is None or count<args.pause_after):
                runner.advance();count+=1
            run_id=runner.run_id
        else:run_id=args.run_id or journal.latest_run_id()
        row=journal.inspect(run_id)
        checkpoint=row['checkpoint']
        report=dict(status=row['status'],execution=row['mode'],confirmed_placements=checkpoint['confirmed'],
                    available_ids=checkpoint['available'],held_brick=checkpoint['held_brick'],
                    placed_unconfirmed=checkpoint['placed_unconfirmed'],uncertain_brick=checkpoint['uncertain_brick'],events=checkpoint['events'])
        observations=read(args.observations) if args.command=='validate' else None
        if observations is not None:
            validation=validate_final(row['job']['plan'],observations,run_id=run_id)
            journal.save_validation(run_id,observations,validation)
        else:
            validation=journal.latest_validation(run_id) or validate_final(row['job']['plan'])
        result=dict(run_id=run_id,snapshot=row['snapshot'],job=row['job'],pending_action=row['pending'],
                    plan_digest=plan_digest(row['job']['plan']),execution_report=report,final_validation=validation)
        if row['status'] in ('ready','running'):result['view_status']='paused'
        output=Path(args.output or f'artifacts/integration/{run_id}.json')
        protected={state.resolve()}
        for name in ('snapshot','config','cell','observations'):
            if getattr(args,name,None):protected.add(Path(getattr(args,name)).resolve())
        if output.suffix.lower()!='.json' or output.resolve() in protected or output.with_suffix('.html').resolve() in protected:
            raise ValueError('output must be a separate .json report')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n')
        output.with_suffix('.html').write_text(render_report(result),encoding='utf-8')
        print(f"Run: {run_id}\nExecution: {result.get('view_status',report['status'])} | Confirmed: {len(checkpoint['confirmed'])}\nFinal observation: {validation['status']}\nReport: {output.with_suffix('.html').resolve()}")
        if args.command in ('inspect','validate'):return 5 if validation['status']=='failed' else 0
        return 0 if row['status']=='completed' else 3 if row['status']=='stopped' else 4
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
        print(f'integration: {error}')
        return 2
    finally:
        if journal is not None:journal.close()


if __name__=='__main__':raise SystemExit(main())

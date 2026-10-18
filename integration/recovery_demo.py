"""Create a fresh synthetic failure, blocked assessment and successful partial-pallet continuation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from execution import SimulatedAdapter
from . import prepare
from .journal import Journal
from .recovery import assess_recovery,basis_digest,render_recovery
from .validation import plan_digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='artifacts/recovery_demo')
    args=parser.parse_args()
    directory=Path(args.output_dir);directory.mkdir(parents=True,exist_ok=True)
    state=directory/'state.sqlite3'
    if state.exists():parser.error('demo journal already exists; choose a new output directory to preserve its audit trail')
    root=Path(__file__).resolve().parents[1]
    read=lambda p:json.loads((root/p).read_text())
    snapshot,plan,job=prepare(read('examples/perception/snapshot.json'),read('examples/faces/config.json'),read('config/cell.json'))
    journal=Journal(state)
    try:
        parent=journal.create(snapshot,job,SimulatedAdapter(5,'pick',True))
        while parent.session.status not in ('stopped','completed'):parent.advance()
        row=journal.inspect(parent.run_id)
        preserved=deepcopy(plan['placements'][:4]);placed={p['brick_id'] for p in preserved}
        missing=plan['placements'][4]['brick_id']
        replacement=deepcopy(next(b for b in snapshot['items'] if b['id']==missing));replacement['id']='replacement_01'
        stock=[deepcopy(b) for b in snapshot['items'] if b['id'] not in placed and b['id']!=missing]+[replacement]
        poses={bid:deepcopy(pose) for bid,pose in job['source_poses'].items() if bid not in placed and bid!=missing}
        poses[replacement['id']]=deepcopy(job['source_poses'][missing])
        observation=dict(schema_version='cell-reconciliation-0.1',run_id=parent.run_id,plan_digest=plan_digest(plan),basis_digest=basis_digest(row),observation_id='synthetic-recheck-001',source='synthetic',coverage='complete',gripper={'state':'empty'},robot={'state':'safe_home'},placements=preserved,inventory=stock,missing_ids=[missing],frame='world',units='m',source_poses=poses)
        blocked=deepcopy(observation);blocked['gripper']={'state':'unknown'}
        blocked_proposal=assess_recovery(row,blocked)
        proposal=assess_recovery(row,observation)
        for name,value in [('stopped_run',row),('reconciliation',observation),('blocked_proposal',blocked_proposal),('proposal',proposal)]:
            (directory/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
        (directory/'blocked.html').write_text(render_recovery(blocked_proposal))
        adapter=SimulatedAdapter()
        child=journal.recover_simulation(parent.run_id,observation,adapter,expected_proposal_digest=proposal['proposal_digest'])
        while child.session.status not in ('stopped','completed'):child.advance()
        outcome=dict(run_id=child.run_id,status=child.session.status,confirmed=len(child.session.confirmed),actions=len(adapter.calls),final_validation='awaiting_observation')
        result=dict(proposal=proposal,outcome=outcome,parent_after=journal.inspect(parent.run_id),child=journal.inspect(child.run_id))
        (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        (directory/'index.html').write_text(render_recovery(proposal,outcome=outcome))
        print(f'Recovery demo: {outcome["status"]}\nPreserved: 4\nReplacements: {len(proposal["replacements"])}\nNew actions: {len(adapter.calls)}\nConfirmed: {outcome["confirmed"]}/12\nReport: {(directory/"index.html").resolve()}')
        if blocked_proposal['status']!='blocked' or outcome['status']!='completed':raise RuntimeError('recovery demo failed')
    finally:journal.close()


if __name__=='__main__':main()

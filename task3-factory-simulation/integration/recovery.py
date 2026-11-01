"""Assess complete reconciliation evidence and propose a new job; never replay an uncertain action."""
from copy import deepcopy
import hashlib
import json
from planning.faces import face_candidates
from execution import compile_job
from execution.cell import CellLayout
from .validation import plan_digest


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def basis_digest(row):
    return digest({k:row[k] for k in ('run_id','status','job','checkpoint','pending','mode','snapshot')})


def assess_recovery(row,observation):
    """Preserve a verified pallet prefix; match remaining slots to observed stock of the same shade."""
    if not isinstance(observation,dict) or observation.get('schema_version')!='cell-reconciliation-0.1':
        raise ValueError('expected cell-reconciliation-0.1')
    if observation.get('run_id')!=row['run_id'] or observation.get('plan_digest')!=plan_digest(row['job']['plan']):
        raise ValueError('reconciliation does not identify this run and plan')
    basis=basis_digest(row)
    if observation.get('basis_digest')!=basis:raise ValueError('reconciliation is stale; inspect the current checkpoint')
    oid=observation.get('observation_id')
    if not isinstance(oid,str) or not oid.strip():raise ValueError('observation_id must be nonempty')
    if observation.get('source') not in ('synthetic','perception','operator'):raise ValueError('invalid reconciliation source')
    issues=[]
    def issue(kind,**details):issues.append(dict(kind=kind,**details))
    if row['status'] not in ('stopped','dispatch_unacknowledged'):issue('run_not_stopped')
    if observation.get('coverage')!='complete':issue('incomplete_coverage')
    if observation.get('gripper')!={'state':'empty'}:issue('gripper_not_verified_empty')
    if observation.get('robot')!={'state':'safe_home'}:issue('robot_not_verified_at_safe_home')
    original=row['job']['plan']
    placements=observation.get('placements')
    stock=observation.get('inventory')
    missing=observation.get('missing_ids')
    poses=observation.get('source_poses')
    if not isinstance(placements,list) or not isinstance(stock,list) or not isinstance(missing,list) or not isinstance(poses,dict):
        raise ValueError('placements/inventory/missing_ids lists and source_poses mapping are required')
    if observation.get('frame')!=row['job']['frame'] or observation.get('units')!='m':issue('metric_cell_frame_required')
    cell=CellLayout(row['job']['cell'])
    observed={}
    for item in placements:
        if not isinstance(item,dict) or any(type(item.get(k)) is not int for k in ('layer','row','column')):
            raise ValueError('observed pallet positions require integer coordinates')
        position=tuple(item[k] for k in ('layer','row','column'))
        if position in observed:issue('duplicate_position',position=list(position))
        observed[position]=item
    prefix=[]
    for p in original['placements']:
        key=tuple(p[k] for k in ('layer','row','column'))
        if key not in observed:break
        actual=observed[key]
        for field in ('brick_id','color_group','visible_face','orientation_id'):
            if field in p and actual.get(field)!=p[field]:issue('preserved_placement_mismatch',step=p['step'],field=field)
        prefix.append(deepcopy(p))
    if len(observed)!=len(prefix):issue('non_prefix_or_unexpected_pallet')
    for p in row['checkpoint']['confirmed']:
        if p not in prefix:issue('confirmed_placement_missing_or_changed',step=p['step'])
    original_items={b['id']:b for b in row['snapshot']['items']}
    prefix_ids=[p['brick_id'] for p in prefix]
    ids=[]
    for b in stock:
        if not isinstance(b,dict) or not isinstance(b.get('id'),str) or not b['id'].strip():raise ValueError('stock IDs must be nonempty strings')
        ids.append(b['id'])
    if row['job'].get('person1_handoff'):
        # This reference run continues the exact producer-classified staged batch.
        for brick in stock:
            if not isinstance(brick,dict):raise ValueError('stock must contain objects')
            old=original_items.get(brick.get('id'))
            if old is None:issue('person1_unrecognized_staged_id',brick_id=brick.get('id'))
            elif any(brick.get(key)!=old.get(key) for key in ('color_group','score')):
                issue('person1_producer_classification_changed',brick_id=brick['id'])
    if any(not isinstance(b,str) or not b for b in missing):raise ValueError('missing_ids requires strings')
    all_ids=prefix_ids+ids+missing
    if len(all_ids)!=len(set(all_ids)):issue('duplicate_or_conflicting_brick_locations')
    unaccounted=set(original_items)-set(all_ids)
    if unaccounted:issue('unaccounted_original_ids',brick_ids=sorted(unaccounted))
    if set(missing)-set(original_items):issue('unknown_missing_ids')
    if set(poses)!=set(ids):issue('source_poses_do_not_cover_available_stock')
    valid_poses={}
    for bid,value in poses.items():
        try:
            cell.check_pose(value)
            valid_poses[bid]=value
        except (ValueError,KeyError,TypeError):issue('invalid_source_pose',brick_id=bid)
    values=list(valid_poses.items())
    for i,(a,pa) in enumerate(values):
        for b,pb in values[i+1:]:
            if all(abs(x-y)<size-1e-9 for x,y,size in zip(pa['position_m'],pb['position_m'],cell.size)):
                issue('overlapping_source_poses',brick_ids=[a,b])
    if original['schema_version']=='0.3':choices=face_candidates(stock)[0]
    else:
        choices={}
        for b in stock:
            category=b.get('color_group')
            if not isinstance(category,str) or not category.strip():raise ValueError('stock requires color_group')
            choices[b['id']]=[dict(color_group=category)]
    remaining=original['placements'][len(prefix):]
    candidates={}
    for i,p in enumerate(remaining):
        candidates[i]=[]
        for bid,options in choices.items():
            valid=[c for c in options if c['color_group']==p['color_group'] and (original['schema_version']!='0.3' or c['orientation_id'] in cell.orientations)]
            if valid:candidates[i].append((bid,valid[0]))
        candidates[i].sort(key=lambda pair:(pair[0]!=p['brick_id'],pair[0]))
    assigned,owners={},{}
    def match(slot,seen):
        for bid,choice in sorted(candidates[slot],key=lambda pair:(pair[0] in owners,pair[0]!=remaining[slot]['brick_id'],pair[0])):
            if bid in seen:continue
            seen.add(bid)
            if bid not in owners or match(owners[bid],seen):
                owners[bid]=slot;assigned[slot]=(bid,choice);return True
        return False
    # Preserve compatible original assignments before looking for substitutes.
    for i,p in enumerate(remaining):
        original_choice=next((c for bid,c in candidates[i] if bid==p['brick_id']),None)
        if original_choice is not None:owners[p['brick_id']]=i;assigned[i]=(p['brick_id'],original_choice)
    for i in range(len(remaining)):
        if i not in assigned and not match(i,set()):issue('insufficient_compatible_stock',step=remaining[i]['step'],color_group=remaining[i]['color_group'])
    proposal=dict(schema_version='recovery-proposal-0.1',status='blocked' if issues else 'ready',
        parent_run_id=row['run_id'],basis_digest=basis,observation_id=oid,source=observation['source'],
        execution_scope=('reference_simulator_after_scene_verification' if row['job'].get('execution_backend')=='panda_moveit_kinematic' else 'acknowledgement_simulator_only'),issues=issues,
        preserved_placements=prefix,replacements=[],job=None,snapshot=None)
    if not issues:
        plan=deepcopy(original)
        for i,p in enumerate(plan['placements'][len(prefix):]):
            bid,choice=assigned[i]
            if bid!=p['brick_id']:proposal['replacements'].append(dict(step=p['step'],old_brick_id=p['brick_id'],new_brick_id=bid))
            p.update(brick_id=bid,**choice)
        inventory=[deepcopy(original_items[bid]) for bid in prefix_ids]+deepcopy(stock)
        if plan['schema_version']=='0.3':
            cs,unknown=face_candidates(inventory)
            plan['face_policy'].update(unknown_allowed_faces=unknown,excluded_brick_ids=sorted(bid for bid,options in cs.items() if not options))
        try:job=compile_job(plan,inventory,row['job']['cell'],source_poses=poses,preserved_placements=prefix)
        except ValueError as error:
            issue('invalid_recovery_geometry',reason=str(error));proposal['status']='blocked'
        else:
            token=digest(dict(parent=row['run_id'],basis=basis,observation=observation))[:16]
            job['job_id']=token
            for command in job['commands']:command['action_id']=f'{token}/{command["step"]}/{command["phase"]}'
            job['recovery']=dict(parent_run_id=row['run_id'],observation_id=oid,source=observation['source'],basis_digest=basis)
            if row['job'].get('person1_handoff'):job['person1_handoff']=deepcopy(row['job']['person1_handoff'])
            proposal['job']=job
            proposal['snapshot']=dict(schema_version='inventory-snapshot-0.1',snapshot_id=f'recovery/{row["run_id"]}/{oid}',source='synthetic',face_aware=plan['schema_version']=='0.3',items=inventory,reconciliation_source=observation['source'])
    if proposal['snapshot'] is not None and row['job'].get('person1_handoff'):
        proposal['snapshot']['producer']=deepcopy(row['snapshot'].get('producer',{}))
    proposal['proposal_digest']=digest(proposal)
    return proposal


def render_recovery(proposal,*,outcome=None):
    """A standalone English explanation of preserved work, substitutions and evidence limits."""
    from html import escape
    esc=lambda v:escape(str(v))
    preserved={p['step'] for p in proposal['preserved_placements']}
    changed={r['step']:r for r in proposal['replacements']}
    job=proposal['job']
    cells=''
    if job:
        for layer in range(job['plan']['shape']['layers']):
            cells+=f'<h3>Layer {layer+1}</h3><div class="grid" style="grid-template-columns:repeat({job["plan"]["shape"]["columns"]},1fr)">'
            for p in job['plan']['placements']:
                if p['layer']!=layer:continue
                kind='preserved' if p['step'] in preserved else 'replacement' if p['step'] in changed else 'pending'
                color={'dark':'#704331','medium':'#b77852','light':'#e7c8a1'}.get(p['color_group'],'#77838a')
                text='#29231e' if p['color_group']=='light' else '#ffffff'
                cells+=f'<div class="brick {kind}" style="background:{color};color:{text}"><b>#{p["step"]} {esc(p["color_group"])}</b><small>{esc(p["brick_id"])}</small><small>{esc(p.get("visible_face","face not modeled"))} · {kind}</small></div>'
            cells+='</div>'
    producer_notice=''
    if job and job.get('person1_handoff'):
        h=job['person1_handoff']
        producer_notice=f'<p>Person 1 export: <b>{esc(h["image_id"])}</b> · {len(h["group_centers_lab"])} received groups. Original IDs, classes and scores are retained; no additional score filter. Pick positions are synthetic. Card backgrounds do not reconstruct material color.</p>'
    rows=''.join(f'<tr><td>{r["step"]}</td><td>{esc(r["old_brick_id"])}</td><td>{esc(r["new_brick_id"])}</td></tr>' for r in proposal['replacements'])
    issues=''.join(f'<li>{esc(i)}</li>' for i in proposal['issues'])
    scope_notice=('Panda kinematic continuation requires live joint and collision-scene verification. Hardware is not resumed.' if proposal['execution_scope']=='reference_simulator_after_scene_verification' else 'This continuation supports the acknowledgement simulator only; Panda and hardware adapters are not resumed.')
    result=''
    if outcome:
        result=f'<h2>Continuation result</h2><p><b>{esc(outcome["status"])}</b> · {outcome["confirmed"]} positions confirmed in the simulator · {outcome["actions"]} new action acknowledgements.</p><p>New run: <code>{esc(outcome["run_id"])}</code>. The original checkpoint and dispatch history remain archived.</p>'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Partial pallet recovery</title>
<style>body{{background:#122027;color:#edf3f6;font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 24px}}p{{line-height:1.65;color:#c5d7df}}h1{{font-size:36px}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:#21333d;padding:20px;border-radius:12px;flex:1;min-width:150px}}.card b{{display:block;font-size:26px;margin-top:10px}}.grid{{display:grid;gap:12px}}.brick{{padding:20px 12px;border:4px solid transparent;border-radius:8px;min-width:0;overflow-wrap:anywhere}}.preserved{{border-color:#69e5ba}}.replacement{{border-color:#ffc770}}small{{display:block;margin-top:6px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #50616a;text-align:left}}.notice{{border-left:4px solid #ffc770;padding:16px;background:#34342e}}code{{overflow-wrap:anywhere}}h2{{margin-top:32px}}</style>
<h1>Partial pallet recovery</h1><p>Stop → reconcile the cell → preserve verified placements → plan remaining work → continue in a new simulation run.</p>
<p class="notice">Evidence source: <b>{esc(proposal['source'])}</b>. A declared observation is not proof of a physical grasp or a camera-validated pallet. {esc(scope_notice)}</p>
<div class="cards"><div class="card">Proposal<b>{esc(proposal['status'].upper())}</b></div><div class="card">Preserved positions<b>{len(preserved)}</b></div><div class="card">Substituted bricks<b>{len(changed)}</b></div><div class="card">Remaining actions<b>{len(job['commands']) if job else 'Blocked'}</b></div></div>
<h2>Reconciliation requirements</h2><p>Complete cell coverage, empty gripper, robot at safe home, all original IDs accounted for, and a verified prefix of the pallet. Source positions must be in meters in the cell frame. Unresolved evidence blocks execution.</p>
<h2>Recovery plan · before continuation</h2>{producer_notice}<p>Green border: already placed, no new pick. Amber border: replacement with the same shade. Other cells: remaining work. The recipe and shade pattern remain unchanged.</p>{cells or '<p>No continuation job was produced.</p>'}
<h2>Substitutions</h2><table><tr><th>Step</th><th>Unavailable brick</th><th>Replacement</th></tr>{rows or '<tr><td colspan="3">No substitutions</td></tr>'}</table>
<h2>Blocking issues</h2><ul>{issues or '<li>No blocking issues in the supplied reconciliation.</li>'}</ul>{result}
<h2>Audit trail</h2><p>Parent run: <code>{esc(proposal['parent_run_id'])}</code><br>Observation: <code>{esc(proposal['observation_id'])}</code><br>Checkpoint digest: <code>{esc(proposal['basis_digest'])}</code></p>
<p>A new job uses new action IDs. Old pending dispatches are archived, not replayed. A stale executor cannot overwrite the child run. Independent final validation remains a separate step.</p></html>'''


def main():
    import argparse
    import sqlite3
    from pathlib import Path
    from .journal import Journal
    from execution import SimulatedAdapter
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    for name in ('inspect','assess','continue'):
        sub=subs.add_parser(name)
        sub.add_argument('--state',required=True)
        sub.add_argument('--run-id')
        sub.add_argument('--output',required=True)
        if name!='inspect':sub.add_argument('--observations',required=True)
        if name=='continue':sub.add_argument('--proposal-digest',required=True)
    args=parser.parse_args()
    journal=None
    try:
        state=Path(args.state);output=Path(args.output)
        if not state.exists():raise ValueError('state journal does not exist')
        protected={state.resolve()}
        if getattr(args,'observations',None):protected.add(Path(args.observations).resolve())
        if output.suffix!='.json' or output.resolve() in protected or output.with_suffix('.html').resolve() in protected:
            raise ValueError('output must be a separate JSON report')
        journal=Journal(state)
        run_id=args.run_id or journal.latest_run_id()
        row=journal.inspect(run_id)
        outcome=None
        if args.command=='inspect':
            result=dict(run_id=run_id,plan_digest=plan_digest(row['job']['plan']),basis_digest=basis_digest(row),status=row['status'],checkpoint=row['checkpoint'],pending=row['pending'])
        else:
            observation=json.loads(Path(args.observations).read_text())
            result=assess_recovery(row,observation)
            if args.command=='continue':
                runner=journal.recover_simulation(run_id,observation,SimulatedAdapter(),expected_proposal_digest=args.proposal_digest)
                while runner.session.status not in ('stopped','completed'):runner.advance()
                outcome=dict(run_id=runner.run_id,status=runner.session.status,confirmed=len(runner.session.confirmed),actions=len(runner.session.events),final_validation='awaiting_observation')
                result['continuation']=outcome
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n')
        if args.command!='inspect':output.with_suffix('.html').write_text(render_recovery(result,outcome=outcome))
        print(f'Recovery {args.command}: {result["status"]}\nReport: {output.resolve()}')
        return 3 if result['status']=='blocked' else 0
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        print(f'recovery: {error}');return 2
    finally:
        if journal:journal.close()


if __name__=='__main__':raise SystemExit(main())

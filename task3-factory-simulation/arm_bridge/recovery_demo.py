"""Stop after four placements, reconstruct the Panda client, verify the live scene and continue."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import rclpy
from execution import ActionResult
from integration import prepare
from integration.journal import Journal
from integration.recovery import assess_recovery,render_recovery
from .adapter import MoveItAdapter
from .recovery import save_robot_checkpoint,load_robot_checkpoint,prepare_home
from .scene_state import scene_digest,without_timestamps


class StopBeforeFifth:
    mode='simulation_only'
    backend='panda_moveit_kinematic'
    def __init__(self,adapter):self.adapter=adapter
    def perform(self,command):
        if command['step']==5 and command['phase']=='approach_pick':
            return ActionResult('unknown','injected_stop_before_fifth_brick_motion')
        return self.adapter.perform(command)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--speed',type=float,default=2.)
    parser.add_argument('--pause',type=float,default=8.)
    parser.add_argument('--hold',type=float,default=600.)
    parser.add_argument('--person1-inventory',type=Path,help='producer JSON; preserve delivered IDs, classes and scores')
    parser.add_argument('--person1-config',type=Path,help='optional recipe using producer group names')
    args=parser.parse_args()
    if args.person1_config and not args.person1_inventory:parser.error('person1-config requires person1-inventory')
    if not 0<args.speed<=20 or not 0<=args.pause<=60 or not 0<=args.hold<=7200:parser.error('invalid speed or duration')
    directory=Path(args.output_dir);directory.mkdir(parents=True,exist_ok=True)
    state=directory/'state.sqlite3'
    generated={directory/name for name in ('state.sqlite3','person1_handoff.json','stopped_run.json','robot_checkpoint.json','restored_scene.json','home_preparation.json','reconciliation.json','proposal.json','final_scene.json','result.json','index.html')}
    protected={p.resolve() for p in (args.person1_inventory,args.person1_config) if p}
    if any(p.exists() or p.resolve() in protected for p in generated):parser.error('recovery evidence must be new and separate from inputs; choose a new output directory')
    root=Path(__file__).resolve().parents[1]
    read=lambda p:json.loads((root/p).read_text())
    bundle=None
    if args.person1_inventory:
        from integration.person1_simulation import prepare_person1_simulation
        inventory=json.loads(args.person1_inventory.read_text())
        config=json.loads(args.person1_config.read_text()) if args.person1_config else None
        bundle=prepare_person1_simulation(inventory,read('config/cell_panda.json'),config)
        snapshot,plan,job=(bundle[name] for name in ('staged_snapshot','plan','job'))
    else:
        snapshot,plan,job=prepare(read('examples/perception/snapshot.json'),read('examples/faces/config.json'),read('config/cell_panda.json'))
    if len(plan['placements'])!=12:parser.error('this recovery rehearsal requires a 12-position plan')
    save=lambda name,value:(directory/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
    rclpy.init();journal=Journal(state);adapter=None
    try:
        if bundle:save('person1_handoff',bundle)
        adapter=MoveItAdapter(job,speed=args.speed)
        parent=journal.create(snapshot,job,StopBeforeFifth(adapter))
        print('Phase 1: build four positions, then inject a stop before the fifth pick.',flush=True)
        while parent.session.status not in ('stopped','completed'):print(json.dumps(parent.advance()),flush=True)
        if len(parent.session.confirmed)!=4:raise RuntimeError('demo did not reach the intended four-placement checkpoint')
        row=journal.inspect(parent.run_id);save('stopped_run',row)
        print('STOPPED: four positions preserved. No fifth brick was moved.',flush=True)
        adapter.demo_status="STOPPED: four placements preserved; recovery pending"
        adapter.publish_state()
        adapter.spin_for(args.pause)
        saved=save_robot_checkpoint(journal,row,adapter);save('robot_checkpoint',saved)
        adapter.destroy_node();adapter=None
        # Recreate only the client. MoveIt and RViz retain the actual collision scene.
        saved=load_robot_checkpoint(journal,row)
        adapter=MoveItAdapter(row['job'],speed=args.speed,restore=True,saved_state=saved)
        _,restored=adapter.capture_scene();save('restored_scene',restored)
        if scene_digest(restored)!=saved['scene_digest']:raise RuntimeError('restoration changed the robot or scene')
        print('Phase 2: joints and scene restored without resetting the pallet.',flush=True)
        adapter.demo_status="RECOVERY: verifying scene and returning home"
        preparation=prepare_home(journal,row,adapter);save('home_preparation',preparation)
        observation=adapter.reconciliation(row,'panda-live-recheck-001');save('reconciliation',observation)
        proposal=assess_recovery(row,observation);save('proposal',proposal)
        if proposal['status']!='ready':raise RuntimeError('reference reconciliation blocked: '+str(proposal['issues']))
        if len(proposal['preserved_placements'])!=4:raise RuntimeError('reference observation did not preserve exactly four positions')
        before={p['brick_id']:deepcopy(observation['robot_scene']['objects'][p['brick_id']]) for p in proposal['preserved_placements']}
        child=journal.recover_reference_simulation(parent.run_id,observation,adapter,expected_proposal_digest=proposal['proposal_digest'])
        print('Phase 3: new Panda run; execute 64 remaining actions, preserving the four outlined bricks.',flush=True)
        while child.session.status not in ('stopped','completed'):print(json.dumps(child.advance()),flush=True)
        after_row=journal.inspect(parent.run_id)
        if after_row['checkpoint']!=row['checkpoint'] or after_row['pending']!=row['pending']:raise RuntimeError('parent history was changed')
        _,final_scene=adapter.capture_scene();save('final_scene',final_scene)
        unchanged=all(without_timestamps(value)==without_timestamps(final_scene['objects'][bid]) for bid,value in before.items())
        if not unchanged:raise RuntimeError('a preserved collision object moved')
        if any(e['step']<=4 for e in child.session.events):raise RuntimeError('a preserved placement was replayed')
        success=child.session.status=='completed' and len(child.session.confirmed)==12 and len(child.session.events)==64
        outcome=dict(run_id=child.run_id,status=child.session.status,confirmed=len(child.session.confirmed),actions=len(child.session.events),preserved_objects_unchanged=unchanged,final_validation='awaiting_observation',physical_validation=False)
        result=dict(parent_run_id=parent.run_id,proposal=proposal,outcome=outcome,parent_after=after_row,child=journal.inspect(child.run_id),motion_evidence=adapter.evidence,playback_metrics=adapter.playback_metrics)
        if bundle:
            parent_items={b['id']:(b['color_group'],b.get('score')) for b in snapshot['items']}
            child_items={b['id']:(b['color_group'],b.get('score')) for b in result['child']['snapshot']['items']}
            continuity=dict(producer_handoff_unchanged=result['child']['job'].get('person1_handoff')==bundle['handoff'],ids_groups_scores_unchanged=parent_items==child_items,recipe_and_plan_unchanged=result['child']['job']['plan']==plan,no_additional_score_filter=not bundle['handoff']['additional_score_filter'])
            result.update(person1_handoff=bundle['handoff'],producer_continuity=continuity)
            if not all(continuity.values()):raise RuntimeError('producer data or plan changed during reference recovery')
            outcome.update(producer_data_unchanged=True,recipe_unchanged=True)
        save('result',result)
        (directory/'index.html').write_text(render_recovery(proposal,outcome=outcome))
        print(f'Panda recovery: {outcome["status"]}; preserved=4; new actions={outcome["actions"]}; confirmed={outcome["confirmed"]}/12; unchanged={unchanged}',flush=True)
        adapter.demo_status=f"{outcome['status'].upper()}: recovery; four placements preserved"
        adapter.publish_state()
        adapter.timer.timer_period_ns=500_000_000
        adapter.spin_for(args.hold)
        if not success:raise SystemExit(2)
    finally:
        journal.close()
        if adapter:adapter.destroy_node()
        rclpy.shutdown()


if __name__=='__main__':main()

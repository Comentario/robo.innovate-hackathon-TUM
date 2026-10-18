"""Run the existing planner/executor against the optional Panda reference adapter."""
import argparse
import json
from pathlib import Path
import rclpy
from integration import prepare
from integration.journal import Journal
from .adapter import MoveItAdapter, hand_goal, box
from moveit_msgs.msg import PlanningScene, CollisionObject


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',required=True,help='new SQLite journal; existing cycles are refused')
    parser.add_argument('--output',default='artifacts/arm_report.json')
    parser.add_argument('--speed',type=float,default=4.)
    parser.add_argument('--hold',type=float,default=0.,help='keep publishing completed scene for RViz, seconds')
    parser.add_argument('--probes',action='store_true',help='test blocked and unreachable goals before execution')
    args=parser.parse_args()
    if not 0<args.speed<=20:parser.error('speed must be in (0,20]')
    output=Path(args.output)
    if output.suffix!='.json' or output.resolve() in {Path(args.state).resolve(),Path('examples/perception/snapshot.json').resolve(),Path('examples/faces/config.json').resolve(),Path('config/cell_panda.json').resolve()}:
        parser.error('output must be a separate JSON report')
    output.parent.mkdir(parents=True,exist_ok=True)
    Path(args.state).parent.mkdir(parents=True,exist_ok=True)
    snapshot=json.loads(Path('examples/perception/snapshot.json').read_text())
    config=json.loads(Path('examples/faces/config.json').read_text())
    cell=json.loads(Path('config/cell_panda.json').read_text())
    snapshot,plan,job=prepare(snapshot,config,cell)
    rclpy.init()
    adapter=None
    journal=Journal(args.state)
    try:
        # Refuse stale cycles before changing the simulated world.
        if journal.db.execute('SELECT 1 FROM cell_cycle').fetchone():raise ValueError('journal already contains a cycle; inspect it, do not replay')
        adapter=MoveItAdapter(job,speed=args.speed)
        probes={}
        if args.probes:
            goal=hand_goal(job['commands'][0]['object_pose'])
            bad=hand_goal(dict(position_m=[2.,0.,.2],orientation_xyzw=[0,0,0,1]))
            path,code=adapter.plan_to(bad)
            probes['unreachable']=dict(rejected=path is None,moveit_error_code=code)
            scene=PlanningScene(is_diff=True)
            scene.world.collision_objects=[box('probe_blocker',[.16,.16,.16],dict(position_m=[goal.position.x,goal.position.y,goal.position.z],orientation_xyzw=[0,0,0,1]))]
            adapter.scene(scene)
            path,code=adapter.plan_to(goal)
            probes['blocked']=dict(rejected=path is None,moveit_error_code=code)
            scene.world.collision_objects=[CollisionObject(id='probe_blocker',operation=CollisionObject.REMOVE)]
            adapter.scene(scene)
            if not all(p['rejected'] for p in probes.values()):raise RuntimeError('negative motion probes failed')
        runner=journal.create(snapshot,job,adapter)
        while runner.session.status not in ('stopped','completed'):
            event=runner.advance()
            print(json.dumps(event),flush=True)
        report=runner.session.report()
        report.update(run_id=runner.run_id,reference_robot='Panda',physical_validation=False,validation_status='awaiting_observation',confirmation='synthetic_scene_only',motion_probes=probes,motion_evidence=adapter.evidence)
        Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
        print(f'Arm demo: {report["status"]}; confirmed={len(report["confirmed_placements"])}',flush=True)
        # A completed scene needs only a slow heartbeat, especially with software GL.
        adapter.timer.timer_period_ns=500_000_000
        adapter.spin_for(args.hold)
        if report['status']!='completed':raise SystemExit(2)
    finally:
        journal.close()
        if adapter:adapter.destroy_node()
        rclpy.shutdown()


if __name__=='__main__':main()

"""Transport-independent workcell execution contract and deterministic simulation."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from demo import validate_plan
from .cell import CellLayout, pose

PHASES = ('approach_pick','pick','lift','orient','approach_place','place','confirm','retreat')


@dataclass(frozen=True)
class ActionResult:
    outcome: str  # succeeded, failed_before_action, or unknown
    reason: str = ''


class ExecutionAdapter(Protocol):
    mode: str
    backend: str
    def perform(self, command: dict) -> ActionResult:
        """Acknowledge a command; timeouts must return unknown, never implicit success."""
        ...


def compile_job(plan, inventory, cell_config, *, source_poses=None, preserved_placements=None):
    validate_plan(plan, inventory)
    preserved=[] if preserved_placements is None else deepcopy(preserved_placements)
    if not isinstance(preserved,list) or preserved!=plan['placements'][:len(preserved)] or len(preserved)>len(plan['placements']):
        raise ValueError('preserved placements must be an exact ordered plan prefix')
    preserved_ids={p['brick_id'] for p in preserved}
    active_inventory=[b for b in inventory if b['id'] not in preserved_ids]
    cell = CellLayout(cell_config)
    if any(plan['shape'][k] > cell.capacity[k] for k in cell.capacity):
        raise ValueError('plan exceeds configured pallet capacity')
    if source_poses is None:
        source = {b['id']:cell.source_pose(i) for i,b in enumerate(active_inventory)}
    else:
        if not isinstance(source_poses,dict) or set(source_poses)!={b['id'] for b in active_inventory}:
            raise ValueError('source poses must cover every inventory ID exactly once')
        source = deepcopy(source_poses)
    for value in source.values():
        cell.check_pose(value)
    destinations = [cell.target_pose(p) for p in plan['placements']]
    # Reject a static source/target overlap, independently of motion planning.
    for start in source.values():
        for target in destinations:
            if all(abs(a-b) < size-1e-9 for a,b,size in zip(start['position_m'], target['position_m'],cell.size)):
                raise ValueError('source brick overlaps a pallet destination')
    identity=dict(plan=plan,cell=cell_config,inventory=inventory)
    if preserved:identity.update(preserved_placements=preserved,source_poses=source)
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    commands = []
    for p,target in list(zip(plan['placements'],destinations))[len(preserved):]:
        start = source[p['brick_id']]
        lifted = cell.above(start)
        oriented = pose(lifted['position_m'],target['orientation_xyzw'])
        values = (cell.above(start),start,lifted,oriented,cell.above(target),target,target,cell.above(target))
        for phase,value in zip(PHASES,values):
            cell.check_pose(value)
            commands.append(dict(action_id=f'{digest}/{p["step"]}/{phase}', step=p['step'],
                                 brick_id=p['brick_id'], phase=phase, frame=cell.frame,
                                 object_pose=deepcopy(value), placement=deepcopy(p)))
    result=dict(schema_version='execution-job-0.1',job_id=digest,frame=cell.frame,
                plan=deepcopy(plan),cell=deepcopy(cell_config),source_poses=source,commands=commands)
    if preserved:result['preserved_placements']=preserved
    return result


class SimulatedAdapter:
    mode = "simulation_only"
    backend = "acknowledgement_simulator"
    """Deterministic acknowledgements; no SDK, physical grasp or motion planner."""
    def __init__(self, fail_step=None, fail_phase='pick', unknown=False):
        if fail_phase not in PHASES or (fail_step is not None and (type(fail_step) is not int or fail_step <= 0)):
            raise ValueError('invalid simulated failure')
        self.fail_step,self.fail_phase,self.unknown = fail_step,fail_phase,unknown
        self.calls = []

    def perform(self, command):
        self.calls.append(deepcopy(command))
        if command['step']==self.fail_step and command['phase']==self.fail_phase:
            return ActionResult('unknown' if self.unknown else 'failed_before_action','injected_simulation_failure')
        return ActionResult('succeeded')


class ExecutionSession:
    """Advance only after an acknowledgement; never automatically retry a stopped job."""
    def __init__(self, job, adapter):
        self.mode = getattr(adapter,'mode',None)
        if self.mode not in ('simulation_only','hardware'):
            raise ValueError('adapter must declare its execution mode')
        if self.mode=='hardware' and job.get('person1_handoff',{}).get('geometry_source')=='synthetic_staging_grid':
            raise ValueError('Person 1 synthetic staging is simulation-only; hardware requires measured cell poses')
        self.job,self.adapter = deepcopy(job),adapter
        self.cursor,self.status = 0,'ready'
        self.available = set(job['source_poses'])
        self.held_brick = None
        self.placed_unconfirmed = None
        self.uncertain_brick = None
        self.confirmed = deepcopy(job.get('preserved_placements',[]))
        if not job['commands']:self.status='completed'
        self.events = []
        self.object_pose = deepcopy(CellLayout(job['cell']).home)

    def advance(self):
        if self.status in ('stopped','completed'):
            return None
        command = self.job['commands'][self.cursor]
        if command['phase']=='pick' and command['brick_id'] not in self.available:
            result = ActionResult('failed_before_action','brick_no_longer_available')
        else:
            try:
                result = self.adapter.perform(deepcopy(command))
                if not isinstance(result,ActionResult) or result.outcome not in ('succeeded','failed_before_action','unknown'):
                    result = ActionResult('unknown','invalid_adapter_acknowledgement')
            except Exception as error:
                result = ActionResult('unknown',str(error))
        event = dict(action_id=command['action_id'],step=command['step'],brick_id=command['brick_id'],
                     phase=command['phase'],outcome=result.outcome,reason=result.reason,execution=self.mode)
        if result.outcome != 'succeeded':
            self.status = 'stopped'
            if result.outcome=='unknown':
                self.uncertain_brick = command['brick_id']
                self.available.discard(command['brick_id'])
            event['next_action']='reconcile_inventory_gripper_and_pallet'
        else:
            self.object_pose = deepcopy(command['object_pose'])
            if command['phase']=='pick':
                self.available.remove(command['brick_id'])
                self.held_brick = command['brick_id']
            elif command['phase']=='place':
                self.held_brick = None
                self.placed_unconfirmed = command['brick_id']
            elif command['phase']=='confirm':
                self.confirmed.append(deepcopy(command['placement']))
                self.placed_unconfirmed = None
            self.cursor += 1
            self.status = 'completed' if self.cursor==len(self.job['commands']) else 'running'
        event['status'],event['confirmed'] = self.status,len(self.confirmed)
        self.events.append(event)
        return deepcopy(event)

    def report(self):
        return dict(schema_version='execution-report-0.1',job_id=self.job['job_id'],status=self.status,
                    execution=self.mode,confirmed_placements=deepcopy(self.confirmed),
                    available_ids=sorted(self.available),held_brick=self.held_brick,
                    placed_unconfirmed=self.placed_unconfirmed,uncertain_brick=self.uncertain_brick,
                    resume_supported=False,events=deepcopy(self.events))

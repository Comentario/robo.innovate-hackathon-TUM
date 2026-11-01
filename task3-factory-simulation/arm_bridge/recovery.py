"""Reference-only recovery preparation with write-ahead records for the home trajectory."""
import json
import time
from integration.recovery import basis_digest
from .scene_state import scene_digest


def require_owner(journal,row,adapter):
    if row['mode']!='simulation_only' or row['job'].get('execution_backend')!='panda_moveit_kinematic' or adapter.mode!='simulation_only' or adapter.backend!='panda_moveit_kinematic':
        raise ValueError('reference preparation requires a Panda simulation run')
    if adapter.job['job_id']!=row['job']['job_id']:raise ValueError('adapter belongs to another job')
    if basis_digest(journal.inspect(row['run_id']))!=basis_digest(row):raise ValueError('reference run changed')
    owner=journal.db.execute('SELECT run_id FROM cell_cycle WHERE name=?',('default',)).fetchone()
    if owner is None or owner['run_id']!=row['run_id']:raise ValueError('run no longer owns reference cell')


def save_robot_checkpoint(journal,row,adapter):
    require_owner(journal,row,adapter)
    if row['status'] not in ('stopped','dispatch_unacknowledged'):raise ValueError('robot checkpoint requires a stopped run')
    _,scene=adapter.capture_scene()
    payload=dict(run_id=row['run_id'],job_id=row['job']['job_id'],basis_digest=basis_digest(row),scene_digest=scene_digest(scene),scene=scene,
        visual_time_ns=adapter.visual_epoch_ns+time.monotonic_ns()-adapter.visual_start_ns)
    journal.db.execute('INSERT INTO reference_checkpoints VALUES(?,?)',(row['run_id'],json.dumps(payload)))
    return payload


def load_robot_checkpoint(journal,row):
    saved=journal.db.execute('SELECT payload FROM reference_checkpoints WHERE run_id=?',(row['run_id'],)).fetchone()
    if saved is None:raise ValueError('reference robot checkpoint unavailable')
    payload=json.loads(saved['payload'])
    if payload['basis_digest']!=basis_digest(row):raise ValueError('reference checkpoint is stale')
    return payload


def prepare_home(journal,row,adapter):
    require_owner(journal,row,adapter)
    if row['status'] not in ('stopped','dispatch_unacknowledged'):raise ValueError('run is not stopped')
    _,before=adapter.capture_scene()
    payload=dict(before_scene_digest=scene_digest(before),intent='collision_checked_reference_home',outcome='pending')
    # A second attempt is refused, especially if the first move was unacknowledged.
    journal.db.execute('INSERT INTO reference_preparations VALUES(?,?,?,?)',(row['run_id'],'pending',basis_digest(row),json.dumps(payload)))
    try:
        result=adapter.move_to_recovery_home()
        if result.outcome!='succeeded':
            payload.update(outcome=result.outcome,reason=result.reason)
            journal.db.execute('UPDATE reference_preparations SET status=?,payload=? WHERE run_id=?',(result.outcome,json.dumps(payload),row['run_id']))
            raise ValueError('reference home trajectory was rejected: '+result.reason)
        _,after=adapter.capture_scene()
        payload.update(outcome='succeeded',after_scene_digest=scene_digest(after))
        journal.db.execute('UPDATE reference_preparations SET status=?,payload=? WHERE run_id=?',('succeeded',json.dumps(payload),row['run_id']))
        return payload
    except BaseException as error:
        if payload['outcome']=='pending':
            payload.update(outcome='unknown',reason=str(error))
            journal.db.execute('UPDATE reference_preparations SET status=?,payload=? WHERE run_id=?',('unknown',json.dumps(payload),row['run_id']))
        raise

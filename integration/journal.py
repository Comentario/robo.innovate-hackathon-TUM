"""SQLite reservations and write-ahead dispatch records for a single cell cycle."""
from copy import deepcopy
import json
import sqlite3
from uuid import uuid4

from execution import ExecutionSession

FIELDS=('cursor','status','available','held_brick','placed_unconfirmed','uncertain_brick','confirmed','events','object_pose')


def checkpoint(session):
    result={k:deepcopy(getattr(session,k)) for k in FIELDS}
    result['available']=sorted(result['available'])
    return result


class Journal:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path),timeout=5,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,snapshot_id TEXT UNIQUE NOT NULL,
            job TEXT NOT NULL,checkpoint TEXT NOT NULL,status TEXT NOT NULL,pending TEXT,mode TEXT NOT NULL,snapshot TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reservations(brick_id TEXT PRIMARY KEY,run_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cell_cycle(name TEXT PRIMARY KEY,run_id TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS validations(run_id TEXT NOT NULL,observation_id TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL,UNIQUE(run_id,observation_id));
        ''')

    def close(self):self.db.close()

    def create(self,snapshot,job,adapter):
        job=deepcopy(job)
        job['execution_backend']=getattr(adapter,'backend','external_adapter')
        session=ExecutionSession(job,adapter)
        run_id=uuid4().hex
        try:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM runs WHERE snapshot_id=?',(snapshot['snapshot_id'],)).fetchone():
                raise ValueError('snapshot already registered; inspect its existing run instead of replaying')
            if self.db.execute('SELECT 1 FROM cell_cycle').fetchone():
                raise ValueError('this cell cycle is already occupied; no second pallet run is allowed')
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',
                            (run_id,snapshot['snapshot_id'],json.dumps(job),json.dumps(checkpoint(session)),'ready',None,adapter.mode,json.dumps(snapshot)))
            self.db.execute('INSERT INTO cell_cycle VALUES(?,?)',('default',run_id))
            self.db.executemany('INSERT INTO reservations VALUES(?,?)',[(p['brick_id'],run_id) for p in job['plan']['placements']])
            self.db.execute('COMMIT')
        except Exception:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
        return DurableRunner(self,run_id,session)

    def inspect(self,run_id):
        row=self.db.execute('SELECT * FROM runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:raise ValueError('unknown run ID')
        result=dict(row)
        for key in ('job','checkpoint','pending','snapshot'):
            result[key]=json.loads(result[key]) if result[key] is not None else None
        if result['pending'] is not None:
            result['status']='dispatch_unacknowledged'
        return result

    def resume_simulation(self,run_id,adapter):
        row=self.inspect(run_id)
        if adapter.mode!='simulation_only' or row['mode']!='simulation_only':
            raise ValueError('automatic restoration is available only for simulation checkpoints')
        if row['job'].get('execution_backend','acknowledgement_simulator')!='acknowledgement_simulator' or getattr(adapter,'backend',None)!='acknowledgement_simulator':
            raise ValueError('this backend requires scene reconciliation; automatic simulation resume refused')
        if row['pending'] is not None:
            raise ValueError('unacknowledged dispatched action requires reconciliation; replay refused')
        if row['status'] not in ('ready','running'):
            raise ValueError('stopped/completed runs cannot be restarted automatically')
        session=ExecutionSession(row['job'],adapter)
        for key,value in row['checkpoint'].items():setattr(session,key,set(value) if key=='available' else value)
        return DurableRunner(self,run_id,session)

    def restore_simulation_view(self,run_id):
        row=self.inspect(run_id)
        if row['mode']!='simulation_only':
            raise ValueError('hardware state requires live reconciliation, not a synthetic viewer restore')
        from execution import SimulatedAdapter
        session=ExecutionSession(row['job'],SimulatedAdapter())
        for key,value in row['checkpoint'].items():setattr(session,key,set(value) if key=='available' else value)
        if row['status']!='completed':session.status='stopped'
        if row['pending'] is not None:
            session.uncertain_brick=row['pending']['brick_id']
            session.available.discard(session.uncertain_brick)
        return session,row

    def save_validation(self,run_id,payload,result):
        self.inspect(run_id)
        encoded=json.dumps(payload,sort_keys=True)
        row=self.db.execute('SELECT payload FROM validations WHERE run_id=? AND observation_id=?',
                            (run_id,payload['observation_id'])).fetchone()
        if row is not None:
            if row['payload']!=encoded:raise ValueError('observation ID cannot be reused with changed data')
            return
        self.db.execute('INSERT INTO validations VALUES(?,?,?,?)',
                        (run_id,payload['observation_id'],encoded,json.dumps(result)))

    def latest_validation(self,run_id):
        row=self.db.execute('SELECT result FROM validations WHERE run_id=? ORDER BY rowid DESC LIMIT 1',(run_id,)).fetchone()
        return json.loads(row['result']) if row else None

    def latest_run_id(self):
        row=self.db.execute('SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
        if row is None:raise ValueError('journal has no runs')
        return row['run_id']


class DurableRunner:
    def __init__(self,journal,run_id,session):
        self.journal,self.run_id,self.session=journal,run_id,session

    def advance(self):
        session=self.session
        if session.status in ('completed','stopped'):return None
        command=session.job['commands'][session.cursor]
        db=self.journal.db
        try:
            db.execute('BEGIN IMMEDIATE')
            row=self.journal.inspect(self.run_id)
            if row['pending'] is not None or row['status'] not in ('ready','running') or row['checkpoint']!=checkpoint(session):
                raise ValueError('run changed or an action is pending; stale executor refused')
            db.execute('UPDATE runs SET pending=?,status=? WHERE run_id=?',
                       (json.dumps(command),'dispatching',self.run_id))
            db.execute('COMMIT')
        except Exception:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        # Deliberately outside the transaction: a crash here leaves a durable pending action.
        event=session.advance()
        try:
            db.execute('BEGIN IMMEDIATE')
            row=self.journal.inspect(self.run_id)
            if row['pending']['action_id']!=command['action_id']:
                raise ValueError('dispatch record mismatch')
            db.execute('UPDATE runs SET checkpoint=?,status=?,pending=NULL WHERE run_id=?',
                       (json.dumps(checkpoint(session)),session.status,self.run_id))
            db.execute('COMMIT')
        except Exception:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        return event

"""SQLite job database. The current checkpoint pointer is written only after verification."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    request TEXT,
    status TEXT NOT NULL,
    backend TEXT NOT NULL,
    created REAL NOT NULL,
    budget_worker_hours REAL NOT NULL,
    used_worker_hours REAL NOT NULL DEFAULT 0,
    provenance_json TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shards (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    spec_json TEXT NOT NULL,
    state TEXT NOT NULL,
    current_checkpoint_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE TABLE IF NOT EXISTS leases (
    id TEXT PRIMARY KEY,
    shard_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    backend TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    started REAL NOT NULL,
    leased_until REAL NOT NULL,
    heartbeat_at REAL NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    backend TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    status TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    shard_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    object_key TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    job_id TEXT,
    shard_id TEXT,
    payload_json TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self.con = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._serialize()

    def _serialize(self):
        names = (
            'event', 'create_job', 'job', 'jobs', 'shards', 'current_checkpoint', 'reap', 'claim',
            'lease_view', 'heartbeat', 'release', 'cancel', 'workers', 'pending_count',
            'active_leases', 'note_dispatch', 'dispatching_count',
        )
        for name in names:
            fn = getattr(self, name)

            def wrapped(*args, _fn=fn, **kwargs):
                with self._lock:
                    return _fn(*args, **kwargs)

            setattr(self, name, wrapped)

    def close(self):
        self.con.close()

    def _now(self):
        return float(self.clock())

    def event(self, kind, payload, job_id=None, shard_id=None):
        self.con.execute(
            'INSERT INTO events (ts, kind, job_id, shard_id, payload_json) VALUES (?,?,?,?,?)',
            (self._now(), kind, job_id, shard_id, json.dumps(payload, default=str)),
        )

    def create_job(self, shards, backend, provenance, budget_worker_hours, request='', max_attempts=3):
        now = self._now()
        job_id = uuid.uuid4().hex[:12]
        projected = 0.0
        for spec in shards:
            projected += float(spec.get('estimated_seconds') or 0) / 3600
        if projected > float(budget_worker_hours):
            raise ValueError(
                f'Predicted worker time {projected:.2f} h exceeds the budget of {budget_worker_hours} h. '
                'The prediction uses the observatory estimator.'
            )
        self.con.execute('BEGIN IMMEDIATE')
        try:
            self.con.execute(
                'INSERT INTO jobs (id, request, status, backend, created, budget_worker_hours, provenance_json) VALUES (?,?,?,?,?,?,?)',
                (job_id, request, 'queued', backend, now, float(budget_worker_hours), json.dumps(provenance)),
            )
            for index, spec in enumerate(shards):
                shard_id = uuid.uuid4().hex[:12]
                self.con.execute(
                    'INSERT INTO shards (id, job_id, idx, spec_json, state, max_attempts) VALUES (?,?,?,?,?,?)',
                    (shard_id, job_id, index, json.dumps(spec), 'pending', int(max_attempts)),
                )
            self.event('job_created', {'shards': len(shards), 'backend': backend, 'predicted_hours': projected}, job_id)
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return job_id

    def job(self, job_id):
        row = self.con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job(row, self.shards(job_id))

    def jobs(self):
        rows = self.con.execute('SELECT * FROM jobs ORDER BY created DESC').fetchall()
        return [_job(row, self.shards(row['id'])) for row in rows]

    def shards(self, job_id):
        rows = self.con.execute('SELECT * FROM shards WHERE job_id=? ORDER BY idx', (job_id,)).fetchall()
        return [_shard(row, self.current_checkpoint(row['id'])) for row in rows]

    def current_checkpoint(self, shard_id):
        row = self.con.execute(
            "SELECT * FROM checkpoints WHERE shard_id=? AND status='current' ORDER BY seq DESC LIMIT 1",
            (shard_id,),
        ).fetchone()
        return _checkpoint(row) if row else None

    def reap(self, grace):
        now = self._now()
        self.con.execute('BEGIN IMMEDIATE')
        try:
            expired = self.con.execute(
                """SELECT id, shard_id FROM leases
                   WHERE state='active' AND (leased_until < ? OR heartbeat_at + ? < ?)""",
                (now, grace, now),
            ).fetchall()
            for lease in expired:
                self.con.execute("UPDATE leases SET state='expired' WHERE id=?", (lease['id'],))
                shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
                if shard is None or shard['state'] not in ('leased', 'running'):
                    continue
                if int(shard['attempt']) >= int(shard['max_attempts']):
                    state = 'held'
                else:
                    state = 'pending'
                self.con.execute('UPDATE shards SET state=? WHERE id=?', (state, shard['id']))
                self.event('lease_expired', {'lease_id': lease['id'], 'shard_state': state}, shard['job_id'], shard['id'])
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return len(expired)

    def claim(self, worker_id, backend, host, lease_seconds, grace, budget_block=True):
        now = self._now()
        self.reap(grace)
        self.con.execute('BEGIN IMMEDIATE')
        try:
            row = self.con.execute(
                """SELECT s.* FROM shards s
                   JOIN jobs j ON j.id = s.job_id
                   WHERE s.state='pending' AND j.status IN ('queued','running') AND j.backend=?
                   ORDER BY j.created, s.idx LIMIT 1""",
                (backend,),
            ).fetchone()
            if row is None:
                self.con.execute('COMMIT')
                return None
            job = self.con.execute('SELECT * FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
            projected = float(job['used_worker_hours']) + lease_seconds / 3600
            if budget_block and projected > float(job['budget_worker_hours']):
                self.con.execute("UPDATE jobs SET status='held', message=? WHERE id=?", (
                    'Held: the next lease would exceed the worker-hour budget.', job['id']))
                self.con.execute("UPDATE shards SET state='held' WHERE job_id=? AND state='pending'", (job['id'],))
                self.event('budget_hold', {'projected_hours': projected}, job['id'], row['id'])
                self.con.execute('COMMIT')
                return None
            attempt = int(row['attempt']) + 1
            lease_id = uuid.uuid4().hex[:12]
            until = now + lease_seconds
            self.con.execute(
                'UPDATE shards SET state=?, attempt=? WHERE id=?',
                ('leased', attempt, row['id']),
            )
            self.con.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
            self.con.execute(
                '''INSERT INTO leases (id, shard_id, worker_id, backend, host, started, leased_until, heartbeat_at, state)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (lease_id, row['id'], worker_id, backend, host, now, until, now, 'active'),
            )
            self.con.execute(
                '''INSERT INTO workers (id, backend, first_seen, last_seen, status, host)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, status='running', host=excluded.host''',
                (worker_id, backend, now, now, 'running', host),
            )
            self.con.execute(
                """UPDATE workers SET status='joined', last_seen=?
                   WHERE id=(
                     SELECT id FROM workers WHERE backend=? AND status='dispatching'
                     ORDER BY first_seen LIMIT 1
                   )""",
                (now, backend),
            )
            self.event('claimed', {'lease_id': lease_id, 'worker_id': worker_id, 'until': until}, job['id'], row['id'])
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return self.lease_view(lease_id)

    def lease_view(self, lease_id):
        lease = self.con.execute('SELECT * FROM leases WHERE id=?', (lease_id,)).fetchone()
        if lease is None:
            raise KeyError(lease_id)
        shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
        job = self.con.execute('SELECT * FROM jobs WHERE id=?', (shard['job_id'],)).fetchone()
        return dict(
            lease_id=lease['id'],
            worker_id=lease['worker_id'],
            backend=lease['backend'],
            leased_until=lease['leased_until'],
            state=lease['state'],
            shard_id=shard['id'],
            job_id=job['id'],
            spec=json.loads(shard['spec_json']),
            checkpoint=self.current_checkpoint(shard['id']),
            cancel=job['status'] == 'cancelled',
        )

    def heartbeat(self, lease_id, worker_id, grace):
        now = self._now()
        lease = self._active_lease(lease_id, worker_id)
        if now > float(lease['leased_until']):
            self.reap(grace)
            raise PermissionError('lease deadline has passed')
        self.con.execute(
            "UPDATE leases SET heartbeat_at=? WHERE id=? AND state='active'",
            (now, lease_id),
        )
        self.con.execute("UPDATE shards SET state='running' WHERE id=? AND state='leased'", (lease['shard_id'],))
        job = self.con.execute(
            'SELECT j.status FROM jobs j JOIN shards s ON s.job_id=j.id WHERE s.id=?',
            (lease['shard_id'],),
        ).fetchone()
        return dict(ok=True, leased_until=lease['leased_until'], cancel=job['status'] == 'cancelled')

    def release(self, lease_id, worker_id, reason):
        now = self._now()
        if reason not in ('handoff', 'complete', 'failed', 'cancelled'):
            raise ValueError('unsupported release reason')
        self.con.execute('BEGIN IMMEDIATE')
        try:
            lease = self._active_lease(lease_id, worker_id)
            elapsed = max(0.0, now - float(lease['started'])) / 3600
            shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
            self.con.execute("UPDATE leases SET state='released' WHERE id=?", (lease_id,))
            self.con.execute(
                'UPDATE jobs SET used_worker_hours = used_worker_hours + ? WHERE id=?',
                (elapsed, shard['job_id']),
            )
            if reason == 'complete':
                self.con.execute("UPDATE shards SET state='complete' WHERE id=?", (shard['id'],))
            elif reason == 'failed':
                state = 'held' if int(shard['attempt']) >= int(shard['max_attempts']) else 'pending'
                self.con.execute('UPDATE shards SET state=? WHERE id=?', (state, shard['id']))
            elif reason == 'cancelled':
                self.con.execute("UPDATE shards SET state='cancelled' WHERE id=?", (shard['id'],))
            else:
                self.con.execute("UPDATE shards SET state='pending' WHERE id=?", (shard['id'],))
            self._refresh_job(shard['job_id'])
            self.event('released', {'lease_id': lease_id, 'reason': reason, 'hours': elapsed}, shard['job_id'], shard['id'])
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise

    def stage_and_verify(self, lease_id, worker_id, seq, sha256, size, object_key, store):
        """Upload is already in the store. This process recomputes SHA-256 before any pointer move."""
        with self._lock:
            lease = self._active_lease(lease_id, worker_id)
            shard_id = lease['shard_id']
            seq = int(seq)
            size = int(size)
            current = self.current_checkpoint(shard_id)
            expected = 1 if current is None else int(current['seq']) + 1
            if seq != expected:
                raise ValueError(f'checkpoint sequence {seq} does not follow {expected - 1}')
            checkpoint_id = uuid.uuid4().hex[:12]
            now = self._now()
            self.con.execute(
                '''INSERT INTO checkpoints (id, shard_id, seq, status, sha256, size, object_key, created)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (checkpoint_id, shard_id, seq, 'staged', sha256, size, object_key, now),
            )
            self.event('checkpoint_staged', {'seq': seq, 'object_key': object_key}, None, shard_id)
        ok = bool(store.verify(object_key, sha256, size))
        with self._lock:
            self.con.execute('BEGIN IMMEDIATE')
            try:
                current = self.current_checkpoint(shard_id)
                expected = 1 if current is None else int(current['seq']) + 1
                if not ok or seq != expected:
                    self.con.execute("UPDATE checkpoints SET status='rejected' WHERE id=?", (checkpoint_id,))
                    self.event('checkpoint_rejected', {'seq': seq, 'sha256': sha256, 'verified': ok}, None, shard_id)
                    self.con.execute('COMMIT')
                    return dict(status='rejected', checkpoint_id=checkpoint_id, current=self.current_checkpoint(shard_id))
                self.con.execute(
                    "UPDATE checkpoints SET status='verified' WHERE shard_id=? AND status='current'",
                    (shard_id,),
                )
                self.con.execute("UPDATE checkpoints SET status='current' WHERE id=?", (checkpoint_id,))
                self.con.execute(
                    'UPDATE shards SET current_checkpoint_id=? WHERE id=?',
                    (checkpoint_id, shard_id),
                )
                self.event('checkpoint_current', {'seq': seq, 'sha256': sha256}, None, shard_id)
                self.con.execute('COMMIT')
            except Exception:
                self.con.execute('ROLLBACK')
                raise
            return dict(status='current', checkpoint_id=checkpoint_id, current=self.current_checkpoint(shard_id))

    def cancel(self, job_id):
        now = self._now()
        self.con.execute('BEGIN IMMEDIATE')
        try:
            job = self.con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job is None:
                raise KeyError(job_id)
            self.con.execute("UPDATE jobs SET status='cancelled', message='Cancelled' WHERE id=?", (job_id,))
            self.con.execute(
                "UPDATE shards SET state='cancelled' WHERE job_id=? AND state IN ('pending','held')",
                (job_id,),
            )
            self.event('cancelled', {}, job_id)
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return self.job(job_id)

    def workers(self):
        rows = self.con.execute('SELECT * FROM workers ORDER BY last_seen DESC').fetchall()
        return [dict(row) for row in rows]

    def pending_count(self, backend):
        row = self.con.execute(
            """SELECT COUNT(*) AS n FROM shards s JOIN jobs j ON j.id=s.job_id
               WHERE s.state='pending' AND j.backend=? AND j.status IN ('queued','running')""",
            (backend,),
        ).fetchone()
        return int(row['n'])

    def active_leases(self, backend):
        row = self.con.execute(
            "SELECT COUNT(*) AS n FROM leases WHERE state='active' AND backend=?",
            (backend,),
        ).fetchone()
        return int(row['n'])

    def note_dispatch(self, backend, dispatch_id):
        now = self._now()
        self.con.execute(
            '''INSERT INTO workers (id, backend, first_seen, last_seen, status, host)
               VALUES (?,?,?,?,?,?)''',
            (dispatch_id, backend, now, now, 'dispatching', ''),
        )

    def dispatching_count(self, backend, stale_after):
        now = self._now()
        row = self.con.execute(
            """SELECT COUNT(*) AS n FROM workers
               WHERE backend=? AND status='dispatching' AND last_seen > ?""",
            (backend, now - stale_after),
        ).fetchone()
        return int(row['n'])

    def _refresh_job(self, job_id):
        rows = self.con.execute('SELECT state FROM shards WHERE job_id=?', (job_id,)).fetchall()
        states = {row['state'] for row in rows}
        job = self.con.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job['status'] == 'cancelled':
            return
        if states and states <= {'complete'}:
            self.con.execute("UPDATE jobs SET status='complete', message='Complete' WHERE id=?", (job_id,))
        elif 'held' in states and not ({'pending', 'leased', 'running'} & states):
            self.con.execute("UPDATE jobs SET status='held', message='Held for review' WHERE id=?", (job_id,))
        elif {'leased', 'running', 'pending'} & states:
            self.con.execute("UPDATE jobs SET status='running' WHERE id=? AND status!='held'", (job_id,))

    def _active_lease(self, lease_id, worker_id):
        lease = self.con.execute('SELECT * FROM leases WHERE id=?', (lease_id,)).fetchone()
        if lease is None or lease['state'] != 'active' or lease['worker_id'] != worker_id:
            raise PermissionError('lease is not active for this worker')
        return lease


def _job(row, shards):
    return dict(
        id=row['id'],
        request=row['request'],
        status=row['status'],
        backend=row['backend'],
        created=row['created'],
        budget_worker_hours=row['budget_worker_hours'],
        used_worker_hours=row['used_worker_hours'],
        provenance=json.loads(row['provenance_json']),
        message=row['message'],
        shards=shards,
    )


def _shard(row, checkpoint):
    return dict(
        id=row['id'],
        job_id=row['job_id'],
        idx=row['idx'],
        spec=json.loads(row['spec_json']),
        state=row['state'],
        attempt=row['attempt'],
        max_attempts=row['max_attempts'],
        current_checkpoint_id=row['current_checkpoint_id'],
        checkpoint=checkpoint,
    )


def _checkpoint(row):
    return dict(
        id=row['id'],
        shard_id=row['shard_id'],
        seq=row['seq'],
        status=row['status'],
        sha256=row['sha256'],
        size=row['size'],
        object_key=row['object_key'],
        created=row['created'],
    )

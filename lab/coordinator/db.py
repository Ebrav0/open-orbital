"""SQLite job database. The current checkpoint pointer is written only after verification."""
import hashlib
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
    failures INTEGER NOT NULL DEFAULT 0,
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
        self._migrate()
        self._lock = threading.RLock()
        self._serialize()

    def _serialize(self):
        names = (
            'event', 'events', 'create_job', 'job', 'jobs', 'shards', 'current_checkpoint', 'reap', 'claim',
            'lease_view', 'heartbeat', 'release', 'cancel', 'workers', 'pending_count',
            'active_leases', 'note_dispatch', 'dispatching_count', 'pending_commits',
            'create_experiment', 'save_result',
            'save_conversation', 'get_conversation', 'conversation_ids', 'experiment',
            'experiments', 'manifest', 'results_for_experiment', 'save_analysis',
            'analyses', 'pause_experiment', 'resume_experiment',
        )
        for name in names:
            fn = getattr(self, name)

            def wrapped(*args, _fn=fn, **kwargs):
                with self._lock:
                    return _fn(*args, **kwargs)

            setattr(self, name, wrapped)

    def _migrate(self):
        columns = {row['name'] for row in self.con.execute('PRAGMA table_info(jobs)')}
        for name, sql_type in (('experiment_id', 'TEXT'), ('manifest_revision', 'INTEGER'), ('manifest_sha256', 'TEXT'), ('git_commit', 'TEXT')):
            if name not in columns:
                self.con.execute(f'ALTER TABLE jobs ADD COLUMN {name} {sql_type}')
        shard_columns = {row['name'] for row in self.con.execute('PRAGMA table_info(shards)')}
        if 'failures' not in shard_columns:
            self.con.execute('ALTER TABLE shards ADD COLUMN failures INTEGER NOT NULL DEFAULT 0')
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, request TEXT NOT NULL, plan_json TEXT NOT NULL, decision_json TEXT NOT NULL, dialogue_json TEXT NOT NULL, current_revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id));
        CREATE TABLE IF NOT EXISTS manifests (experiment_id TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL, object_key TEXT NOT NULL, manifest_json TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(experiment_id, revision), FOREIGN KEY(experiment_id) REFERENCES experiments(id));
        CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, status TEXT NOT NULL, state_json TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS results (shard_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, experiment_id TEXT, object_key TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, metadata_json TEXT NOT NULL, created REAL NOT NULL, FOREIGN KEY(shard_id) REFERENCES shards(id));
        CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, created REAL NOT NULL, model TEXT NOT NULL, input_sha256 TEXT NOT NULL, text TEXT NOT NULL, FOREIGN KEY(experiment_id) REFERENCES experiments(id));
        CREATE INDEX IF NOT EXISTS idx_manifests_sha ON manifests(experiment_id, sha256);
        CREATE INDEX IF NOT EXISTS idx_results_experiment ON results(experiment_id);
        """)

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

    def events(self, job_id=None, limit=100):
        limit = min(1000, max(1, int(limit)))
        if job_id is None:
            rows = self.con.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        else:
            rows = self.con.execute('SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?', (job_id, limit)).fetchall()
        return [{'id': row['id'], 'ts': row['ts'], 'kind': row['kind'], 'job_id': row['job_id'],
                 'shard_id': row['shard_id'], 'payload': json.loads(row['payload_json'])} for row in rows]

    def save_conversation(self, conversation_id, state, status='waiting'):
        now = self._now()
        raw = json.dumps(state, sort_keys=True, ensure_ascii=False)
        self.con.execute("INSERT INTO conversations (id,status,state_json,created,updated) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,state_json=excluded.state_json,updated=excluded.updated", (conversation_id, status, raw, now, now))
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id):
        row = self.con.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return {'id': row['id'], 'status': row['status'], 'state': json.loads(row['state_json']), 'created': row['created'], 'updated': row['updated']}

    def conversation_ids(self):
        return [dict(row) for row in self.con.execute('SELECT id,status,created,updated FROM conversations ORDER BY updated DESC')]

    def create_experiment(self, experiment_id, job_id, shards, backend, manifest, plan, decisions, dialogue, request, budget_worker_hours, max_attempts=3, manifest_key='', resource_estimate=None):
        now = self._now()
        projected = (float(resource_estimate.get('total_worker_hours')) if resource_estimate else
                     sum(float(spec.get('estimated_seconds') or 0) for spec in shards) / 3600)
        if not shards:
            raise ValueError('An experiment must contain at least one run')
        if projected > float(budget_worker_hours):
            raise ValueError(f'Predicted worker time {projected:.2f} h exceeds the budget of {budget_worker_hours} h')
        digest = _manifest_sha256(manifest)
        source = manifest.get('source') or {}
        commit = str(source.get('git_commit') or '')
        manifest_raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.con.execute('BEGIN IMMEDIATE')
        try:
            self.con.execute('INSERT INTO jobs (id,request,status,backend,created,budget_worker_hours,provenance_json,experiment_id,manifest_revision,manifest_sha256,git_commit) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (job_id, request, 'queued', backend, now, float(budget_worker_hours), json.dumps(manifest.get('provenance') or {}), experiment_id, 1, digest, commit))
            for index, spec in enumerate(shards):
                shard_id = uuid.uuid4().hex[:12]
                self.con.execute('INSERT INTO shards (id,job_id,idx,spec_json,state,max_attempts) VALUES (?,?,?,?,?,?)', (shard_id, job_id, index, json.dumps(spec, sort_keys=True), 'pending', int(max_attempts)))
            self.con.execute('INSERT INTO experiments (id,job_id,status,request,plan_json,decision_json,dialogue_json,current_revision,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)', (experiment_id, job_id, 'queued', request, json.dumps(plan, sort_keys=True), json.dumps(decisions, sort_keys=True), json.dumps(dialogue, sort_keys=True), 1, now, now))
            self.con.execute('INSERT INTO manifests (experiment_id,revision,sha256,object_key,manifest_json,created) VALUES (?,?,?,?,?,?)', (experiment_id, 1, digest, manifest_key, manifest_raw, now))
            self.event('experiment_frozen', {'revision': 1, 'sha256': digest, 'runs': len(shards)}, job_id)
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return self.experiment(experiment_id)

    def validate_experiment_revision(self, experiment_id, projected_worker_hours, budget_worker_hours):
        row = self.con.execute('SELECT job_id,current_revision FROM experiments WHERE id=?', (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        job = self.con.execute('SELECT status FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        if job is None or job['status'] not in ('complete', 'cancelled', 'held'):
            raise ValueError('Stop or finish the current revision before creating another; use lab cancel and wait for active workers to release their leases.')
        active = self.con.execute("SELECT COUNT(*) FROM leases WHERE state='active' AND shard_id IN (SELECT id FROM shards WHERE job_id=?)", (row['job_id'],)).fetchone()[0]
        if active:
            raise ValueError('The current revision still has active worker leases; wait for them to checkpoint and release before revising.')
        used = float(self.con.execute('SELECT COALESCE(SUM(used_worker_hours),0) FROM jobs WHERE experiment_id=?', (experiment_id,)).fetchone()[0])
        available = max(0.0, float(budget_worker_hours) - used)
        projected = float(projected_worker_hours)
        if projected > available:
            raise ValueError(f'Revision projects {projected:.2f} worker-hours but only {available:.2f} remain in the {float(budget_worker_hours):.2f} h experiment budget.')
        return {'revision': int(row['current_revision']) + 1, 'used_worker_hours': used, 'remaining_worker_hours': available}

    def create_experiment_revision(self, experiment_id, job_id, shards, backend, manifest, plan, decisions, dialogue, request, budget_worker_hours, max_attempts=3, manifest_key='', resource_estimate=None):
        if not shards:
            raise ValueError('An experiment revision must contain at least one run')
        projected = float(resource_estimate.get('total_worker_hours')) if resource_estimate else sum(float(spec.get('estimated_seconds') or 0) for spec in shards) / 3600
        digest = _manifest_sha256(manifest)
        manifest_raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        source = manifest.get('source') or {}
        commit = str(source.get('git_commit') or '')
        now = self._now()
        self.con.execute('BEGIN IMMEDIATE')
        try:
            current = self.con.execute('SELECT job_id,current_revision FROM experiments WHERE id=?', (experiment_id,)).fetchone()
            if current is None:
                raise KeyError(experiment_id)
            old_job = self.con.execute('SELECT status FROM jobs WHERE id=?', (current['job_id'],)).fetchone()
            if old_job is None or old_job['status'] not in ('complete', 'cancelled', 'held'):
                raise ValueError('Stop or finish the current revision before creating another; use lab cancel and wait for active workers to release their leases.')
            active = self.con.execute("SELECT COUNT(*) FROM leases WHERE state='active' AND shard_id IN (SELECT id FROM shards WHERE job_id=?)", (current['job_id'],)).fetchone()[0]
            if active:
                raise ValueError('The current revision still has active worker leases; wait for them to checkpoint and release before revising.')
            revision = int(current['current_revision']) + 1
            if int(manifest.get('revision') or 0) != revision:
                raise ValueError('Manifest revision does not follow the current experiment revision')
            used = float(self.con.execute('SELECT COALESCE(SUM(used_worker_hours),0) FROM jobs WHERE experiment_id=?', (experiment_id,)).fetchone()[0])
            remaining = max(0.0, float(budget_worker_hours) - used)
            if projected > remaining:
                raise ValueError(f'Revision projects {projected:.2f} worker-hours but only {remaining:.2f} remain in the experiment budget.')
            self.con.execute('INSERT INTO jobs (id,request,status,backend,created,budget_worker_hours,provenance_json,experiment_id,manifest_revision,manifest_sha256,git_commit) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (job_id, request, 'queued', backend, now, remaining, json.dumps(manifest.get('provenance') or {}), experiment_id, revision, digest, commit))
            for index, spec in enumerate(shards):
                shard_id = uuid.uuid4().hex[:12]
                self.con.execute('INSERT INTO shards (id,job_id,idx,spec_json,state,max_attempts) VALUES (?,?,?,?,?,?)', (shard_id, job_id, index, json.dumps(spec, sort_keys=True), 'pending', int(max_attempts)))
            self.con.execute('INSERT INTO manifests (experiment_id,revision,sha256,object_key,manifest_json,created) VALUES (?,?,?,?,?,?)', (experiment_id, revision, digest, manifest_key, manifest_raw, now))
            self.con.execute('UPDATE experiments SET job_id=?,current_revision=?,request=?,plan_json=?,decision_json=?,dialogue_json=?,status=?,updated=? WHERE id=?', (job_id, revision, request, json.dumps(plan, sort_keys=True), json.dumps(decisions, sort_keys=True), json.dumps(dialogue, sort_keys=True), 'queued', now, experiment_id))
            self.event('experiment_revision_frozen', {'revision': revision, 'sha256': digest, 'runs': len(shards), 'prior_worker_hours': used}, job_id)
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return self.experiment(experiment_id)

    def experiment(self, experiment_id):
        row = self.con.execute('SELECT * FROM experiments WHERE id=?', (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        job = self.job(row['job_id'])
        counts = {}
        for shard in job['shards']:
            counts[shard['state']] = counts.get(shard['state'], 0) + 1
        return {'id': row['id'], 'job_id': row['job_id'], 'status': row['status'], 'request': row['request'], 'plan': json.loads(row['plan_json']), 'decisions': json.loads(row['decision_json']), 'dialogue': json.loads(row['dialogue_json']), 'current_revision': row['current_revision'], 'created': row['created'], 'updated': row['updated'], 'job': job, 'run_count': len(job['shards']), 'counts': counts, 'manifest': self.manifest(row['id'], row['current_revision'])}

    def experiments(self):
        rows = self.con.execute('SELECT id FROM experiments ORDER BY created DESC').fetchall()
        return [self.experiment(row['id']) for row in rows]

    def manifest(self, experiment_id, revision=None):
        if revision is None:
            row = self.con.execute('SELECT * FROM manifests WHERE experiment_id=? ORDER BY revision DESC LIMIT 1', (experiment_id,)).fetchone()
        else:
            row = self.con.execute('SELECT * FROM manifests WHERE experiment_id=? AND revision=?', (experiment_id, int(revision))).fetchone()
        if row is None:
            raise KeyError(f'{experiment_id} manifest revision {revision}')
        return {'revision': row['revision'], 'sha256': row['sha256'], 'object_key': row['object_key'], 'manifest': json.loads(row['manifest_json']), 'created': row['created']}

    def save_result(self, lease_id, worker_id, object_key, sha256, size, metadata, store):
        size = int(size)
        if size <= 0 or len(str(sha256)) != 64:
            raise ValueError('Result size and SHA-256 are invalid')
        if not store.verify(object_key, sha256, size):
            raise ValueError('Uploaded result failed SHA-256 or size verification')
        with self._lock:
            lease = self._active_lease(lease_id, worker_id)
            shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
            job = self.con.execute('SELECT * FROM jobs WHERE id=?', (shard['job_id'],)).fetchone()
            existing = self.con.execute('SELECT * FROM results WHERE shard_id=?', (shard['id'],)).fetchone()
            if existing:
                if existing['sha256'] == sha256 and existing['object_key'] == object_key:
                    return {'status': 'verified', 'sha256': sha256, 'idempotent': True}
                raise ValueError('A different final result is already recorded for this run')
            safe_meta = json.loads(json.dumps(metadata or {}))
            if not isinstance(safe_meta, dict):
                raise ValueError('Result metadata must be an object')
            for log in safe_meta.get('logs', []):
                if not store.verify(log.get('object_key', ''), log.get('sha256', ''), log.get('size')):
                    raise ValueError('Uploaded log failed SHA-256 or size verification')
            if len(json.dumps(safe_meta)) > 100000:
                raise ValueError('Result metadata is too large')
            self.con.execute('INSERT INTO results (shard_id,job_id,experiment_id,object_key,sha256,size,metadata_json,created) VALUES (?,?,?,?,?,?,?,?)', (shard['id'], job['id'], job['experiment_id'], object_key, sha256, size, json.dumps(safe_meta, sort_keys=True), self._now()))
            self.event('result_verified', {'sha256': sha256, 'size': size, 'object_key': object_key}, job['id'], shard['id'])
            return {'status': 'verified', 'sha256': sha256, 'idempotent': False}

    def results_for_experiment(self, experiment_id):
        rows = self.con.execute('''SELECT r.* FROM results r JOIN experiments e ON e.id=r.experiment_id
                                   WHERE r.experiment_id=? AND r.job_id=e.job_id ORDER BY r.created''', (experiment_id,)).fetchall()
        return [{'shard_id': r['shard_id'], 'job_id': r['job_id'], 'object_key': r['object_key'], 'sha256': r['sha256'], 'size': r['size'], 'metadata': json.loads(r['metadata_json']), 'created': r['created']} for r in rows]

    def save_analysis(self, analysis_id, experiment_id, model, input_sha256, text):
        self.con.execute('INSERT INTO analyses (id,experiment_id,created,model,input_sha256,text) VALUES (?,?,?,?,?,?)', (analysis_id, experiment_id, self._now(), model, input_sha256, text))
        return analysis_id

    def analyses(self, experiment_id):
        return [dict(row) for row in self.con.execute('SELECT * FROM analyses WHERE experiment_id=? ORDER BY created', (experiment_id,)).fetchall()]

    def pause_experiment(self, experiment_id):
        row = self.con.execute('SELECT job_id FROM experiments WHERE id=?', (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        self.con.execute("UPDATE jobs SET status='paused',message='Paused by user' WHERE id=? AND status!='complete'", (row['job_id'],))
        self.con.execute("UPDATE experiments SET status='paused',updated=? WHERE id=?", (self._now(), experiment_id))
        return self.experiment(experiment_id)

    def resume_experiment(self, experiment_id):
        row = self.con.execute('SELECT job_id FROM experiments WHERE id=?', (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        self.con.execute("UPDATE jobs SET status='running',message='' WHERE id=? AND status='paused'", (row['job_id'],))
        self._refresh_job(row['job_id'])
        return self.experiment(experiment_id)

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
                """SELECT id, shard_id, started, leased_until FROM leases
                   WHERE state='active' AND (leased_until < ? OR heartbeat_at + ? < ?)""",
                (now, grace, now),
            ).fetchall()
            for lease in expired:
                self.con.execute("UPDATE leases SET state='expired' WHERE id=?", (lease['id'],))
                shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
                if shard is None or shard['state'] not in ('leased', 'running'):
                    continue
                elapsed = max(0.0, min(now - float(lease['started']), float(lease['leased_until']) - float(lease['started']))) / 3600
                self.con.execute('UPDATE jobs SET used_worker_hours=used_worker_hours+? WHERE id=?', (elapsed, shard['job_id']))
                failures = int(shard['failures']) + 1
                state = 'held' if failures >= int(shard['max_attempts']) else 'pending'
                self.con.execute('UPDATE shards SET state=?,failures=? WHERE id=?', (state, failures, shard['id']))
                self.event('lease_expired', {'lease_id': lease['id'], 'shard_state': state}, shard['job_id'], shard['id'])
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return len(expired)

    def claim(self, worker_id, backend, host, lease_seconds, grace, budget_block=True, expected_commit=None, drain_margin_seconds=0):
        now = self._now()
        self.reap(grace)
        self.con.execute('BEGIN IMMEDIATE')
        try:
            row = self.con.execute(
                """SELECT s.* FROM shards s
                   JOIN jobs j ON j.id = s.job_id
                   WHERE s.state='pending' AND j.status IN ('queued','running') AND j.backend=?
                     AND (? IS NULL OR j.git_commit=?)
                   ORDER BY j.created, s.idx LIMIT 1""",
                (backend, expected_commit, expected_commit),
            ).fetchone()
            if row is None:
                self.con.execute('COMMIT')
                return None
            job = self.con.execute('SELECT * FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
            lease_duration = int(lease_seconds)
            if budget_block:
                active = self.con.execute("SELECT started,leased_until FROM leases WHERE state='active' AND shard_id IN (SELECT id FROM shards WHERE job_id=?)", (job['id'],)).fetchall()
                reserved = sum(max(0.0, float(item['leased_until']) - float(item['started'])) for item in active)
                available = (float(job['budget_worker_hours']) - float(job['used_worker_hours'])) * 3600 - reserved
                if available <= int(drain_margin_seconds) + 30:
                    self.con.execute("UPDATE jobs SET status='held',message='Held: insufficient worker-hour budget remains for another safe lease.' WHERE id=?", (job['id'],))
                    self.con.execute("UPDATE shards SET state='held' WHERE job_id=? AND state='pending'", (job['id'],))
                    self.event('budget_hold', {'available_worker_seconds': max(0.0, available), 'reserved_worker_seconds': reserved}, job['id'], row['id'])
                    self.con.execute('COMMIT')
                    return None
                lease_duration = min(lease_duration, int(available))
            attempt = int(row['attempt']) + 1
            lease_id = uuid.uuid4().hex[:12]
            until = now + lease_duration
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
        manifest_ref = None
        run_metadata = {}
        if job['experiment_id']:
            manifest_ref = self.manifest(job['experiment_id'], job['manifest_revision'])
            runs = manifest_ref['manifest'].get('runs', [])
            if int(shard['idx']) < len(runs):
                run_metadata = runs[int(shard['idx'])]
        return dict(
            lease_id=lease['id'], worker_id=lease['worker_id'], backend=lease['backend'],
            leased_until=lease['leased_until'], state=lease['state'], shard_id=shard['id'],
            job_id=job['id'], spec=json.loads(shard['spec_json']),
            checkpoint=self.current_checkpoint(shard['id']), cancel=job['status'] == 'cancelled',
            experiment_id=job['experiment_id'], manifest_revision=job['manifest_revision'],
            manifest_sha256=job['manifest_sha256'], git_commit=job['git_commit'],
            manifest_object_key=(manifest_ref['object_key'] if manifest_ref else ''),
            run_index=int(shard['idx']), run_metadata=run_metadata,
            generation=int(shard['attempt']), failures=int(shard['failures']),
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
        return dict(ok=True, leased_until=lease['leased_until'], cancel=job['status'] == 'cancelled', pause=job['status'] == 'paused')

    def release(self, lease_id, worker_id, reason):
        now = self._now()
        if reason not in ('handoff', 'complete', 'failed', 'cancelled'):
            raise ValueError('unsupported release reason')
        self.con.execute('BEGIN IMMEDIATE')
        try:
            lease = self._active_lease(lease_id, worker_id)
            elapsed = max(0.0, min(now - float(lease['started']), float(lease['leased_until']) - float(lease['started']))) / 3600
            shard = self.con.execute('SELECT * FROM shards WHERE id=?', (lease['shard_id'],)).fetchone()
            self.con.execute("UPDATE leases SET state='released' WHERE id=?", (lease_id,))
            self.con.execute(
                'UPDATE jobs SET used_worker_hours = used_worker_hours + ? WHERE id=?',
                (elapsed, shard['job_id']),
            )
            if reason == 'complete':
                job_for_result = self.con.execute('SELECT experiment_id FROM jobs WHERE id=?', (shard['job_id'],)).fetchone()
                if job_for_result['experiment_id'] and not self.con.execute('SELECT 1 FROM results WHERE shard_id=?', (shard['id'],)).fetchone():
                    raise ValueError('Experiment run cannot complete before a verified final result is recorded')
                self.con.execute("UPDATE shards SET state='complete' WHERE id=?", (shard['id'],))
            elif reason == 'failed':
                failures = int(shard['failures']) + 1
                state = 'held' if failures >= int(shard['max_attempts']) else 'pending'
                self.con.execute('UPDATE shards SET state=?,failures=? WHERE id=?', (state, failures, shard['id']))
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

    def pending_commits(self, backend):
        rows = self.con.execute(
            """SELECT COALESCE(j.git_commit,'') AS git_commit, COUNT(*) AS pending
               FROM shards s JOIN jobs j ON j.id=s.job_id
               WHERE s.state='pending' AND j.status IN ('queued','running') AND j.backend=?
               GROUP BY COALESCE(j.git_commit,'') ORDER BY MIN(j.created)""",
            (backend,),
        ).fetchall()
        return [{'git_commit': row['git_commit'], 'pending': int(row['pending'])} for row in rows]

    def _refresh_job(self, job_id):
        rows = self.con.execute('SELECT state FROM shards WHERE job_id=?', (job_id,)).fetchall()
        states = {row['state'] for row in rows}
        job = self.con.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job['status'] in ('cancelled', 'paused'):
            return
        if states and states <= {'complete'}:
            self.con.execute("UPDATE jobs SET status='complete', message='Complete' WHERE id=?", (job_id,))
        elif 'held' in states and not ({'pending', 'leased', 'running'} & states):
            self.con.execute("UPDATE jobs SET status='held', message='Held for review' WHERE id=?", (job_id,))
        elif {'leased', 'running', 'pending'} & states:
            self.con.execute("UPDATE jobs SET status='running' WHERE id=? AND status!='held'", (job_id,))
        current = self.con.execute('SELECT experiment_id,status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if current and current['experiment_id']:
            self.con.execute('UPDATE experiments SET status=?,updated=? WHERE id=? AND job_id=?', (current['status'], self._now(), current['experiment_id'], job_id))

    def _active_lease(self, lease_id, worker_id):
        lease = self.con.execute('SELECT * FROM leases WHERE id=?', (lease_id,)).fetchone()
        if lease is None or lease['state'] != 'active' or lease['worker_id'] != worker_id:
            raise PermissionError('lease is not active for this worker')
        return lease


def _manifest_sha256(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('A frozen manifest object is required')
    document = dict(manifest)
    digest = str(document.pop('sha256', '') or '')
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if len(digest) != 64 or hashlib.sha256(canonical).hexdigest() != digest:
        raise ValueError('Frozen manifest content does not match its SHA-256')
    return digest


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
        experiment_id=row['experiment_id'] if 'experiment_id' in row.keys() else None,
        manifest_revision=row['manifest_revision'] if 'manifest_revision' in row.keys() else None,
        manifest_sha256=row['manifest_sha256'] if 'manifest_sha256' in row.keys() else None,
        git_commit=row['git_commit'] if 'git_commit' in row.keys() else None,
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
        failures=row['failures'] if 'failures' in row.keys() else 0,
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

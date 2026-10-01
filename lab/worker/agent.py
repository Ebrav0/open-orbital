"""Claim one shard, integrate with worker.py, and publish checkpoints through the store."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from lab.paths import OBSERVATORY, OPENMP
from lab.storage.memory import file_sha256
from lab.worker.bundle import pack, unpack


class WorkerError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=3600) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[:500]
            raise WorkerError(f'{exc.code} {detail}') from exc


def run_once(cfg, store, backend='local', worker_id=None, popen=None, sleep=time.sleep):
    if not cfg.worker_token:
        raise WorkerError('LAB_WORKER_TOKEN is not set in work/lab-data/lab.env')
    url = os.environ.get('LAB_URL') or _local_url(cfg)
    client = Client(url, cfg.worker_token)
    worker_id = worker_id or f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'
    claimed = client.call('POST', '/api/claim', {'worker_id': worker_id, 'backend': backend, 'host': socket.gethostname()})
    claim = claimed.get('claim')
    if not claim:
        return 0
    run_dir = cfg.scratch / 'runs' / claim['shard_id']
    if run_dir.exists():
        for child in run_dir.iterdir():
            if child.is_file():
                child.unlink()
    else:
        run_dir.mkdir(parents=True)
    checkpoint = claim.get('checkpoint')
    if checkpoint:
        archive = run_dir / 'resume.tar.gz'
        store.fetch(checkpoint['object_key'], archive)
        unpack(archive, run_dir)
    else:
        (run_dir / 'config.json').write_text(json.dumps(claim['spec']))
        (run_dir / 'control.json').write_text(json.dumps({'action': 'run'}))
    proc = _spawn(run_dir, claim['spec'], popen or subprocess.Popen)
    try:
        _watch(cfg, store, client, claim, worker_id, run_dir, proc, sleep)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def _watch(cfg, store, client, claim, worker_id, run_dir, proc, sleep):
    deadline = float(claim['leased_until']) - cfg.drain_margin_seconds
    next_upload = time.time() + cfg.checkpoint_interval_seconds
    published = 0
    while True:
        beat = client.call('POST', '/api/heartbeat', {'lease_id': claim['lease_id'], 'worker_id': worker_id})
        if beat.get('cancel'):
            _pause(run_dir)
            _publish(cfg, store, client, claim, worker_id, run_dir, published)
            client.call('POST', '/api/release', {'lease_id': claim['lease_id'], 'worker_id': worker_id, 'reason': 'cancelled'})
            return
        phase = _phase(run_dir)
        now = time.time()
        if phase == 'complete':
            published = _publish(cfg, store, client, claim, worker_id, run_dir, published)
            client.call('POST', '/api/release', {'lease_id': claim['lease_id'], 'worker_id': worker_id, 'reason': 'complete'})
            return
        if phase == 'error':
            client.call('POST', '/api/release', {'lease_id': claim['lease_id'], 'worker_id': worker_id, 'reason': 'failed'})
            return
        if now >= deadline or (proc.poll() is not None and phase not in ('complete',)):
            _pause(run_dir)
            _wait_quiet(run_dir, proc)
            published = _publish(cfg, store, client, claim, worker_id, run_dir, published)
            client.call('POST', '/api/release', {'lease_id': claim['lease_id'], 'worker_id': worker_id, 'reason': 'handoff'})
            return
        if now >= next_upload and (run_dir / 'checkpoint.json').is_file():
            published = _publish(cfg, store, client, claim, worker_id, run_dir, published)
            next_upload = now + cfg.checkpoint_interval_seconds
        sleep(2)


def _publish(cfg, store, client, claim, worker_id, run_dir, published):
    if not (run_dir / 'checkpoint.json').is_file():
        return published
    seq = published + 1
    archive = cfg.scratch / f"{claim['shard_id']}-{seq:06d}.tar.gz"
    pack(run_dir, archive)
    key = f"jobs/{claim['job_id']}/shards/{claim['shard_id']}/{seq:06d}.tar.gz"
    store.put(key, archive)
    digest = file_sha256(archive)
    result = client.call('POST', '/api/checkpoints', {
        'lease_id': claim['lease_id'],
        'worker_id': worker_id,
        'seq': seq,
        'sha256': digest,
        'size': archive.stat().st_size,
        'object_key': key,
    })
    if result.get('status') != 'current':
        raise WorkerError(f'checkpoint {seq} was not accepted: {result.get("status")}')
    return seq


def _spawn(run_dir, spec, popen):
    env = os.environ.copy()
    pythonpath = [str(OBSERVATORY)]
    if OPENMP.is_dir():
        pythonpath.append(str(OPENMP))
    if env.get('PYTHONPATH'):
        pythonpath.append(env['PYTHONPATH'])
    env['PYTHONPATH'] = os.pathsep.join(pythonpath)
    env['OMP_NUM_THREADS'] = str(spec.get('threads') or 1)
    return popen(
        [sys.executable, str(OBSERVATORY / 'worker.py'), str(run_dir)],
        cwd=str(OBSERVATORY),
        env=env,
    )


def _pause(run_dir):
    path = Path(run_dir) / 'control.json'
    path.write_text(json.dumps({'action': 'pause'}))


def _phase(run_dir):
    path = Path(run_dir) / 'status.json'
    if not path.is_file():
        return ''
    try:
        return json.loads(path.read_text()).get('phase') or ''
    except json.JSONDecodeError:
        return ''


def _wait_quiet(run_dir, proc):
    for _ in range(60):
        if _phase(run_dir) in ('paused', 'interrupted', 'complete', 'error'):
            return
        if proc.poll() is not None:
            return
        time.sleep(0.5)


def _local_url(cfg):
    return f'http://{cfg.host}:{cfg.port}'

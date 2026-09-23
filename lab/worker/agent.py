"""Claim one shard, integrate with worker.py, and publish checkpoints through the store."""
import json
import os
import socket
import shutil
import hashlib
import tarfile
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from lab.paths import OBSERVATORY, OPENMP
from lab.storage.memory import file_sha256
from lab.worker.bundle import pack, pack_result, unpack


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
    expected_commit = os.environ.get('LAB_EXPECTED_COMMIT') or None
    claimed = client.call('POST', '/api/claim', {'worker_id': worker_id, 'backend': backend, 'host': socket.gethostname(), 'expected_commit': expected_commit})
    claim = claimed.get('claim')
    if not claim:
        return 0
    if backend == 'github' and claim.get('git_commit'):
        actual = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(OBSERVATORY.parent.parent), capture_output=True, text=True, check=True).stdout.strip()
        if actual != claim['git_commit']:
            raise WorkerError(f'checked out commit {actual} does not match leased experiment commit {claim["git_commit"]}')
    run_dir = cfg.scratch / 'runs' / claim['shard_id']
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    checkpoint = claim.get('checkpoint')
    if checkpoint:
        archive = cfg.scratch / f"{claim['shard_id']}-resume.tar.gz"
        store.fetch(checkpoint['object_key'], archive)
        if archive.stat().st_size != int(checkpoint['size']) or file_sha256(archive) != checkpoint['sha256']:
            raise WorkerError('downloaded resume checkpoint failed SHA-256 or size verification')
        unpack(archive, run_dir)
        archive.unlink(missing_ok=True)
    else:
        (run_dir / 'config.json').write_text(json.dumps(claim['spec']))
        (run_dir / 'control.json').write_text(json.dumps({'action': 'run'}))
    if claim.get('manifest_object_key'):
        manifest_path = run_dir / 'experiment-manifest.json'
        store.fetch(claim['manifest_object_key'], manifest_path)
        if not _valid_manifest(manifest_path, claim):
            raise WorkerError('frozen experiment manifest hash or run config does not match the lease')
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
    checkpoint = claim.get('checkpoint') or {}
    published = int(checkpoint.get('seq') or 0)
    while True:
        beat = client.call('POST', '/api/heartbeat', {'lease_id': claim['lease_id'], 'worker_id': worker_id})
        if beat.get('cancel') or beat.get('pause'):
            _pause(run_dir)
            _wait_quiet(run_dir, proc)
            _publish(cfg, store, client, claim, worker_id, run_dir, published)
            reason = 'cancelled' if beat.get('cancel') else 'handoff'
            client.call('POST', '/api/release', {'lease_id': claim['lease_id'], 'worker_id': worker_id, 'reason': reason})
            return
        phase = _phase(run_dir)
        now = time.time()
        if phase == 'complete':
            if proc.poll() is None:
                proc.wait(timeout=30)
            published = _publish(cfg, store, client, claim, worker_id, run_dir, published)
            if claim.get('experiment_id'):
                result = cfg.scratch / f"{claim['shard_id']}-final.tar.gz"
                pack_result(run_dir, result)
                digest = file_sha256(result)
                key = f"experiments/{claim['experiment_id']}/jobs/{claim['job_id']}/results/{claim['shard_id']}-{digest}.tar.gz"
                store.put(key, result)
                metadata = _result_metadata(run_dir)
                metadata['run_metadata'] = claim.get('run_metadata') or {}
                log_path = run_dir / 'worker.log'
                if log_path.is_file() and log_path.stat().st_size:
                    log_sha = file_sha256(log_path)
                    log_key = f"experiments/{claim['experiment_id']}/jobs/{claim['job_id']}/logs/{claim['shard_id']}/{log_sha}.log"
                    store.put(log_key, log_path)
                    if not store.verify(log_key, log_sha, log_path.stat().st_size):
                        raise WorkerError('uploaded worker log failed SHA-256 verification')
                    metadata['logs'] = [{'object_key': log_key, 'sha256': log_sha, 'size': log_path.stat().st_size}]
                client.call('POST', '/api/results', {
                    'lease_id': claim['lease_id'], 'worker_id': worker_id, 'object_key': key,
                    'sha256': digest, 'size': result.stat().st_size, 'metadata': metadata,
                })
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
    if claim.get('experiment_id'):
        key = f"experiments/{claim['experiment_id']}/jobs/{claim['job_id']}/checkpoints/{claim['shard_id']}/{seq:06d}.tar.gz"
    else:
        key = f"jobs/{claim['job_id']}/shards/{claim['shard_id']}/checkpoints/{seq:06d}.tar.gz"
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
    prefix = key.rsplit('/', 1)[0] + '/'
    store.prune(prefix, int(getattr(cfg, 'checkpoint_retention', 3)))
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
    command = [sys.executable, str(OBSERVATORY / 'worker.py'), str(run_dir)]
    if popen is subprocess.Popen:
        log = (Path(run_dir) / 'worker.log').open('ab')
        try:
            return popen(command, cwd=str(OBSERVATORY), env=env, stdout=log, stderr=subprocess.STDOUT)
        finally:
            log.close()
    return popen(command, cwd=str(OBSERVATORY), env=env)


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


def _valid_manifest(path, claim):
    try:
        document = json.loads(Path(path).read_text())
        digest = document.pop('sha256')
        raw = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if hashlib.sha256(raw).hexdigest() != digest or digest != claim.get('manifest_sha256'):
            return False
        runs = document.get('runs') or []
        index = int(claim.get('run_index', -1))
        return 0 <= index < len(runs) and runs[index].get('config') == claim.get('spec')
    except (OSError, ValueError, TypeError, KeyError):
        return False

def _result_metadata(run_dir):
    result = {'status': {}, 'meta': {}, 'diagnostics_summary': {}}
    status_keys = ('phase', 'computed_time', 'progress', 'frames', 'steps', 'wall_seconds', 'openmp_threads', 'error', 'flags')
    meta_keys = ('mode', 'model_revision', 'n', 'n_galaxies', 'duration', 'seed', 'threads', 'lifecycle_enabled')
    try:
        status = json.loads((Path(run_dir) / 'status.json').read_text())
        result['status'] = {key: status[key] for key in status_keys if key in status}
    except (OSError, ValueError):
        pass
    try:
        meta = json.loads((Path(run_dir) / 'meta.json').read_text())
        result['meta'] = {key: meta[key] for key in meta_keys if key in meta}
    except (OSError, ValueError):
        pass
    diagnostics = Path(run_dir) / 'diagnostics.jsonl'
    try:
        lines = [line for line in diagnostics.read_text().splitlines() if line.strip()]
        last = json.loads(lines[-1]) if lines else {}
        result['diagnostics_summary'] = {
            'records': len(lines),
            'last': {key: value for key, value in last.items() if isinstance(value, (str, int, float, bool)) or value is None},
        }
    except (OSError, ValueError):
        pass
    return result

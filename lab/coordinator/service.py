"""Coordinator process: HTTP API plus the backend scaler."""
import secrets
import threading
import time

from lab.backends.base import NotConfigured
from lab.backends.github import GitHubBackend
from lab.backends.local import LocalBackend
from lab.coordinator.api import serve_http
from lab.paths import ENV_FILE


def ensure_token(cfg):
    if cfg.worker_token:
        return cfg.worker_token
    token = secrets.token_hex(32)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ENV_FILE.read_text() if ENV_FILE.is_file() else ''
    if 'LAB_WORKER_TOKEN=' in existing:
        lines = []
        for line in existing.splitlines():
            if line.startswith('LAB_WORKER_TOKEN='):
                lines.append(f'LAB_WORKER_TOKEN={token}')
            else:
                lines.append(line)
        ENV_FILE.write_text('\n'.join(lines) + '\n')
    else:
        with ENV_FILE.open('a') as handle:
            if existing and not existing.endswith('\n'):
                handle.write('\n')
            handle.write(f'LAB_WORKER_TOKEN={token}\n')
    print(f'Wrote a new LAB_WORKER_TOKEN to {ENV_FILE}', flush=True)
    return token


def serve(cfg, db, store, backends=None):
    token = ensure_token(cfg)
    servers = serve_http(
        db, store, token, cfg.heartbeat_grace_seconds, cfg.lease_seconds, cfg.listen_hosts, cfg.port,
        drain_margin_seconds=cfg.drain_margin_seconds,
    )
    local = LocalBackend()
    github = GitHubBackend(cfg, active=lambda: db.active_leases('github') + db.dispatching_count('github', 900))
    if backends:
        local = backends.get('local', local)
        github = backends.get('github', github)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                db.reap(cfg.heartbeat_grace_seconds)
                _scale(cfg, db, 'local', local, cfg.local_concurrency)
                _scale(cfg, db, 'github', github, cfg.github_concurrency)
            except Exception as exc:
                db.event('scaler_error', {'error': str(exc)})
            stop.wait(cfg.poll_seconds)

    thread = threading.Thread(target=loop, name='lab-scaler', daemon=True)
    thread.start()
    for server in servers:
        threading.Thread(target=server.serve_forever, name=f'lab-{server.server_address[0]}', daemon=True).start()
    print('Lab coordinator listening on ' + ', '.join(f'{host}:{cfg.port}' for host in cfg.listen_hosts), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        local.drain()
        github.drain()
        for server in servers:
            server.shutdown()


def _scale(cfg, db, backend, adapter, limit):
    if backend == 'github':
        active = db.active_leases('github') + db.dispatching_count('github', 900)
        room = max(0, min(20, int(limit)) - active)
        if room <= 0:
            return
        for group in db.pending_commits('github'):
            if room <= 0:
                break
            commit = group['git_commit']
            if not commit:
                if not getattr(adapter, 'reported_unpinned', False):
                    db.event('launch_failed', {'backend': 'github', 'error': 'Experiment has no pinned commit SHA'})
                    adapter.reported_unpinned = True
                continue
            count = min(int(group['pending']), room)
            try:
                started = adapter.launch(count, {'coordinator_url': _url(cfg), 'git_commit': commit})
            except NotConfigured as exc:
                for ident in getattr(exc, 'started', []):
                    db.note_dispatch(backend, ident)
                if not getattr(adapter, 'reported_unconfigured', False):
                    db.event('launch_failed', {'backend': backend, 'error': str(exc)})
                    adapter.reported_unconfigured = True
                return
            except Exception as exc:
                for ident in getattr(exc, 'started', []):
                    db.note_dispatch(backend, ident)
                db.event('scaler_error', {'backend': backend, 'error': str(exc)})
                return
            for ident in started:
                db.note_dispatch(backend, ident)
            room -= len(started)
        return

    pending = db.pending_count(backend)
    if pending <= 0:
        return
    room = max(0, int(limit) - adapter.active_count())
    count = min(pending, room)
    if count <= 0:
        return
    try:
        adapter.launch(count, {'coordinator_url': _url(cfg)})
    except NotConfigured as exc:
        if not getattr(adapter, 'reported_unconfigured', False):
            db.event('launch_failed', {'backend': backend, 'error': str(exc)})
            adapter.reported_unconfigured = True
    except Exception as exc:
        db.event('scaler_error', {'backend': backend, 'error': str(exc)})


def _url(cfg):
    host = cfg.tailscale_host or cfg.host
    return f'http://{host}:{cfg.port}'

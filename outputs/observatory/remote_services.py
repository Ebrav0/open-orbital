"""Start, check, or stop the Observatory (8766) and Lab coordinator (8770) on a remote node.

Run on the node from the repository root with work/venv/bin/python. The Mac launcher
outputs/observatory/cube-connect.sh calls this over SSH. Both servers bind loopback only;
`status` fails if either listener is reachable on any other address.

  status          print JSON health for both services
  ensure          start whichever service is not answering, then wait for health
  stop [--force]  graceful stop; refuses while Observatory or Lab work is active
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / 'work/venv/bin/python'
OBS_ACTIVE = ('running', 'initializing', 'pausing')
SERVICES = {
    'observatory': dict(
        port=8766, health='/api/jobs?view=summary',
        argv=['/bin/sh', str(ROOT / 'outputs/observatory/run.sh')],
        log=ROOT / 'work/observatory-data/server.log',
        stop_signal=signal.SIGTERM,  # server.py turns SIGTERM into its checkpointing shutdown
    ),
    'lab': dict(
        port=8770, health='/api/health',
        argv=[str(PYTHON), '-m', 'lab', 'serve'],
        log=ROOT / 'work/lab-data/serve.log',
        stop_signal=signal.SIGINT,  # lab serve drains local workers only on KeyboardInterrupt
    ),
}


def fetch(port, path, timeout=2):
    headers = {}
    if port == SERVICES['lab']['port']:
        headers['Authorization'] = 'Bearer ' + lab_config().worker_token
    try:
        request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return json.loads(r.read() or b'null')
    except Exception:
        return None


def listeners(port):
    """(address, inode) for every TCP LISTEN socket on port, from /proc/net/tcp{,6}."""
    found = []
    for name in ('tcp', 'tcp6'):
        try:
            rows = Path(f'/proc/net/{name}').read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            addr, hexport = f[1].split(':')
            if f[3] == '0A' and int(hexport, 16) == port:
                found.append((_address(addr), f[9]))
    return found


def _address(hexaddr):
    if len(hexaddr) == 8:
        return '.'.join(str(b) for b in reversed(bytes.fromhex(hexaddr)))
    words = [bytes.fromhex(hexaddr[i:i + 8])[::-1].hex() for i in range(0, 32, 8)]
    full = ''.join(words)
    if full == '0' * 32:
        return '::'
    if full == '0' * 31 + '1':
        return '::1'
    if full.startswith('0' * 20 + 'ffff'):
        return '::ffff:' + '.'.join(str(b) for b in bytes.fromhex(full[24:]))
    return ':'.join(full[i:i + 4] for i in range(0, 32, 4))


def loopback(address):
    return address.startswith('127.') or address in ('::1', '::ffff:127.0.0.1')


def owner_pid(inodes):
    wanted = {f'socket:[{i}]' for i in inodes}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / 'fd').iterdir():
                if os.readlink(fd) in wanted:
                    return int(proc.name)
        except OSError:
            continue
    return None


def observatory_active():
    jobs = fetch(8766, '/api/jobs?view=summary') or []
    return [j.get('id') for j in jobs if (j.get('status') or {}).get('phase') in OBS_ACTIVE]


def lab_config():
    """Reloaded on each call: the first `lab serve` writes LAB_WORKER_TOKEN to lab.env."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from lab.config import load_config
    return load_config()


def lab_active():
    from lab.coordinator.db import Database
    db = Database(lab_config().database)
    return db.active_leases('local') + db.active_leases('github')


def status():
    out = {}
    for name, svc in SERVICES.items():
        socks = listeners(svc['port'])
        out[name] = dict(
            port=svc['port'],
            healthy=fetch(svc['port'], svc['health']) is not None,
            listening=sorted({a for a, _ in socks}),
            loopback_only=all(loopback(a) for a, _ in socks),
            pid=owner_pid([i for _, i in socks]) if socks else None,
            log=str(svc['log'].relative_to(ROOT)),
        )
    if out['observatory']['healthy']:
        out['observatory']['active_jobs'] = observatory_active()
    if out['lab']['healthy']:
        out['lab']['active_leases'] = lab_active()
    return out


def _start(svc):
    svc['log'].parent.mkdir(parents=True, exist_ok=True)
    log = open(svc['log'], 'ab')

    def child():
        # An SSH-started background process inherits SIGINT as ignored, and Python then
        # never raises KeyboardInterrupt, so `lab serve` could not drain on stop.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    subprocess.Popen(svc['argv'], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, preexec_fn=child, close_fds=True)


def ensure(timeout=60):
    if not PYTHON.exists():
        raise SystemExit(f'Missing {PYTHON}; build work/venv first (outputs/observatory/LINUX_COMPUTE_NODE.md).')
    for name, svc in SERVICES.items():
        if fetch(svc['port'], svc['health']) is not None:
            print(f'{name}: already running on 127.0.0.1:{svc["port"]}')
            continue
        if listeners(svc['port']):
            raise SystemExit(f'{name}: port {svc["port"]} is in use but does not answer {svc["health"]}. Leave that process alone and free the port.')
        print(f'{name}: starting (log {svc["log"].relative_to(ROOT)})')
        _start(svc)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(fetch(s['port'], s['health']) is not None for s in SERVICES.values()):
            break
        time.sleep(0.5)
    else:
        raise SystemExit('Services did not become healthy; see the logs named above.')
    report = status()
    exposed = [n for n, s in report.items() if not s['loopback_only']]
    if exposed:
        raise SystemExit(f'Refusing to continue: {", ".join(exposed)} listen beyond loopback: {report}')
    print(json.dumps(report))


def stop(force=False):
    report = status()
    busy = report['observatory'].get('active_jobs') or []
    leases = report['lab'].get('active_leases') or 0
    if (busy or leases) and not force:
        raise SystemExit(f'Not stopping: Observatory active jobs {busy}, Lab active leases {leases}. '
                         'Pause them first, or pass --force to request a checkpointing shutdown.')
    for name in ('lab', 'observatory'):
        svc, pid = SERVICES[name], report[name]['pid']
        if pid is None:
            print(f'{name}: not running')
            continue
        os.kill(pid, svc['stop_signal'])
        for _ in range(120):
            if not listeners(svc['port']):
                break
            time.sleep(0.5)
        print(f'{name}: {"stopped" if not listeners(svc["port"]) else "still shutting down (pid %d)" % pid}')


def main(argv):
    command = argv[0] if argv else 'status'
    if command == 'status':
        print(json.dumps(status(), indent=2))
    elif command == 'ensure':
        ensure()
    elif command == 'stop':
        stop(force='--force' in argv[1:])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])

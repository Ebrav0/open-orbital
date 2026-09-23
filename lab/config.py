"""Load Lab settings. Limits are clamped here so a config file cannot lift a hard cap."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lab.paths import CONFIG_FILE, DATA, DATABASE, ENV_FILE, RCLONE_CONFIG, SCRATCH

LEASE_FLOOR = 15 * 60
LEASE_CEILING = 5 * 3600
GITHUB_CEILING = 20
RUNTIME_CEILING_HOURS = 120


def _table(doc, name):
    value = doc.get(name) or {}
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be a table')
    return value


def load_env(path=None):
    path = Path(path or ENV_FILE)
    found = {}
    if not path.is_file():
        return found
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def env_value(name, file_values):
    return os.environ.get(name) or file_values.get(name) or ''


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    tailscale_host: str
    lease_seconds: int
    drain_margin_seconds: int
    heartbeat_grace_seconds: int
    checkpoint_interval_seconds: int
    github_concurrency: int
    local_concurrency: int
    max_threads: int
    max_ram_mib: int
    max_runtime_hours: int
    max_total_runs: int
    max_storage_gib: float
    checkpoint_retention: int
    budget_worker_hours: float
    max_attempts: int
    disk_floor_bytes: int
    decisions_url: str
    chat_url: str
    luna_model: str
    jev_model: str
    luna_provider_sort: str
    noul_threshold: float
    storage_backend: str
    rclone_config: Path
    rclone_remote: str
    drive_folder: str
    scratch: Path
    github_repo: str
    github_workflow: str
    github_ref: str
    default_backend: str
    poll_seconds: float
    database: Path
    data: Path
    env_file: Path
    openrouter_api_key: str
    github_token: str
    worker_token: str

    @property
    def listen_hosts(self):
        hosts = [self.host]
        if self.tailscale_host and self.tailscale_host not in hosts:
            hosts.append(self.tailscale_host)
        return hosts


def load_config(path=None, env_path=None):
    path = Path(path or os.environ.get('LAB_CONFIG') or CONFIG_FILE)
    doc = {}
    if path.is_file():
        doc = tomllib.loads(path.read_text())
    example = Path(__file__).resolve().parent / 'config.example.toml'
    base = tomllib.loads(example.read_text())
    server = {**_table(base, 'server'), **_table(doc, 'server')}
    limits = {**_table(base, 'limits'), **_table(doc, 'limits')}
    planner = {**_table(base, 'planner'), **_table(doc, 'planner')}
    storage = {**_table(base, 'storage'), **_table(doc, 'storage')}
    github = {**_table(base, 'github'), **_table(doc, 'github')}
    scheduler = {**_table(base, 'scheduler'), **_table(doc, 'scheduler')}
    file_env = load_env(env_path)
    lease = int(limits['lease_seconds'])
    lease = min(LEASE_CEILING, max(LEASE_FLOOR, lease))
    ceiling = min(GITHUB_CEILING, int(limits['github_concurrency_ceiling']))
    concurrency = min(ceiling, max(1, int(limits['github_concurrency'])))
    runtime = min(RUNTIME_CEILING_HOURS, max(1, int(limits['max_runtime_hours'])))
    drain = max(60, int(limits['drain_margin_seconds']))
    if drain >= lease:
        drain = max(60, lease // 10)
    storage_backend = os.environ.get('LAB_STORAGE') or storage['backend']
    rclone = Path(os.environ.get('LAB_RCLONE_CONFIG') or RCLONE_CONFIG)
    return Config(
        host=server['host'],
        port=int(os.environ.get('LAB_PORT') or server['port']),
        tailscale_host=os.environ.get('LAB_TAILSCALE_HOST') or server['tailscale_host'],
        lease_seconds=lease,
        drain_margin_seconds=drain,
        heartbeat_grace_seconds=max(30, int(limits['heartbeat_grace_seconds'])),
        checkpoint_interval_seconds=max(30, int(limits['checkpoint_interval_seconds'])),
        github_concurrency=concurrency,
        local_concurrency=max(1, int(limits['local_concurrency'])),
        max_threads=max(1, int(limits['max_threads'])),
        max_ram_mib=max(256, int(limits['max_ram_mib'])),
        max_runtime_hours=runtime,
        max_total_runs=min(500, max(1, int(limits.get('max_total_runs', 500)))),
        max_storage_gib=min(1000.0, max(0.1, float(limits.get('max_storage_gib', 100)))),
        checkpoint_retention=min(5, max(2, int(limits.get('checkpoint_retention', 3)))),
        budget_worker_hours=float(limits['budget_worker_hours']),
        max_attempts=max(1, int(limits['max_attempts'])),
        disk_floor_bytes=int(limits['disk_floor_bytes']),
        decisions_url=planner['decisions_url'],
        chat_url=planner['chat_url'],
        luna_model=planner['luna_model'],
        jev_model=planner['jev_model'],
        luna_provider_sort=planner['luna_provider_sort'],
        noul_threshold=float(planner['noul_threshold']),
        storage_backend=storage_backend,
        rclone_config=rclone,
        rclone_remote=storage['rclone_remote'],
        drive_folder=storage['drive_folder'],
        scratch=SCRATCH,
        github_repo=github['repo'],
        github_workflow=github['workflow'],
        github_ref=github['ref'],
        default_backend=scheduler['default_backend'],
        poll_seconds=float(scheduler['poll_seconds']),
        database=Path(os.environ.get('LAB_DATABASE') or DATABASE),
        data=DATA,
        env_file=Path(env_path or ENV_FILE),
        openrouter_api_key=env_value('OPENROUTER_API_KEY', file_env),
        github_token=env_value('LAB_GITHUB_TOKEN', file_env),
        worker_token=env_value('LAB_WORKER_TOKEN', file_env),
    )

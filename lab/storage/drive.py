"""Google Drive via rclone. The current pointer stays in SQLite, not in the folder."""
import hashlib
import os
import subprocess
from pathlib import Path

from lab.storage.base import CheckpointStore, StorageError
from lab.storage.memory import file_sha256


class RcloneDriveStore(CheckpointStore):
    def __init__(self, config_path, remote, folder, scratch, runner=None):
        self.config_path = Path(config_path)
        self.remote = remote
        self.folder = folder.strip('/')
        self.scratch = Path(scratch)
        self.runner = runner or _run

    def put(self, key, path):
        path = Path(path)
        if not path.is_file():
            raise StorageError(f'missing archive {path}')
        self._copyto(str(path), self._remote(key))

    def verify(self, key, sha256, size=None):
        self.scratch.mkdir(parents=True, exist_ok=True)
        dest = self.scratch / f'verify-{hashlib.sha256(key.encode()).hexdigest()[:16]}.tar.gz'
        try:
            self._copyto(self._remote(key), str(dest))
            if size is not None and dest.stat().st_size != int(size):
                return False
            return file_sha256(dest) == sha256
        except StorageError:
            return False
        finally:
            try:
                dest.unlink()
            except OSError:
                pass

    def fetch(self, key, dest):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._copyto(self._remote(key), str(dest))

    def list_versions(self, prefix):
        completed = self.runner(self._base_args() + ['lsf', self._remote(prefix)])
        names = []
        for line in completed.stdout.splitlines():
            name = line.strip()
            if name:
                names.append(f'{prefix.rstrip("/")}/{name}' if not name.startswith(prefix) else name)
        return names

    def delete(self, key):
        self.runner(self._base_args() + ['deletefile', self._remote(key)])

    def _remote(self, key):
        key = key.lstrip('/')
        return f'{self.remote}:{self.folder}/{key}'

    def _copyto(self, source, dest):
        args = self._base_args() + [
            'copyto', source, dest,
            '--retries', '5',
            '--low-level-retries', '10',
            '--drive-chunk-size', '64M',
        ]
        self.runner(args)

    def _base_args(self):
        if not self.config_path.is_file():
            raise StorageError(f'rclone config is missing: {self.config_path}')
        return ['rclone', '--config', str(self.config_path)]


def _run(args):
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise StorageError('rclone is not installed') from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        raise StorageError(detail[-500:] or f'rclone exited {completed.returncode}')
    return completed


def build_store(cfg):
    if cfg.storage_backend == 'memory':
        from lab.storage.memory import MemoryStore
        return MemoryStore()
    if cfg.storage_backend == 'directory':
        from lab.storage.directory import DirectoryStore
        return DirectoryStore(cfg.scratch / 'objects')
    if cfg.storage_backend == 'drive':
        return RcloneDriveStore(cfg.rclone_config, cfg.rclone_remote, cfg.drive_folder, cfg.scratch)
    raise StorageError(f'unknown storage backend {cfg.storage_backend}')

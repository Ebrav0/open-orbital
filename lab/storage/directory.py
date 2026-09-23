"""Filesystem store. Two processes can share it. Drive remains the shared transport in production."""
import os
import shutil
from pathlib import Path

from lab.storage.base import CheckpointStore, StorageError
from lab.storage.memory import file_sha256


class DirectoryStore(CheckpointStore):
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key, path):
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + '.uploading')
        shutil.copyfile(path, temp)
        os.replace(temp, dest)

    def verify(self, key, sha256, size=None):
        dest = self._path(key)
        if not dest.is_file():
            return False
        if size is not None and dest.stat().st_size != int(size):
            return False
        return file_sha256(dest) == sha256

    def fetch(self, key, dest):
        source = self._path(key)
        if not source.is_file():
            raise StorageError(f'unknown object {key}')
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)

    def list_versions(self, prefix):
        root = self._path(prefix)
        if not root.exists():
            return []
        found = []
        for path in root.rglob('*'):
            if path.is_file():
                found.append(str(path.relative_to(self.root)))
        return sorted(found)

    def delete(self, key):
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def _path(self, key):
        dest = (self.root / key).resolve()
        try:
            dest.relative_to(self.root)
        except ValueError:
            raise StorageError('object key escapes the store') from None
        return dest

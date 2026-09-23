"""Process-local store for tests. Production workers share Drive instead."""
import hashlib
from pathlib import Path

from lab.storage.base import CheckpointStore, StorageError


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class MemoryStore(CheckpointStore):
    def __init__(self):
        self.objects = {}

    def put(self, key, path):
        path = Path(path)
        if not path.is_file():
            raise StorageError(f'missing archive {path}')
        self.objects[key] = path.read_bytes()

    def verify(self, key, sha256, size=None):
        data = self.objects.get(key)
        if data is None:
            return False
        if size is not None and len(data) != int(size):
            return False
        return hashlib.sha256(data).hexdigest() == sha256

    def fetch(self, key, dest):
        data = self.objects.get(key)
        if data is None:
            raise StorageError(f'unknown object {key}')
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def list_versions(self, prefix):
        return sorted(key for key in self.objects if key.startswith(prefix))

    def delete(self, key):
        self.objects.pop(key, None)

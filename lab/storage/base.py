"""Checkpoint storage. Workers call this interface and never a vendor client."""
from pathlib import Path


class StorageError(RuntimeError):
    pass


class CheckpointStore:
    def put(self, key: str, path: Path) -> None:
        raise NotImplementedError

    def verify(self, key: str, sha256: str, size: int | None = None) -> bool:
        raise NotImplementedError

    def fetch(self, key: str, dest: Path) -> None:
        raise NotImplementedError

    def list_versions(self, prefix: str) -> list:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def prune(self, prefix: str, keep: int) -> list[str]:
        keep = max(1, int(keep))
        versions = sorted(self.list_versions(prefix))
        removed = versions[:-keep]
        for key in removed:
            self.delete(key)
        return removed

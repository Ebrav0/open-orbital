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

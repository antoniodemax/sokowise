"""Local filesystem blob storage — development and single-host deployments.

Production should plug an object-storage implementation (S3-compatible: same
`put/get/delete` with the same keys) behind `BlobStorage`; nothing else changes.
"""

import asyncio
import os
import re
from pathlib import Path

from app.storage.base import StorageError

_KEY = re.compile(r"^[a-z0-9][a-z0-9/._-]{0,200}$")


class LocalFileStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def ensure_ready(self) -> None:
        """Create the root now, so a bad directory fails at startup and not on the first upload."""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"receipt storage root cannot be created: {exc}") from exc
        if not self.is_writable():
            msg = f"receipt storage root is not writable: {self._root}"
            raise StorageError(msg)

    def is_writable(self) -> bool:
        return self._root.is_dir() and os.access(self._root, os.W_OK)

    def _path(self, key: str) -> Path:
        # Keys are service-generated, but never trust a path anyway.
        if not _KEY.fullmatch(key) or ".." in key.split("/"):
            msg = "invalid storage key"
            raise StorageError(msg)
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            msg = "storage key escapes the root"
            raise StorageError(msg)
        return path

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise StorageError("blob not found") from None
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

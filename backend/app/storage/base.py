from typing import Protocol


class StorageError(Exception):
    """The backend could not store or read a blob; the API reports 503 STORAGE_UNAVAILABLE."""


class BlobStorage(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

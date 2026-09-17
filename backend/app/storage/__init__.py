"""Blob storage for uploaded files (docs/ARCHITECTURE.md §6.7).

The database keeps only a storage key; bytes live behind `BlobStorage`. Keys are
built by the service from ids it generated, never from client input, so a local
backend cannot be steered outside its root.
"""

from app.storage.base import BlobStorage, StorageError
from app.storage.local import LocalFileStorage

__all__ = ["BlobStorage", "LocalFileStorage", "StorageError"]

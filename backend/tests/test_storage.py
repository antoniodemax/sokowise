"""Local blob storage: key validation, root containment, startup readiness."""

from pathlib import Path

import pytest
from app.storage import LocalFileStorage, StorageError

pytestmark = pytest.mark.anyio


async def test_put_get_delete_round_trip(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.put("receipts/a/b.jpg", b"jpeg", content_type="image/jpeg")
    assert await storage.get("receipts/a/b.jpg") == b"jpeg"
    assert not list(tmp_path.glob("**/*.part"))
    await storage.delete("receipts/a/b.jpg")
    with pytest.raises(StorageError):
        await storage.get("receipts/a/b.jpg")


@pytest.mark.parametrize(
    "key",
    ["../etc/passwd", "receipts/../../x", "/abs/path", "UPPER/case.jpg", "a" * 202, "", "a b"],
)
async def test_keys_cannot_escape_or_break_the_namespace(tmp_path: Path, key: str) -> None:
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(StorageError):
        await storage.get(key)
    assert not any(tmp_path.parent.glob("passwd"))


def test_ensure_ready_creates_the_root_and_reports_writability(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "nested" / "receipts")
    assert not storage.is_writable()
    storage.ensure_ready()
    assert storage.is_writable()


def test_ensure_ready_fails_fast_when_the_root_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(StorageError):
        LocalFileStorage(blocker).ensure_ready()

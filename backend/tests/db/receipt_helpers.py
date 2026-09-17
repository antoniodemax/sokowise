"""Deterministic pieces for receipt tests: a scripted extraction provider and tiny images."""

import io
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.ai.receipts import ExtractedLine, ExtractionResult, ReceiptExtraction
from app.api.v1.receipts import get_receipt_provider
from httpx import ASGITransport, AsyncClient
from PIL import Image

from tests.db.conftest import ApiFactory

RECEIPTS_URL = "/api/v1/receipts"
Step = ExtractionResult | Exception


def make_image(
    fmt: str = "JPEG",
    size: tuple[int, int] = (640, 900),
    color: tuple[int, int, int] = (250, 250, 245),
) -> bytes:
    """A small valid image; the pixels do not matter to the fake provider."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def line(
    name: str,
    quantity: str,
    unit_cost: str,
    line_total: str | None = None,
    *,
    sku: str | None = None,
    confidence: str | None = "0.95",
) -> ExtractedLine:
    return ExtractedLine(
        product_name=name,
        sku=sku,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        line_total=Decimal(line_total) if line_total is not None else None,
        confidence=Decimal(confidence) if confidence is not None else None,
    )


def extraction(lines: Sequence[ExtractedLine], **fields: Any) -> ExtractionResult:
    base: dict[str, Any] = {
        "supplier_name": "Kamau Wholesalers",
        "receipt_number": "KW-1042",
        "currency": "KES",
    }
    base.update(fields)
    return ExtractionResult(
        extraction=ReceiptExtraction(lines=list(lines), **base), provider="fake", model="fake-1"
    )


class FakeReceiptExtractionProvider:
    """Plays scripted results; records what it was given (bytes size and MIME only)."""

    name = "fake"

    def __init__(self, script: Sequence[Step]) -> None:
        self.script = list(script)
        self.calls: list[tuple[int, str]] = []

    async def extract(self, image: bytes, *, mime_type: str) -> ExtractionResult:
        self.calls.append((len(image), mime_type))
        if not self.script:
            raise AssertionError("the fake receipt provider ran out of scripted results")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


async def make_receipt_api(
    api_factory: ApiFactory,
    provider: FakeReceiptExtractionProvider | None,
    storage_dir: str,
    **settings: Any,
) -> AsyncClient:
    api = await api_factory(receipt_storage_dir=storage_dir, **settings)
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    transport.app.dependency_overrides[get_receipt_provider] = lambda: provider  # type: ignore[attr-defined]
    return api


async def upload(
    api: AsyncClient,
    headers: dict[str, str],
    data: bytes | None = None,
    *,
    filename: str = "receipt.jpg",
    content_type: str = "image/jpeg",
) -> Any:
    return await api.post(
        RECEIPTS_URL,
        headers=headers,
        files={"file": (filename, data if data is not None else make_image(), content_type)},
    )


async def upload_ok(api: AsyncClient, headers: dict[str, str], **kw: Any) -> dict[str, Any]:
    response = await upload(api, headers, **kw)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def process(api: AsyncClient, headers: dict[str, str], receipt_id: str) -> Any:
    return await api.post(f"{RECEIPTS_URL}/{receipt_id}/process", headers=headers)


async def confirm(
    api: AsyncClient,
    headers: dict[str, str],
    receipt_id: str,
    lines: list[dict[str, Any]],
    **extra: Any,
) -> Any:
    return await api.post(
        f"{RECEIPTS_URL}/{receipt_id}/confirm", headers=headers, json={"lines": lines, **extra}
    )

"""/api/v1/receipts: upload validation, extraction, matching, confirmation, isolation."""

import json
import uuid
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.ai.errors import AIUnavailableError
from app.ai.receipts import ReceiptExtraction, ReceiptExtractionError
from app.models import AuditLog, InventoryMovement, Product, ReceiptLine
from app.services.receipt_matching import match_line
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code
from tests.db.conftest import ApiFactory
from tests.db.isolation import IsolationCase, Tenant, assert_tenant_isolated
from tests.db.receipt_helpers import (
    RECEIPTS_URL,
    FakeReceiptExtractionProvider,
    confirm,
    extraction,
    line,
    make_image,
    make_receipt_api,
    process,
    upload,
    upload_ok,
)
from tests.db.sales_helpers import make_product

pytestmark = [pytest.mark.db, pytest.mark.anyio]


@pytest.fixture
def storage_dir(tmp_path: Any) -> str:
    return str(tmp_path / "blobs")


async def _movements(session: AsyncSession, business_id: str) -> list[InventoryMovement]:
    rows = await session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.business_id == uuid.UUID(business_id))
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _ready_receipt(
    api: AsyncClient, tenant: Tenant, provider: FakeReceiptExtractionProvider
) -> dict[str, Any]:
    receipt = await upload_ok(api, tenant.owner)
    processed = await process(api, tenant.owner, receipt["id"])
    assert processed.status_code == HTTPStatus.OK, processed.text
    body: dict[str, Any] = processed.json()
    assert body["status"] == "READY_FOR_REVIEW"
    return body


# --- upload and validation ---------------------------------------------------------------


async def test_upload_stores_the_image_and_serves_it_only_to_its_business(
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
) -> None:
    a, b = tenants
    api = await make_receipt_api(api_factory, FakeReceiptExtractionProvider([]), storage_dir)
    receipt = await upload_ok(api, a.owner, filename="IMG_2031.jpg")
    assert receipt["status"] == "UPLOADED" and receipt["mime_type"] == "image/jpeg"
    assert receipt["original_filename"] == "IMG_2031.jpg" and receipt["lines"] == []
    image = await api.get(f"{RECEIPTS_URL}/{receipt['id']}/image", headers=a.owner)
    assert image.status_code == HTTPStatus.OK and image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "private, no-store"
    assert image.content[:3] == b"\xff\xd8\xff"
    assert (
        await api.get(f"{RECEIPTS_URL}/{receipt['id']}/image", headers=b.owner)
    ).status_code == HTTPStatus.NOT_FOUND
    listing = await api.get(RECEIPTS_URL, headers=a.owner)
    assert [r["id"] for r in listing.json()] == [receipt["id"]]
    assert (await api.get(RECEIPTS_URL, headers=b.owner)).json() == []
    uploads = await _audits(db_session, a.business_id, "receipt.upload")
    assert len(uploads) == 1 and uploads[0].after == {
        "mime_type": "image/jpeg",
        "size_bytes": len(make_image()),
        "width": 640,
        "height": 900,
    }


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "code"),
    [
        (
            b"<html><script>alert(1)</script></html>",
            "receipt.jpg",
            "image/jpeg",
            "RECEIPT_IMAGE_INVALID",
        ),
        (
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
            "receipt.svg",
            "image/svg+xml",
            "RECEIPT_IMAGE_INVALID",
        ),
        (b"MZ\x90\x00" + b"\x00" * 100, "receipt.exe", "image/png", "RECEIPT_IMAGE_INVALID"),
        (b"%PDF-1.4 " + b"\x00" * 100, "receipt.pdf", "application/pdf", "RECEIPT_IMAGE_INVALID"),
        (b"\xff\xd8\xff" + b"\x00" * 200, "truncated.jpg", "image/jpeg", "RECEIPT_IMAGE_INVALID"),
        (b"", "empty.jpg", "image/jpeg", "RECEIPT_IMAGE_INVALID"),
    ],
)
async def test_non_images_are_rejected_regardless_of_the_declared_type(
    api_factory: ApiFactory,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
    data: bytes,
    filename: str,
    content_type: str,
    code: str,
) -> None:
    a, _ = tenants
    api = await make_receipt_api(api_factory, None, storage_dir)
    response = await upload(api, a.owner, data, filename=filename, content_type=content_type)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert error_code(response) == code


async def test_oversized_and_tiny_images_are_rejected(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant], storage_dir: str
) -> None:
    a, _ = tenants
    api = await make_receipt_api(api_factory, None, storage_dir, receipt_max_bytes=64 * 1024)
    big = make_image("PNG", (900, 900), (17, 33, 51)) + bytes(range(256)) * 300
    too_big = await upload(api, a.owner, big)
    assert (
        too_big.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        and error_code(too_big) == "RECEIPT_TOO_LARGE"
    )
    tiny = await upload(api, a.owner, make_image("PNG", (80, 80)))
    assert (
        tiny.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and error_code(tiny) == "RECEIPT_IMAGE_INVALID"
    )
    webp = await upload(
        api, a.owner, make_image("WEBP"), filename="r.webp", content_type="image/webp"
    )
    assert webp.status_code == HTTPStatus.CREATED and webp.json()["mime_type"] == "image/webp"


async def test_receipts_are_owner_only_and_need_a_session(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant], storage_dir: str
) -> None:
    a, _ = tenants
    api = await make_receipt_api(api_factory, None, storage_dir)
    assert (await upload(api, {})).status_code == HTTPStatus.UNAUTHORIZED
    assert a.staff is not None
    assert (await upload(api, a.staff)).status_code == HTTPStatus.FORBIDDEN
    assert (await api.get(RECEIPTS_URL, headers=a.staff)).status_code == HTTPStatus.FORBIDDEN
    rid = uuid.uuid4()
    assert (await confirm(api, a.staff, str(rid), [])).status_code == HTTPStatus.FORBIDDEN


async def test_receipts_are_tenant_isolated(
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
) -> None:
    a, b = tenants
    api = await make_receipt_api(api_factory, None, storage_dir)

    async def create_in(_: AsyncClient, __: AsyncSession, tenant: Tenant) -> str:
        return str((await upload_ok(api, tenant.owner))["id"])

    await assert_tenant_isolated(
        api,
        db_session,
        IsolationCase(
            name="receipts",
            create_in=create_in,
            read_url=lambda rid: f"{RECEIPTS_URL}/{rid}",
            list_url=RECEIPTS_URL,
            mutations=(
                ("POST", lambda rid: f"{RECEIPTS_URL}/{rid}/process", None),
                ("POST", lambda rid: f"{RECEIPTS_URL}/{rid}/cancel", None),
                (
                    "POST",
                    lambda rid: f"{RECEIPTS_URL}/{rid}/confirm",
                    {
                        "lines": [
                            {
                                "line_id": str(uuid.uuid4()),
                                "product_id": str(uuid.uuid4()),
                                "quantity": "1",
                                "unit_cost": "1",
                            }
                        ]
                    },
                ),
            ),
        ),
        a,
        b,
    )


# --- extraction, validation and matching ------------------------------------------------------


async def test_not_configured_server_refuses_to_process_and_keeps_the_upload(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant], storage_dir: str
) -> None:
    a, _ = tenants
    api = await make_receipt_api(api_factory, None, storage_dir)
    receipt = await upload_ok(api, a.owner)
    response = await process(api, a.owner, receipt["id"])
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert error_code(response) == "RECEIPT_AI_NOT_CONFIGURED"
    assert (await api.get(f"{RECEIPTS_URL}/{receipt['id']}", headers=a.owner)).json()[
        "status"
    ] == "UPLOADED"


async def test_extraction_is_validated_matched_and_flagged(
    api: AsyncClient,
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
) -> None:
    a, b = tenants
    sugar = await make_product(
        api, a.owner, name="Sukari 1kg", price="160", cost="135", stock="10", sku="SUG-1"
    )
    await make_product(
        api, a.owner, name="Mafuta ya kupikia 1L", price="320", cost="285", stock="5"
    )
    await make_product(
        api, a.owner, name="Mafuta ya kupikia 2L", price="600", cost="540", stock="5"
    )
    await make_product(
        api, b.owner, name="Unga wa ugali 2kg", price="185", cost="160", stock="5"
    )  # other business
    provider = FakeReceiptExtractionProvider(
        [
            extraction(
                [
                    line(
                        "SUKARI 1KG", "10", "135.00", "1350.00"
                    ),  # exact name, different case → MATCHED
                    line(
                        "Mafuta ya kupikia", "3", "285.00", "855.00"
                    ),  # no size → two candidates → AMBIGUOUS
                    line(
                        "Unga wa ugali 2kg", "4", "160.00", "640.00"
                    ),  # only exists in business B → UNMATCHED
                    line(
                        "Sabuni ya bar", "12", "115.00", "1400.00", confidence="0.4"
                    ),  # arithmetic off + low confidence
                ],
                subtotal=Decimal("4225.00"),
                total=Decimal("9999.00"),
                currency="USD",
            )
        ]
    )
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    body = await _ready_receipt(rapi, a, provider)
    assert provider.calls == [(len(make_image()), "image/jpeg")]
    assert body["supplier_name"] == "Kamau Wholesalers" and body["currency"] == "USD"
    assert body["warnings"] == ["total_mismatch", "currency_not_kes"]
    lines = body["lines"]
    assert [item["match_status"] for item in lines] == [
        "MATCHED",
        "AMBIGUOUS",
        "UNMATCHED",
        "UNMATCHED",
    ]
    assert lines[0]["matched_product_id"] == sugar["id"] and lines[0]["warnings"] == []
    assert lines[1]["matched_product_id"] is None and len(lines[1]["candidate_product_ids"]) == 2
    assert lines[3]["warnings"] == ["line_total_mismatch", "low_confidence"]
    assert all(item["review_status"] == "PENDING" for item in lines)
    extracts = await _audits(db_session, a.business_id, "receipt.extract")
    assert extracts[-1].after is not None
    assert extracts[-1].after == {
        **extracts[-1].after,
        "status": "READY_FOR_REVIEW",
        "lines": 4,
        "matched": 1,
    }


def test_matching_never_guesses_weakly() -> None:
    def product(name: str, sku: str | None = None) -> Product:
        return Product(
            id=uuid.uuid4(), business_id=uuid.uuid4(), name=name, sku=sku, selling_price=Decimal(1)
        )

    sugar, oil, bread = (
        product("Sukari 1kg", "SUG-1"),
        product("Mafuta ya kupikia 1L"),
        product("Mkate 400g"),
    )
    catalogue = [sugar, oil, bread]
    assert match_line("sukari 1kg", None, catalogue).product_id == sugar.id
    assert match_line("anything", "sug-1", catalogue).product_id == sugar.id
    assert match_line("Sukari 1 kg", None, catalogue).status.value in ("MATCHED", "AMBIGUOUS")
    assert match_line("Sukari", None, catalogue).status.value == "AMBIGUOUS"  # close, not certain
    assert match_line("Rice 2kg", None, catalogue).status.value == "UNMATCHED"
    assert match_line("", None, catalogue).status.value == "UNMATCHED"
    assert match_line("x", None, []).status.value == "UNMATCHED"


@pytest.mark.parametrize(
    ("step", "code", "status"),
    [
        (
            ReceiptExtractionError("The receipt could not be read reliably."),
            "RECEIPT_EXTRACTION_FAILED",
            "FAILED",
        ),
        (AIUnavailableError("busy", code="AI_PROVIDER_BUSY"), "AI_PROVIDER_BUSY", "FAILED"),
        (extraction([]), "RECEIPT_EXTRACTION_FAILED", "FAILED"),
    ],
)
async def test_extraction_failures_mark_the_receipt_failed_and_allow_a_retry(
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
    step: Any,
    code: str,
    status: str,
) -> None:
    a, _ = tenants
    provider = FakeReceiptExtractionProvider([step, extraction([line("Mkate", "2", "60")])])
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    receipt = await upload_ok(rapi, a.owner)
    failed = await process(rapi, a.owner, receipt["id"])
    assert failed.status_code == HTTPStatus.SERVICE_UNAVAILABLE and error_code(failed) == code
    assert "anthropic" not in failed.text.lower() and "claude" not in failed.text.lower()
    detail = (await rapi.get(f"{RECEIPTS_URL}/{receipt['id']}", headers=a.owner)).json()
    assert detail["status"] == status and detail["extraction_error"] in (code, "NO_LINES")
    retried = await process(rapi, a.owner, receipt["id"])
    assert retried.status_code == HTTPStatus.OK and retried.json()["status"] == "READY_FOR_REVIEW"
    assert len(await _audits(db_session, a.business_id, "receipt.extract")) == 2


def test_malformed_model_output_is_rejected_by_the_schema() -> None:
    from pydantic import ValidationError

    bad_payloads = [
        {
            "lines": [
                {
                    "product_name": "x",
                    "quantity": "-1",
                    "unit_cost": "1",
                    "sku": None,
                    "line_total": None,
                    "confidence": None,
                }
            ]
        },
        {
            "lines": [
                {
                    "product_name": "x",
                    "quantity": "1",
                    "unit_cost": "-5",
                    "sku": None,
                    "line_total": None,
                    "confidence": None,
                }
            ]
        },
        {
            "lines": [
                {
                    "product_name": "",
                    "quantity": "1",
                    "unit_cost": "1",
                    "sku": None,
                    "line_total": None,
                    "confidence": None,
                }
            ]
        },
        {"lines": [], "business_id": "spoofed"},
        {
            "lines": [
                {"product_name": "x", "quantity": "1", "unit_cost": "1", "product_id": "spoofed"}
            ]
        },
        {"lines": [{"product_name": "x", "quantity": "abc", "unit_cost": "1"}]},
        {"lines": "not a list"},
    ]
    for payload in bad_payloads:
        with pytest.raises(ValidationError):
            ReceiptExtraction.model_validate(payload)
    ok = ReceiptExtraction.model_validate(
        {
            "lines": [{"product_name": "  Mkate  ", "quantity": "2", "unit_cost": "60"}],
            "receipt_date": "2026-09-17",
        }
    )
    assert ok.lines[0].product_name == "Mkate" and ok.receipt_date == date(2026, 9, 17)


async def test_malicious_product_names_stay_data(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant], storage_dir: str
) -> None:
    a, _ = tenants
    nasty = "<script>alert(1)</script>'; DROP TABLE products; --"
    provider = FakeReceiptExtractionProvider([extraction([line(nasty, "1", "10")])])
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    body = await _ready_receipt(rapi, a, provider)
    assert (
        body["lines"][0]["extracted_name"] == nasty
        and body["lines"][0]["match_status"] == "UNMATCHED"
    )
    assert (await rapi.get("/api/v1/products", headers=a.owner)).status_code == HTTPStatus.OK


# --- confirmation -------------------------------------------------------------------------------


async def test_confirmation_restocks_through_the_inventory_service_atomically(
    api: AsyncClient,
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
) -> None:
    a, _ = tenants
    sugar = await make_product(api, a.owner, name="Sukari 1kg", price="160", cost="135", stock="10")
    oil = await make_product(
        api, a.owner, name="Mafuta ya kupikia 1L", price="320", cost="285", stock="5"
    )
    provider = FakeReceiptExtractionProvider(
        [
            extraction(
                [
                    line("Sukari 1kg", "10", "135.00", "1350.00"),
                    line("Mafuta ya kupikia 1L", "3", "290.00", "870.00"),
                    line("Mystery item", "1", "50"),
                ]
            )
        ]
    )
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    body = await _ready_receipt(rapi, a, provider)
    lines = body["lines"]
    decisions = [
        {
            "line_id": lines[0]["id"],
            "product_id": sugar["id"],
            "quantity": "10",
            "unit_cost": "135.00",
        },
        # The owner corrected the quantity and chose to update the product's cost price.
        {
            "line_id": lines[1]["id"],
            "product_id": oil["id"],
            "quantity": "2",
            "unit_cost": "290.00",
            "update_cost_price": True,
        },
        # The third line is skipped on purpose.
    ]
    response = await confirm(rapi, a.owner, body["id"], decisions, reason="Delivery 17 Sept")
    assert response.status_code == HTTPStatus.OK, response.text
    result = response.json()
    assert result["movements_created"] == 2 and result["receipt"]["status"] == "CONFIRMED"
    statuses = {
        item["extracted_name"]: item["review_status"] for item in result["receipt"]["lines"]
    }
    assert statuses == {
        "Sukari 1kg": "APPLIED",
        "Mafuta ya kupikia 1L": "APPLIED",
        "Mystery item": "SKIPPED",
    }

    # Real movements, real stock, real cost update — through services.inventory.
    movements = await _movements(db_session, a.business_id)
    restocks = [m for m in movements if m.movement_type.value == "RESTOCK"]
    assert {
        (str(m.product_id), str(m.quantity_delta), str(m.unit_cost), m.supplier_name, m.reason)
        for m in restocks
    } == {
        (sugar["id"], "10.000", "135.00", "Kamau Wholesalers", "Delivery 17 Sept"),
        (oil["id"], "2.000", "290.00", "Kamau Wholesalers", "Delivery 17 Sept"),
    }
    products = {p["id"]: p for p in (await api.get("/api/v1/products", headers=a.owner)).json()}
    assert (
        products[sugar["id"]]["stock_quantity"] == "20.000"
        and products[sugar["id"]]["cost_price"] == "135.00"
    )
    assert (
        products[oil["id"]]["stock_quantity"] == "7.000"
        and products[oil["id"]]["cost_price"] == "290.00"
    )
    applied = {
        str(item.movement_id)
        for item in await db_session.scalars(
            select(ReceiptLine)
            .where(ReceiptLine.receipt_id == uuid.UUID(body["id"]))
            .execution_options(populate_existing=True)
        )
        if item.movement_id
    }
    assert applied == {str(m.id) for m in restocks}
    restock_audits = await _audits(db_session, a.business_id, "inventory.restock")
    assert len(restock_audits) == 2 and all(
        (audit.after or {})["receipt_id"] == body["id"] for audit in restock_audits
    )
    confirms = await _audits(db_session, a.business_id, "receipt.confirm")
    assert len(confirms) == 1 and confirms[0].after is not None
    assert confirms[0].after["movements"] == 2 and confirms[0].after["skipped"] == 1

    # A second confirmation is refused and creates nothing.
    again = await confirm(rapi, a.owner, body["id"], decisions)
    assert (
        again.status_code == HTTPStatus.CONFLICT
        and error_code(again) == "RECEIPT_ALREADY_CONFIRMED"
    )
    assert (
        len(
            [
                m
                for m in await _movements(db_session, a.business_id)
                if m.movement_type.value == "RESTOCK"
            ]
        )
        == 2
    )
    assert (
        await rapi.post(f"{RECEIPTS_URL}/{body['id']}/cancel", headers=a.owner)
    ).status_code == HTTPStatus.CONFLICT


@pytest.mark.parametrize(
    ("setup", "expected_status", "code"),
    [
        ("other_business_product", HTTPStatus.NOT_FOUND, "NOT_FOUND"),
        ("forged_product", HTTPStatus.NOT_FOUND, "NOT_FOUND"),
        ("archived_product", HTTPStatus.CONFLICT, "PRODUCT_ARCHIVED"),
        ("untracked_product", HTTPStatus.UNPROCESSABLE_ENTITY, "PRODUCT_UNTRACKED"),
        ("foreign_line", HTTPStatus.UNPROCESSABLE_ENTITY, "RECEIPT_LINE_INVALID"),
    ],
)
async def test_a_bad_line_rolls_back_the_whole_confirmation(
    api: AsyncClient,
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
    setup: str,
    expected_status: HTTPStatus,
    code: str,
) -> None:
    a, b = tenants
    good = await make_product(api, a.owner, name="Sukari 1kg", price="160", cost="135", stock="10")
    if setup == "other_business_product":
        bad_id = (
            await make_product(api, b.owner, name="Beta sugar", price="1", cost="1", stock="1")
        )["id"]
    elif setup == "forged_product":
        bad_id = str(uuid.uuid4())
    elif setup == "archived_product":
        archived = await make_product(api, a.owner, name="Old item", price="1", cost="1", stock="1")
        assert (
            await api.patch(
                f"/api/v1/products/{archived['id']}", headers=a.owner, json={"is_active": False}
            )
        ).status_code == HTTPStatus.OK
        bad_id = archived["id"]
    elif setup == "untracked_product":
        bad_id = (
            await make_product(
                api, a.owner, name="Airtime", price="100", cost=None, stock=None, tracked=False
            )
        )["id"]
    else:
        bad_id = good["id"]
    provider = FakeReceiptExtractionProvider(
        [extraction([line("Sukari 1kg", "10", "135"), line("Second", "1", "10")])]
    )
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    body = await _ready_receipt(rapi, a, provider)
    lines = body["lines"]
    second_line_id = str(uuid.uuid4()) if setup == "foreign_line" else lines[1]["id"]
    decisions = [
        {
            "line_id": lines[0]["id"],
            "product_id": good["id"],
            "quantity": "10",
            "unit_cost": "135",
        },  # valid, first
        {
            "line_id": second_line_id,
            "product_id": bad_id,
            "quantity": "1",
            "unit_cost": "10",
        },  # invalid, second
    ]
    response = await confirm(rapi, a.owner, body["id"], decisions)
    assert response.status_code == expected_status, response.text
    assert error_code(response) == code
    # Nothing landed: no restock movement, stock unchanged, receipt still reviewable.
    assert [
        m for m in await _movements(db_session, a.business_id) if m.movement_type.value == "RESTOCK"
    ] == []
    products = {p["id"]: p for p in (await api.get("/api/v1/products", headers=a.owner)).json()}
    assert products[good["id"]]["stock_quantity"] == "10.000"
    assert (await rapi.get(f"{RECEIPTS_URL}/{body['id']}", headers=a.owner)).json()[
        "status"
    ] == "READY_FOR_REVIEW"


async def test_confirmation_payload_validation(
    api: AsyncClient, api_factory: ApiFactory, tenants: tuple[Tenant, Tenant], storage_dir: str
) -> None:
    a, _ = tenants
    sugar = await make_product(api, a.owner, name="Sukari 1kg", price="160", cost="135", stock="10")
    provider = FakeReceiptExtractionProvider([extraction([line("Sukari 1kg", "10", "135")])])
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    body = await _ready_receipt(rapi, a, provider)
    lid = body["lines"][0]["id"]
    bad = [
        [],
        [{"line_id": lid, "product_id": sugar["id"], "quantity": "0", "unit_cost": "1"}],
        [{"line_id": lid, "product_id": sugar["id"], "quantity": "1", "unit_cost": "-1"}],
        [
            {
                "line_id": lid,
                "product_id": sugar["id"],
                "quantity": "1",
                "unit_cost": "1",
                "business_id": "x",
            }
        ],
        [
            {"line_id": lid, "product_id": sugar["id"], "quantity": "1", "unit_cost": "1"},
            {"line_id": lid, "product_id": sugar["id"], "quantity": "1", "unit_cost": "1"},
        ],
    ]
    for lines in bad:
        response = await confirm(rapi, a.owner, body["id"], lines)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, lines
    unprocessed = await upload_ok(rapi, a.owner)
    not_ready = await confirm(
        rapi,
        a.owner,
        unprocessed["id"],
        [{"line_id": lid, "product_id": sugar["id"], "quantity": "1", "unit_cost": "1"}],
    )
    assert (
        not_ready.status_code == HTTPStatus.CONFLICT
        and error_code(not_ready) == "RECEIPT_INVALID_STATE"
    )


async def test_cancel_and_state_rules(
    api_factory: ApiFactory,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    storage_dir: str,
) -> None:
    a, _ = tenants
    provider = FakeReceiptExtractionProvider([extraction([line("Mkate", "2", "60")])])
    rapi = await make_receipt_api(api_factory, provider, storage_dir)
    receipt = await upload_ok(rapi, a.owner)
    cancelled = await rapi.post(f"{RECEIPTS_URL}/{receipt['id']}/cancel", headers=a.owner)
    assert cancelled.status_code == HTTPStatus.OK and cancelled.json()["status"] == "CANCELLED"
    assert (await rapi.post(f"{RECEIPTS_URL}/{receipt['id']}/cancel", headers=a.owner)).json()[
        "status"
    ] == "CANCELLED"  # idempotent
    blocked = await process(rapi, a.owner, receipt["id"])
    assert (
        blocked.status_code == HTTPStatus.CONFLICT
        and error_code(blocked) == "RECEIPT_INVALID_STATE"
    )
    assert len(await _audits(db_session, a.business_id, "receipt.cancel")) == 1
    # Reprocessing a reviewable receipt is refused too (its lines are the owner's to review).
    ready = await _ready_receipt(rapi, a, provider)
    assert error_code(await process(rapi, a.owner, ready["id"])) == "RECEIPT_INVALID_STATE"


def test_no_business_data_reaches_the_extraction_provider() -> None:
    """The provider contract takes bytes and a MIME type — nothing else exists to send."""
    import inspect

    from app.ai.receipts import ReceiptExtractionProvider

    signature = inspect.signature(ReceiptExtractionProvider.extract)
    assert list(signature.parameters) == ["self", "image", "mime_type"]
    schema = json.dumps(__import__("app.ai.receipts", fromlist=["RECEIPT_TOOL"]).RECEIPT_TOOL)
    assert "business" not in schema and "product_id" not in schema

"""Reusable tenant-isolation check for every tenant-scoped endpoint (ROADMAP Phase 4).

Register a case for each resource type. `test_tenant_isolation.py` runs every
registered case through `assert_tenant_isolated`, which creates the resource in
business B and then, as business A's owner, expects 404 on read, update, delete
and every extra action, and that A's list does not contain it — while B can
still read it. A PR that adds a tenant-scoped endpoint without registering a
case here is incomplete (ROADMAP Phase 4 completion criteria).

The check goes through the real HTTP API with real tokens, so it exercises the
dependency chain, the service and the repository scoping together.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class Tenant:
    """One business and the bearer headers of its owner (and staff, when created)."""

    business_id: str
    owner_user_id: str
    owner: dict[str, str]  # Authorization header for the owner
    staff: dict[str, str] | None = None
    staff_user_id: str | None = None


# Called as the owner of business B; returns the id to substitute into the URLs.
Creator = Callable[[AsyncClient, AsyncSession, Tenant], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class IsolationCase:
    name: str
    create_in: Creator
    read_url: Callable[[str], str]
    list_url: str | None = None
    # (method, url-from-id, JSON body) — each must be a 404 for the other tenant.
    mutations: tuple[tuple[str, Callable[[str], str], dict[str, Any] | None], ...] = field(
        default_factory=tuple
    )
    delete_url: Callable[[str], str] | None = None


async def assert_tenant_isolated(
    api: AsyncClient, session: AsyncSession, case: IsolationCase, a: Tenant, b: Tenant
) -> None:
    resource_id = await case.create_in(api, session, b)

    # The owner can see it: the resource is real and the URL is right.
    own = await api.get(case.read_url(resource_id), headers=b.owner)
    assert own.status_code == HTTPStatus.OK, (case.name, own.text)

    # Another business: not found, never forbidden, and never any of its data.
    other = await api.get(case.read_url(resource_id), headers=a.owner)
    assert other.status_code == HTTPStatus.NOT_FOUND, (case.name, other.text)
    assert other.json()["error"]["code"] == "NOT_FOUND"
    assert resource_id not in other.text

    for method, url_for, body in case.mutations:
        response = await api.request(method, url_for(resource_id), headers=a.owner, json=body)
        assert response.status_code == HTTPStatus.NOT_FOUND, (case.name, method, response.text)
    if case.delete_url is not None:
        response = await api.delete(case.delete_url(resource_id), headers=a.owner)
        assert response.status_code == HTTPStatus.NOT_FOUND, (case.name, response.text)

    if case.list_url is not None:
        listing = await api.get(case.list_url, headers=a.owner)
        assert listing.status_code == HTTPStatus.OK, (case.name, listing.text)
        assert resource_id not in listing.text, case.name

    # Nothing above changed the resource for its real owner.
    still = await api.get(case.read_url(resource_id), headers=b.owner)
    assert still.status_code == HTTPStatus.OK and still.json() == own.json(), case.name

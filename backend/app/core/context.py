"""Request-derived context objects shared by the API layer and services.

Defined here (not in `app.api.deps`) so services can type their parameters
without importing the HTTP layer.
"""

import uuid
from dataclasses import dataclass

from app.models.enums import MembershipRole


@dataclass(frozen=True, slots=True)
class BusinessContext:
    """What every business-scoped service call receives (docs/ARCHITECTURE.md §3.3).

    Built by `get_business_context` from the verified membership row on every
    request; nothing in it comes from the client.
    """

    user_id: uuid.UUID
    business_id: uuid.UUID
    role: MembershipRole
    timezone: str
    settings: dict[str, object]


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Where a request came from; stored on refresh tokens for "logout everywhere" UX."""

    ip: str | None
    user_agent: str | None

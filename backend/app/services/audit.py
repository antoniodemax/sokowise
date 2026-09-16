"""Audit logging (docs/DATA_MAPPING.md §3.16, PRD FR-K1).

`record` adds an `audit_logs` row to the *caller's* transaction and never commits:
the row lands together with the change it describes, or not at all. Services
call it after the mutation, inside the same `transaction(session)` block.

Action naming: `<entity>.<verb>`, lower snake case, stable (they are queried, not
displayed). Phase 4 actions: `business.update`, `user.create`, `user.role_change`,
`user.deactivate`, `user.reactivate`, `user.password_reset`. Later phases add
their own following DATA_MAPPING §3.16 (`sale.void`, `inventory.adjust`, …).

`before`/`after` hold only the fields that changed, as JSON-safe values. Never
pass secrets: password hashes, tokens, cookies or headers do not belong here,
and the schemas that feed this function do not carry them.
"""

import logging
import uuid
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.models import AuditLog
from app.repositories import audit_logs as audit_repo

logger = logging.getLogger(__name__)


class AuditAction(StrEnum):
    BUSINESS_UPDATE = "business.update"
    USER_CREATE = "user.create"
    USER_ROLE_CHANGE = "user.role_change"
    USER_DEACTIVATE = "user.deactivate"
    USER_REACTIVATE = "user.reactivate"
    USER_PASSWORD_RESET = "user.password_reset"  # noqa: S105 — an action name, not a secret


# Keys that must never appear in an audit payload, whatever a caller passes.
_FORBIDDEN_KEYS = frozenset(
    {"password", "password_hash", "new_password", "current_password", "token", "token_hash"}
)


def _scrub(payload: dict[str, object] | None) -> dict[str, object] | None:
    if payload is None:
        return None
    return {key: value for key, value in payload.items() if key not in _FORBIDDEN_KEYS}


async def record(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    action: AuditAction,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    client: ClientInfo | None = None,
) -> AuditLog:
    entry = AuditLog(
        business_id=ctx.business_id,
        actor_user_id=ctx.user_id,
        action=action.value,
        entity_type=entity_type,
        entity_id=entity_id,
        before=_scrub(before),
        after=_scrub(after),
        ip=client.ip[:45] if client and client.ip else None,
        user_agent=client.user_agent[:255] if client and client.user_agent else None,
    )
    await audit_repo.add(session, entry)
    # The request ID is bound to this log line, which is how an audit row is correlated
    # with a request (the table has no request_id column; DATA_MAPPING §3.16).
    logger.info(
        "audit",
        extra={
            "audit_id": str(entry.id),
            "business_id": str(ctx.business_id),
            "actor_user_id": str(ctx.user_id),
            "action": action.value,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        },
    )
    return entry

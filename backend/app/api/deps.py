"""Request dependencies: authentication, business context, roles, CSRF and rate limits
(docs/ARCHITECTURE.md §3.3, §5).

The chain for a business endpoint is

    get_access_claims  → verify the bearer JWT (signature, expiry, type, claims)
    get_current_user   → load the user; must exist and be active
    get_business_context
                       → load the membership for (user, token.bid) and its business;
                         both must be active; role comes from the membership row;
                         reject if the user must change their password
    require_role(...)  → compare the membership role with the route's requirement

Nothing about authorization is taken from the token or the request body: `bid`
only selects which membership to verify, and the role is whatever that row says
right now.
"""

import re
from collections.abc import Callable, Coroutine
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import PermissionDeniedError, RateLimitedError, UnauthorizedError
from app.core.ratelimit import RateLimiter
from app.core.tokens import AccessTokenClaims, InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models import User
from app.models.enums import MembershipRole
from app.repositories import businesses as business_repo
from app.repositories import users as user_repo

# The custom header that cookie-authenticated endpoints require (ARCHITECTURE §5.1). A
# cross-site form cannot set it, and a cross-origin fetch that sets it triggers a CORS
# preflight that only allow-listed origins pass.
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "sokowise"

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def client_ip(request: Request) -> str:
    # Behind a reverse proxy uvicorn must run with --proxy-headers so this is the
    # real client address (deployment detail for Phase 15).
    return request.client.host if request.client else "unknown"


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


def enforce_rate_limit(request: Request, *, scope: str, key: str, limit: int) -> None:
    """Count one attempt under `scope:key`; 429 with Retry-After once over `limit` per minute."""
    retry_after = get_rate_limiter(request).hit(f"{scope}:{key}", limit=limit)
    if retry_after is not None:
        raise RateLimitedError(
            "Too many attempts; try again shortly", retry_after_seconds=max(1, int(retry_after) + 1)
        )


def require_trusted_origin(request: Request) -> None:
    """Reject a browser request whose Origin is not an allowed frontend origin.

    Non-browser clients send no Origin header and pass; browsers always send one on
    cross-origin POSTs, and a `null` Origin (sandboxed frames, some redirects) is rejected.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return
    settings = get_settings_dep(request)
    if origin in settings.cors_origins:
        return
    if settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin):
        return
    raise PermissionDeniedError("Request origin is not allowed", code="CSRF_REJECTED")


def require_csrf_header(request: Request) -> None:
    """Cookie-bearing endpoints also need the custom header, on top of the Origin check."""
    require_trusted_origin(request)
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise PermissionDeniedError(
            f"Missing {CSRF_HEADER}: {CSRF_HEADER_VALUE} header", code="CSRF_REJECTED"
        )


def get_access_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AccessTokenClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Authentication required")
    try:
        return decode_access_token(get_settings_dep(request), credentials.credentials)
    except InvalidTokenError:
        raise UnauthorizedError("Invalid or expired token") from None


async def get_current_user(
    claims: Annotated[AccessTokenClaims, Depends(get_access_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    user = await user_repo.get_user_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired token")
    return user


async def get_business_context(
    claims: Annotated[AccessTokenClaims, Depends(get_access_claims)],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BusinessContext:
    membership = await user_repo.get_membership(
        session, user_id=user.id, business_id=claims.business_id
    )
    if membership is None:
        # The token names a business this user has never belonged to: not a valid session.
        raise UnauthorizedError("Invalid or expired token")
    if not membership.is_active:
        raise PermissionDeniedError(
            "Your access to this business is inactive", code="MEMBERSHIP_INACTIVE"
        )
    business = await business_repo.get_business(session, membership.business_id)
    if business is None or not business.is_active:
        raise PermissionDeniedError("This business is inactive", code="BUSINESS_INACTIVE")
    if user.must_change_password:
        raise PermissionDeniedError(
            "You must change your password before continuing", code="PASSWORD_CHANGE_REQUIRED"
        )
    return BusinessContext(
        user_id=user.id,
        business_id=business.id,
        role=membership.role,
        timezone=business.timezone,
        settings=dict(business.settings),
    )


def require_role(
    *roles: MembershipRole,
) -> Callable[..., Coroutine[None, None, BusinessContext]]:
    """Dependency factory: the membership role must be one of `roles`.

    `require_role(OWNER)` is owner-only; `require_role(OWNER, STAFF)` is any member.
    STAFF never implies OWNER.
    """
    allowed = frozenset(roles)

    async def dependency(
        ctx: Annotated[BusinessContext, Depends(get_business_context)],
    ) -> BusinessContext:
        if ctx.role not in allowed:
            raise PermissionDeniedError("You do not have permission to do this")
        return ctx

    return dependency


require_owner = require_role(MembershipRole.OWNER)
require_member = require_role(MembershipRole.OWNER, MembershipRole.STAFF)

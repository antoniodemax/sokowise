"""Registration, login, refresh, logout and password change (docs/ARCHITECTURE.md §5).

Each public function owns its transaction (`async with transaction(session)`), so the
multi-row writes (register: user + business + membership; refresh: revoke +
issue) are visibly atomic. Nothing here logs passwords, tokens or hashes; log
lines carry ids only.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import GoogleIdentity
from app.core.config import Settings
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, PermissionDeniedError, UnauthorizedError
from app.core.passwords import DUMMY_PASSWORD_HASH, hash_password, needs_rehash, verify_password
from app.core.tokens import (
    InvalidTokenError,
    SignupTokenClaims,
    create_access_token,
    create_signup_token,
    decode_signup_token,
    generate_refresh_token,
    generate_reset_code,
    hash_refresh_token,
    hash_reset_code,
)
from app.db.session import transaction
from app.models import Business, BusinessMembership, User
from app.models.enums import MembershipRole
from app.notifications.sms import SmsDeliveryError, SmsSender
from app.repositories import businesses as business_repo
from app.repositories import password_resets as reset_repo
from app.repositories import refresh_tokens as token_repo
from app.repositories import users as user_repo
from app.schemas.auth import (
    ChangePasswordRequest,
    GoogleRegisterRequest,
    LoginRequest,
    RegisterRequest,
)
from app.schemas.identifiers import looks_like_email, normalize_email, normalize_phone
from app.services import audit
from app.services.audit import AuditAction

logger = logging.getLogger(__name__)

_USER_UNIQUE_CONSTRAINTS = ("uq_users_phone", "uq_users_email", "uq_users_google_sub")


@dataclass(frozen=True, slots=True)
class AuthSession:
    """A freshly issued session. `refresh_token` is the raw value for the cookie only."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: User
    business: Business
    role: MembershipRole


class InvalidCurrentPasswordError(AppError):
    status_code = 400
    code = "INVALID_CURRENT_PASSWORD"


def _invalid_credentials() -> UnauthorizedError:
    # One message for unknown identifier, wrong password and deactivated user, so the
    # response does not say which (account enumeration).
    return UnauthorizedError("Invalid phone/email or password", code="INVALID_CREDENTIALS")


def _invalid_refresh() -> UnauthorizedError:
    return UnauthorizedError("Session is no longer valid", code="INVALID_REFRESH_TOKEN")


async def _resolve_active_membership(
    session: AsyncSession, user: User
) -> tuple[BusinessMembership, Business]:
    """The membership a session is opened for, with its business; both must be active.

    MVP exposes one business per user (PRD FR-A4). If a user ever has several active
    memberships the oldest wins until business switching exists; that ordering is
    deterministic, not a product decision.
    """
    memberships = await user_repo.list_memberships(session, user.id)
    membership = next((m for m in memberships if m.is_active), None)
    if membership is None:
        raise PermissionDeniedError(
            "Your access to this business is inactive", code="MEMBERSHIP_INACTIVE"
        )
    business = await business_repo.get_business(session, membership.business_id)
    if business is None or not business.is_active:
        raise PermissionDeniedError("This business is inactive", code="BUSINESS_INACTIVE")
    return membership, business


async def _issue_session(
    session: AsyncSession,
    settings: Settings,
    *,
    user: User,
    business: Business,
    role: MembershipRole,
    client: ClientInfo,
    family_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
) -> AuthSession:
    """Create an access token and a refresh-token row (new family unless `family_id` given)."""
    access_token, access_expires_at = create_access_token(
        settings, user_id=user.id, business_id=business.id
    )
    raw_refresh = generate_refresh_token()
    refresh_expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
    await token_repo.create_refresh_token(
        session,
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=refresh_expires_at,
        family_id=family_id,
        parent_id=parent_id,
        user_agent=client.user_agent[:255] if client.user_agent else None,
        ip=client.ip[:45] if client.ip else None,
    )
    return AuthSession(
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=raw_refresh,
        refresh_expires_at=refresh_expires_at,
        user=user,
        business=business,
        role=role,
    )


async def register(
    session: AsyncSession, settings: Settings, data: RegisterRequest, client: ClientInfo
) -> AuthSession:
    """Create user + business + OWNER membership atomically and open a session (PRD FR-A1/A2).

    The role is fixed here; the request model has no role field. Uniqueness of phone
    and email is left to the database constraints, so two concurrent registrations
    with the same phone cannot both succeed.
    """
    user = User(
        phone=data.phone,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
    )
    business = Business(
        name=data.business_name, business_type=data.business_type, timezone=data.timezone
    )
    return await _create_owner_account(
        session, settings, user=user, business=business, client=client
    )


async def _create_owner_account(
    session: AsyncSession,
    settings: Settings,
    *,
    user: User,
    business: Business,
    client: ClientInfo,
) -> AuthSession:
    try:
        async with transaction(session):
            session.add_all([user, business])
            await session.flush()
            session.add(
                BusinessMembership(
                    business_id=business.id, user_id=user.id, role=MembershipRole.OWNER
                )
            )
            await session.flush()
            await session.refresh(user)
            await session.refresh(business)
            auth = await _issue_session(
                session,
                settings,
                user=user,
                business=business,
                role=MembershipRole.OWNER,
                client=client,
            )
    except IntegrityError as exc:
        if any(name in str(exc.orig) for name in _USER_UNIQUE_CONSTRAINTS):
            # Says "an account exists", not which identifier or whose: the phone/email
            # pair is the caller's own input, and register is rate-limited per IP.
            raise ConflictError(
                "An account with this phone number or email already exists",
                code="ACCOUNT_EXISTS",
            ) from None
        raise
    logger.info("user registered", extra={"user_id": str(user.id), "business_id": str(business.id)})
    return auth


async def _find_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    try:
        if looks_like_email(identifier):
            return await user_repo.get_user_by_email(session, normalize_email(identifier))
        return await user_repo.get_user_by_phone(session, normalize_phone(identifier))
    except ValueError:
        return None


async def login(
    session: AsyncSession, settings: Settings, data: LoginRequest, client: ClientInfo
) -> AuthSession:
    async with transaction(session):
        user = await _find_user_by_identifier(session, data.identifier)
        if user is None:
            # Same cost as a real verification so timing does not reveal unknown accounts.
            verify_password(DUMMY_PASSWORD_HASH, data.password)
            logger.warning("login failed", extra={"reason": "unknown_identifier"})
            raise _invalid_credentials()
        if user.password_hash is None:
            # A Google-only account: same cost and same answer as a wrong password, so the
            # response never reveals how the account was created.
            verify_password(DUMMY_PASSWORD_HASH, data.password)
            logger.warning("login failed", extra={"reason": "no_password", "user_id": str(user.id)})
            raise _invalid_credentials()
        if not verify_password(user.password_hash, data.password):
            logger.warning(
                "login failed", extra={"reason": "bad_password", "user_id": str(user.id)}
            )
            raise _invalid_credentials()
        if not user.is_active:
            logger.warning(
                "login failed", extra={"reason": "user_inactive", "user_id": str(user.id)}
            )
            raise _invalid_credentials()
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        membership, business = await _resolve_active_membership(session, user)
        user.last_login_at = datetime.now(UTC)
        auth = await _issue_session(
            session,
            settings,
            user=user,
            business=business,
            role=membership.role,
            client=client,
        )
    logger.info("login succeeded", extra={"user_id": str(user.id), "business_id": str(business.id)})
    return auth


async def refresh(
    session: AsyncSession, settings: Settings, raw_token: str, client: ClientInfo
) -> AuthSession:
    """Rotate a refresh token: revoke the presented one, issue a child in the same family.

    A token that is already revoked is treated as reuse — someone (the legitimate
    client or a thief) is replaying a value that was consumed — and the whole family
    is revoked so both parties lose the session. That revocation is committed even
    though the request fails.
    """
    token_hash = hash_refresh_token(raw_token)
    auth: AuthSession | None = None
    async with transaction(session):
        row = await token_repo.consume(session, token_hash)
        if row is None:
            existing = await token_repo.get_by_hash(session, token_hash)
            if existing is not None and existing.revoked_at is not None:
                revoked = await token_repo.revoke_family(session, existing.family_id)
                logger.warning(
                    "refresh token reuse detected; family revoked",
                    extra={
                        "user_id": str(existing.user_id),
                        "family_id": str(existing.family_id),
                        "revoked": revoked,
                    },
                )
            # Unknown or expired tokens fall through with nothing to revoke.
        else:
            user = await user_repo.get_user_by_id(session, row.user_id)
            if user is None or not user.is_active:
                await token_repo.revoke_family(session, row.family_id)
            else:
                # Membership/business checks raise 403 and roll this transaction back,
                # which un-consumes the token: the session survives a temporary
                # deactivation and fails only while it lasts.
                membership, business = await _resolve_active_membership(session, user)
                auth = await _issue_session(
                    session,
                    settings,
                    user=user,
                    business=business,
                    role=membership.role,
                    client=client,
                    family_id=row.family_id,
                    parent_id=row.id,
                )
    if auth is None:
        raise _invalid_refresh()
    return auth


async def get_business_for_context(session: AsyncSession, ctx: BusinessContext) -> Business:
    """The (already verified) business of the current request, for `GET /auth/me`."""
    business = await business_repo.get_business(session, ctx.business_id)
    if business is None:  # pragma: no cover — get_business_context just loaded it
        raise PermissionDeniedError("This business is inactive", code="BUSINESS_INACTIVE")
    return business


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    """Revoke the family of the presented refresh token. Idempotent; unknown tokens are ignored."""
    if not raw_token:
        return
    async with transaction(session):
        row = await token_repo.get_by_hash(session, hash_refresh_token(raw_token))
        if row is not None:
            await token_repo.revoke_family(session, row.family_id)
            logger.info(
                "logout", extra={"user_id": str(row.user_id), "family_id": str(row.family_id)}
            )


async def logout_all(session: AsyncSession, user: User) -> None:
    """Revoke every refresh token the user has, on every device."""
    async with transaction(session):
        revoked = await token_repo.revoke_all_for_user(session, user.id)
    logger.info("logout all", extra={"user_id": str(user.id), "revoked": revoked})


async def change_password(
    session: AsyncSession,
    settings: Settings,
    user: User,
    data: ChangePasswordRequest,
    client: ClientInfo,
) -> AuthSession:
    """Set a new password, clear `must_change_password`, and replace every session.

    All existing refresh tokens are revoked (a changed password should log out any
    device the old one was used on) and a fresh session is issued to the caller so
    they are not logged out themselves.
    """
    async with transaction(session):
        if user.password_hash is None or not verify_password(
            user.password_hash, data.current_password
        ):
            raise InvalidCurrentPasswordError("Current password is incorrect")
        membership, business = await _resolve_active_membership(session, user)
        user.password_hash = hash_password(data.new_password)
        user.must_change_password = False
        await session.flush()
        await token_repo.revoke_all_for_user(session, user.id)
        auth = await _issue_session(
            session,
            settings,
            user=user,
            business=business,
            role=membership.role,
            client=client,
        )
    logger.info("password changed", extra={"user_id": str(user.id)})
    return auth


# --- Sign in with Google (ARCHITECTURE §5.1) ---


@dataclass(frozen=True, slots=True)
class PendingGoogleSignup:
    """A verified Google identity with no SokoWise account yet: finish-up form needed."""

    registration_token: str
    email: str
    name: str | None


class InvalidSignupTokenError(UnauthorizedError):
    code = "SIGNUP_TOKEN_INVALID"


async def google_sign_in(
    session: AsyncSession, settings: Settings, identity: GoogleIdentity, client: ClientInfo
) -> AuthSession | PendingGoogleSignup:
    """Open a session for the account linked to this Google identity, linking by verified
    email on first use; otherwise hand back a short-lived signup token."""
    try:
        email = normalize_email(identity.email)
    except ValueError:
        raise _invalid_credentials() from None
    async with transaction(session):
        user = await user_repo.get_user_by_google_sub(session, identity.sub)
        if user is None:
            user = await user_repo.get_user_by_email(session, email)
            if user is not None and user.google_sub is None:
                user.google_sub = identity.sub
                logger.info("google identity linked", extra={"user_id": str(user.id)})
        if user is None:
            claims = SignupTokenClaims(google_sub=identity.sub, email=email, name=identity.name)
            return PendingGoogleSignup(
                registration_token=create_signup_token(settings, claims),
                email=email,
                name=identity.name,
            )
        if not user.is_active:
            logger.warning(
                "login failed", extra={"reason": "user_inactive", "user_id": str(user.id)}
            )
            raise _invalid_credentials()
        membership, business = await _resolve_active_membership(session, user)
        user.last_login_at = datetime.now(UTC)
        auth = await _issue_session(
            session, settings, user=user, business=business, role=membership.role, client=client
        )
    logger.info(
        "login succeeded",
        extra={"user_id": str(user.id), "business_id": str(business.id), "method": "google"},
    )
    return auth


async def google_register(
    session: AsyncSession, settings: Settings, data: GoogleRegisterRequest, client: ClientInfo
) -> AuthSession:
    """Finish a Google sign-up: the email comes from the signed token, never the form."""
    try:
        claims = decode_signup_token(settings, data.registration_token)
    except InvalidTokenError:
        raise InvalidSignupTokenError("Start again with the Google button") from None
    user = User(
        phone=data.phone,
        email=claims.email,
        full_name=data.full_name or claims.name or claims.email.split("@")[0],
        password_hash=None,
        google_sub=claims.google_sub,
    )
    business = Business(
        name=data.business_name, business_type=data.business_type, timezone=data.timezone
    )
    return await _create_owner_account(
        session, settings, user=user, business=business, client=client
    )


# --- Self-service password reset by SMS (ARCHITECTURE §5.1) ---

RESET_CODE_TTL = timedelta(minutes=10)


class ResetCodeError(AppError):
    status_code = 400
    code = "RESET_CODE_INVALID"


class SmsUnavailableError(AppError):
    status_code = 503
    code = "SMS_UNAVAILABLE"


def _reset_sms_text(code: str) -> str:
    return (
        f"SokoWise: your code is {code}. It expires in 10 minutes. "
        "If you did not ask for it, ignore this message."
    )


async def request_password_reset(
    session: AsyncSession, sms: SmsSender, phone: str, client: ClientInfo
) -> None:
    """Send a code when the phone belongs to an active account; silent otherwise.

    The caller always answers 202, so the response never reveals whether a phone is
    registered. The SMS is sent after the row is committed; a delivery failure is
    reported (503) because the person is waiting for it.
    """
    try:
        normalized = normalize_phone(phone)
    except ValueError:
        return
    async with transaction(session):
        user = await user_repo.get_user_by_phone(session, normalized)
        if user is None or not user.is_active:
            logger.info("password reset requested", extra={"reason": "unknown_or_inactive"})
            return
        await reset_repo.expire_open_codes(session, user.id)
        code = generate_reset_code()
        await reset_repo.create_code(
            session,
            user_id=user.id,
            code_hash=hash_reset_code(user.id, code),
            expires_at=datetime.now(UTC) + RESET_CODE_TTL,
            ip=client.ip[:45] if client.ip else None,
        )
    try:
        await sms.send(normalized, _reset_sms_text(code))
    except SmsDeliveryError:
        raise SmsUnavailableError(
            "We could not send the SMS right now. Please try again in a few minutes."
        ) from None
    logger.info("password reset requested", extra={"user_id": str(user.id)})


async def confirm_password_reset(
    session: AsyncSession, phone: str, code: str, new_password: str, client: ClientInfo
) -> None:
    """Set the password when `code` is the live code for `phone`; count wrong guesses.

    Every failure answers the same 400 RESET_CODE_INVALID. Success revokes every session
    (like a password change) and clears `must_change_password`; a Google-only account
    gets its first password this way.
    """
    invalid = ResetCodeError("That code is not valid. Ask for a new one.")
    try:
        normalized = normalize_phone(phone)
    except ValueError:
        raise invalid from None
    async with transaction(session):
        user = await user_repo.get_user_by_phone(session, normalized)
        if user is None or not user.is_active:
            raise invalid
        consumed = await reset_repo.consume(
            session, user_id=user.id, code_hash=hash_reset_code(user.id, code)
        )
    if consumed is None:
        # Counted in its own transaction so the guess is kept even though we then fail.
        async with transaction(session):
            open_code = await reset_repo.latest_open_code(session, user.id)
            if open_code is not None:
                await reset_repo.count_attempt(session, open_code.id)
        logger.warning("password reset failed", extra={"user_id": str(user.id)})
        raise invalid
    async with transaction(session):
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        await session.flush()
        await token_repo.revoke_all_for_user(session, user.id)
        membership, _ = await _resolve_active_membership(session, user)
        await audit.record(
            session,
            BusinessContext(
                user_id=user.id,
                business_id=membership.business_id,
                membership_id=membership.id,
                role=membership.role,
                timezone="UTC",
                settings={},
            ),
            action=AuditAction.USER_PASSWORD_RESET,
            entity_type="user",
            entity_id=user.id,
            after={"method": "sms_code"},
            client=client,
        )
    logger.info("password reset completed", extra={"user_id": str(user.id)})

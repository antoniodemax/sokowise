"""Authentication endpoints (docs/ARCHITECTURE.md §5, ROADMAP Phase 3).

Transport: the access token is returned in the body and sent back as
`Authorization: Bearer`; the refresh token travels only in an HttpOnly cookie
scoped to this router's path, so no other endpoint ever receives it. The
cookie-consuming endpoints (refresh, logout) require the CSRF header.
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    client_ip,
    enforce_rate_limit,
    get_business_context,
    get_client_info,
    get_current_user,
    get_settings_dep,
    is_platform_admin,
    require_csrf_header,
    require_trusted_origin,
)
from app.auth.google import GoogleTokenError, GoogleVerifier
from app.core.config import Settings
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, UnauthorizedError
from app.db.session import get_session
from app.models import User
from app.notifications.sms import SmsSender
from app.schemas.auth import (
    BusinessOut,
    ChangePasswordRequest,
    GoogleRegisterRequest,
    GoogleSignInRequest,
    GoogleSignupPendingResponse,
    LoginRequest,
    MeResponse,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    RegisterRequest,
    SessionResponse,
    UserOut,
)
from app.services import auth as auth_service
from app.services.auth import AuthSession

REFRESH_COOKIE_NAME = "sokowise_refresh"
# Only the auth endpoints ever see the cookie; it is not sent to the rest of the API.
REFRESH_COOKIE_PATH = "/api/v1/auth"

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]


def set_refresh_cookie(response: Response, settings: Settings, auth: AuthSession) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=auth.refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _clearing_cookie_header(settings: Settings) -> str:
    """The Set-Cookie value that deletes the refresh cookie, for attaching to an error."""
    scratch = Response()
    clear_refresh_cookie(scratch, settings)
    return scratch.headers["set-cookie"]


def _session_response(auth: AuthSession, settings: Settings) -> SessionResponse:
    return SessionResponse(
        access_token=auth.access_token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(auth.user, from_attributes=True),
        business=BusinessOut.model_validate(auth.business, from_attributes=True),
        role=auth.role,
        is_platform_admin=is_platform_admin(settings, auth.user),
    )


class GoogleNotConfiguredError(AppError):
    status_code = 503
    code = "GOOGLE_NOT_CONFIGURED"


class PasswordResetNotConfiguredError(AppError):
    status_code = 503
    code = "PASSWORD_RESET_NOT_CONFIGURED"


def get_google_verifier(request: Request) -> GoogleVerifier:
    verifier: GoogleVerifier | None = getattr(request.app.state, "google_verifier", None)
    if verifier is None:
        raise GoogleNotConfiguredError("Sign in with Google is not set up on this server yet.")
    return verifier


def get_sms_sender(request: Request) -> SmsSender:
    sender: SmsSender | None = getattr(request.app.state, "sms_sender", None)
    if sender is None:
        raise PasswordResetNotConfiguredError(
            "Password reset by SMS is not switched on in this version yet."
        )
    return sender


GoogleVerifierDep = Annotated[GoogleVerifier, Depends(get_google_verifier)]
SmsDep = Annotated[SmsSender, Depends(get_sms_sender)]


@router.post(
    "/register",
    status_code=HTTPStatus.CREATED,
    response_model=SessionResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> SessionResponse:
    enforce_rate_limit(
        request,
        scope="register:ip",
        key=client_ip(request),
        limit=settings.rate_limit_register_per_minute,
    )
    auth = await auth_service.register(session, settings, payload, client)
    set_refresh_cookie(response, settings, auth)
    return _session_response(auth, settings)


@router.post(
    "/login", response_model=SessionResponse, dependencies=[Depends(require_trusted_origin)]
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> SessionResponse:
    limit = settings.rate_limit_login_per_minute
    enforce_rate_limit(request, scope="login:ip", key=client_ip(request), limit=limit)
    # Per identifier as well, so one account cannot be brute-forced from many addresses.
    # Counted whether or not the account exists, so the 429 says nothing about that.
    enforce_rate_limit(request, scope="login:id", key=payload.identifier.lower(), limit=limit)
    auth = await auth_service.login(session, settings, payload, client)
    set_refresh_cookie(response, settings, auth)
    return _session_response(auth, settings)


@router.post(
    "/refresh", response_model=SessionResponse, dependencies=[Depends(require_csrf_header)]
)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> SessionResponse:
    enforce_rate_limit(
        request,
        scope="refresh:ip",
        key=client_ip(request),
        limit=settings.rate_limit_refresh_per_minute,
    )
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise UnauthorizedError(
            "Session is no longer valid",
            code="INVALID_REFRESH_TOKEN",
            headers={"WWW-Authenticate": "Bearer", "Set-Cookie": _clearing_cookie_header(settings)},
        )
    try:
        auth = await auth_service.refresh(session, settings, raw_token, client)
    except UnauthorizedError as exc:
        # A dead token is useless to the client; the error response deletes the cookie.
        exc.headers = {**(exc.headers or {}), "Set-Cookie": _clearing_cookie_header(settings)}
        raise
    set_refresh_cookie(response, settings, auth)
    return _session_response(auth, settings)


@router.post(
    "/logout",
    status_code=HTTPStatus.NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
)
async def logout(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    await auth_service.logout(session, request.cookies.get(REFRESH_COOKIE_NAME))
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    clear_refresh_cookie(response, settings)
    return response


@router.post("/logout-all", status_code=HTTPStatus.NO_CONTENT)
async def logout_all(
    user: Annotated[User, Depends(get_current_user)], session: SessionDep, settings: SettingsDep
) -> Response:
    await auth_service.logout_all(session, user)
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    clear_refresh_cookie(response, settings)
    return response


@router.post(
    "/change-password",
    response_model=SessionResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> SessionResponse:
    enforce_rate_limit(
        request,
        scope="change-password:user",
        key=str(user.id),
        limit=settings.rate_limit_password_change_per_minute,
    )
    auth = await auth_service.change_password(session, settings, user, payload, client)
    set_refresh_cookie(response, settings, auth)
    return _session_response(auth, settings)


@router.get("/me", response_model=MeResponse)
async def me(
    ctx: Annotated[BusinessContext, Depends(get_business_context)],
    user: Annotated[User, Depends(get_current_user)],
    session: SessionDep,
    settings: SettingsDep,
) -> MeResponse:
    business = await auth_service.get_business_for_context(session, ctx)
    return MeResponse(
        user=UserOut.model_validate(user, from_attributes=True),
        business=BusinessOut.model_validate(business, from_attributes=True),
        role=ctx.role,
        is_platform_admin=is_platform_admin(settings, user),
    )


@router.post(
    "/google",
    response_model=SessionResponse | GoogleSignupPendingResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def google_sign_in(
    payload: GoogleSignInRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
    verifier: GoogleVerifierDep,
) -> SessionResponse | GoogleSignupPendingResponse:
    enforce_rate_limit(
        request,
        scope="login:ip",
        key=client_ip(request),
        limit=settings.rate_limit_login_per_minute,
    )
    try:
        identity = verifier.verify(payload.credential)
    except GoogleTokenError:
        raise UnauthorizedError(
            "Google did not confirm that account", code="GOOGLE_TOKEN_INVALID"
        ) from None
    result = await auth_service.google_sign_in(session, settings, identity, client)
    if isinstance(result, auth_service.PendingGoogleSignup):
        return GoogleSignupPendingResponse(
            registration_token=result.registration_token, email=result.email, name=result.name
        )
    set_refresh_cookie(response, settings, result)
    return _session_response(result, settings)


@router.post(
    "/google/register",
    status_code=HTTPStatus.CREATED,
    response_model=SessionResponse,
    dependencies=[Depends(require_trusted_origin), Depends(get_google_verifier)],
)
async def google_register(
    payload: GoogleRegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> SessionResponse:
    enforce_rate_limit(
        request,
        scope="register:ip",
        key=client_ip(request),
        limit=settings.rate_limit_register_per_minute,
    )
    auth = await auth_service.google_register(session, settings, payload, client)
    set_refresh_cookie(response, settings, auth)
    return _session_response(auth, settings)


@router.post(
    "/password-reset/request",
    status_code=HTTPStatus.ACCEPTED,
    response_model=MessageResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def password_reset_request(
    payload: PasswordResetRequestRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
    sms: SmsDep,
) -> MessageResponse:
    _reset_rate_limits(request, settings, payload.phone, step="request")
    await auth_service.request_password_reset(session, sms, payload.phone, client)
    return MessageResponse(
        message="If that phone number has an account, a code is on its way by SMS."
    )


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    dependencies=[Depends(require_trusted_origin), Depends(get_sms_sender)],
)
async def password_reset_confirm(
    payload: PasswordResetConfirmRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
) -> MessageResponse:
    _reset_rate_limits(request, settings, payload.phone, step="confirm")
    await auth_service.confirm_password_reset(
        session, payload.phone, payload.code, payload.new_password, client
    )
    return MessageResponse(message="Your password is changed. Sign in with the new one.")


def _reset_rate_limits(request: Request, settings: Settings, phone: str, *, step: str) -> None:
    """Per IP for both steps; per phone: few SMS requests, more room for code typos."""
    enforce_rate_limit(
        request,
        scope=f"password-reset-{step}:ip",
        key=client_ip(request),
        limit=settings.rate_limit_password_reset_per_minute,
    )
    enforce_rate_limit(
        request,
        scope=f"password-reset-{step}:phone",
        key=phone.strip().lower(),
        limit=settings.rate_limit_password_reset_per_phone_per_minute
        if step == "request"
        else settings.rate_limit_password_reset_confirm_per_phone_per_minute,
    )

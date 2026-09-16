"""Request-ID middleware (docs/ARCHITECTURE.md §3.3 step 1, §9).

Each request gets an ID that is bound to the logging context, returned in the
`X-Request-ID` response header and included in every error envelope. A client
may supply its own `X-Request-ID`; it is kept only when it looks like an
identifier (1-64 characters of [A-Za-z0-9._-]) so log lines cannot be polluted.

This is a pure ASGI middleware rather than `BaseHTTPMiddleware` so that an
unhandled exception is turned into the error envelope *while the request ID is
still bound*; Starlette's own server-error handler runs outside this layer and
would otherwise produce a response with no request ID.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_exception_handler
from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

logger = logging.getLogger("app.access")


def resolve_request_id(candidate: str | None) -> str:
    if candidate is not None and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 0
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                if response_started:
                    raise  # too late to replace a response that is already streaming
                response = await unhandled_exception_handler(Request(scope), exc)
                await response(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )

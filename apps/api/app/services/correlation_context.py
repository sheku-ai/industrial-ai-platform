from __future__ import annotations

import contextvars
import logging
import re
import uuid
from time import perf_counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

CORRELATION_HEADER = "X-Correlation-ID"
MAX_CORRELATION_LENGTH = 128
_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
logger = logging.getLogger("app.http")


def normalize_correlation_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return str(uuid.uuid4())
    if len(candidate) > MAX_CORRELATION_LENGTH or _SAFE_CORRELATION.fullmatch(candidate) is None:
        raise ValueError("invalid correlation id")
    return candidate


def current_correlation_id() -> str | None:
    return _correlation_id.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        try:
            correlation_id = normalize_correlation_id(request.headers.get(CORRELATION_HEADER))
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid X-Correlation-ID"})
        token = _correlation_id.set(correlation_id)
        request.state.correlation_id = correlation_id
        request.state.request_id = correlation_id
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "http_request_failed method=%s path=%s correlation_id=%s duration_ms=%s",
                    request.method,
                    request.url.path,
                    correlation_id,
                    max(0, int((perf_counter() - started) * 1000)),
                )
                raise
        finally:
            _correlation_id.reset(token)
        response.headers[CORRELATION_HEADER] = correlation_id
        logger.info(
            "http_request_completed method=%s path=%s status_code=%s correlation_id=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            correlation_id,
            max(0, int((perf_counter() - started) * 1000)),
        )
        return response

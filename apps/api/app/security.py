from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


SECRET_KEY_NAMES = re.compile(r"(authorization|api[_-]?key|token|password|secret|dsn|cookie)", re.IGNORECASE)
SECRET_VALUE = re.compile(r"(?i)(bearer\s+|(?:api[_-]?key|token|password|secret)\s*[=:]\s*)([^\s,;]+)")
logger = logging.getLogger(__name__)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SECRET_KEY_NAMES.search(str(key)) else redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return SECRET_VALUE.sub(lambda match: f"{match.group(1)}[REDACTED]", value)
    return value


def safe_request_id(value: str | None, max_length: int = 96) -> str:
    if value and len(value) <= max_length and re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        return value
    return secrets.token_urlsafe(16)


def constant_time_token(expected: str | None, supplied: str | None) -> bool:
    return bool(expected and supplied and hmac.compare_digest(expected.encode(), supplied.encode()))


async def require_admin(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.enable_admin_endpoints:
        raise HTTPException(status_code=404, detail="Not found")
    if not settings.admin_token:
        if settings.app_env == "production":
            raise HTTPException(status_code=503, detail="Administrative access is not configured")
        return
    supplied = request.headers.get("authorization", "")
    token = supplied[7:] if supplied.lower().startswith("bearer ") else None
    if not constant_time_token(settings.admin_token, token):
        raise HTTPException(status_code=401, detail="Administrative authorization required")


@dataclass
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        hits = [stamp for stamp in self._hits[key] if now - stamp < window_seconds]
        self._hits[key] = hits
        if len(hits) >= limit:
            retry = max(1, int(window_seconds - (now - hits[0])))
            return RateLimitDecision(False, 0, retry)
        hits.append(now)
        return RateLimitDecision(True, max(0, limit - len(hits)), 0)


class RedisRateLimiter:
    def __init__(self, redis_client: Any, *, namespace: str = "slipiq:rate") -> None:
        self.redis = redis_client
        self.namespace = namespace

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        bucket = f"{self.namespace}:{hashlib.sha256(key.encode()).hexdigest()}:{int(time.time()) // window_seconds}"
        count = int(self.redis.incr(bucket))
        if count == 1:
            self.redis.expire(bucket, window_seconds)
        allowed = count <= limit
        return RateLimitDecision(allowed, max(0, limit - count), window_seconds if not allowed else 0)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        request_id = safe_request_id(request.headers.get("x-request-id"), settings.request_id_max_length)
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.observe_http(request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
        logger.info("request complete", extra={"request_id": request_id, "route": request.url.path, "method": request.method, "status_code": response.status_code})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        settings = request.app.state.settings
        if settings.app_env == "production" and settings.strict_security_headers:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_body_bytes:
                    return JSONResponse(status_code=413, content={"code": "REQUEST_TOO_LARGE", "message": "Request body exceeds the configured limit."})
            except ValueError:
                return JSONResponse(status_code=400, content={"code": "INVALID_CONTENT_LENGTH", "message": "Invalid content length."})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: Any, *, enabled: bool = True) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        if not self.enabled or request.url.path in {"/health", "/ready", "/livez", "/metrics"}:
            return await call_next(request)
        expensive = request.method in {"POST", "PUT", "DELETE"} or "/refresh" in request.url.path or "/backtest" in request.url.path
        limit = settings.expensive_rate_limit_requests if expensive else settings.api_rate_limit_requests
        window = settings.expensive_rate_limit_window_seconds if expensive else settings.api_rate_limit_window_seconds
        client = request.client.host if request.client else "unknown"
        try:
            decision = self.limiter.check(f"{client}:{request.url.path}", limit, window)
        except Exception:
            if settings.app_env == "production":
                return JSONResponse(status_code=503, content={"code": "RATE_LIMIT_UNAVAILABLE", "message": "Rate limiting is temporarily unavailable."})
            return await call_next(request)
        if not decision.allowed:
            response = JSONResponse(status_code=429, content={"code": "RATE_LIMITED", "message": "Too many requests; retry later."})
            response.headers["Retry-After"] = str(decision.retry_after)
            return response
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response

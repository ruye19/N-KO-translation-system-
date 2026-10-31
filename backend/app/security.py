"""Access control and rate limiting for the translation endpoints.

Access key
    Callers send ``Authorization: Bearer <TRANSLATOR_API_KEY>``. The key is
    compared in constant time and is never logged or returned. If no key is
    configured the endpoints refuse every request (fail closed) unless
    REQUIRE_API_KEY=false, which is meant for local development only.

Rate limit
    A sliding window of RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW_SECONDS for
    each client address. The address is ``request.client.host``: this module
    never reads X-Forwarded-For itself. Behind a reverse proxy, let uvicorn
    rewrite the client address from the proxy's headers by trusting only that
    proxy (``--forwarded-allow-ips``); see docs/API_INTEGRATION.md.

    State lives in this process's memory, so each worker process counts
    separately. Run one worker, or move the counter to a shared store such as
    Redis before scaling out.
"""

import hashlib
import hmac
import logging
import threading
import time
from collections import deque
from functools import lru_cache

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# A key shorter than this is easy to guess; the server warns at startup.
MIN_KEY_LENGTH = 32


def _digest(value: str) -> bytes:
    # Hashing first makes both sides the same length, so compare_digest does
    # not reveal the configured key's length.
    return hashlib.sha256(value.encode("utf-8")).digest()


def key_matches(presented: str, configured: list[str]) -> bool:
    """Constant-time check against every configured key (no early exit)."""
    presented_digest = _digest(presented)
    matched = False
    for key in configured:
        matched |= hmac.compare_digest(presented_digest, _digest(key))
    return matched


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "unauthorized", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_api_key(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if not settings.require_api_key:
        return
    keys = settings.translator_api_key_list
    if not keys:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "access_not_configured",
                "message": "The translation service has no access key configured.",
            },
        )

    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    presented = presented.strip()
    if scheme.lower() != "bearer" or not presented:
        raise _unauthorized("Missing access key. Send 'Authorization: Bearer <key>'.")
    if not key_matches(presented, keys):
        logger.warning("Rejected an invalid access key from %s.", client_address(request))
        raise _unauthorized("Invalid access key.")


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Thread-safe sliding-window counter, keyed by client address.

    The endpoints are synchronous and run in a thread pool, hence the lock.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, key: str, limit: int, window: float) -> float | None:
        """Record one request. Returns None if allowed, otherwise the number
        of seconds until the client may try again."""
        now = self._clock()
        with self._lock:
            self._sweep(now, window)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(hits[0] + window - now, 0.0)
            hits.append(now)
            return None

    def _sweep(self, now: float, window: float) -> None:
        # Drop idle clients now and then so memory does not grow without bound.
        if now - self._last_sweep < window:
            return
        self._last_sweep = now
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= now - window]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    return RateLimiter()


def enforce_rate_limit(
    request: Request,
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    if settings.rate_limit_requests <= 0:
        return
    wait = limiter.hit(
        client_address(request),
        settings.rate_limit_requests,
        settings.rate_limit_window_seconds,
    )
    if wait is not None:
        retry_after = max(1, int(wait + 0.999))
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": (
                    f"Too many requests: the limit is {settings.rate_limit_requests} "
                    f"per {settings.rate_limit_window_seconds:g} seconds. "
                    f"Try again in {retry_after} seconds."
                ),
            },
            headers={"Retry-After": str(retry_after)},
        )

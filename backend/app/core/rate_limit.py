"""Tiny in-memory rate limiter (feature 5): max N login attempts per IP per minute.
Per-process memory is fine for a prototype; production would use Redis.
blocks ip address that tries to log in more than 10 times in a minute"""
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(limit: int, window_seconds: int = 60):
    def dependency(request: Request) -> None:
        key = f"{request.url.path}:{request.client.host if request.client else 'unknown'}"
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > window_seconds:   # forget hits older than the window
            q.popleft()
        if len(q) >= limit:
            raise AppError(429, "TOO_MANY_REQUESTS", "Too many attempts. Please wait a minute and try again.")
        q.append(now)

    return dependency


def reset_rate_limits() -> None:
    """Used by tests."""
    _hits.clear()
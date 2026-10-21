"""Process-local write throttling used only when public demo mode is enabled."""

import asyncio
import hmac
import re
import time
from collections import defaultdict, deque

_REVERSAL_PATH = re.compile(r"^/transfers/[^/]+/reverse$")


class PerIPWriteRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_limited(self, client_ip: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            requests = self._requests[client_ip]
            while requests and requests[0] <= now - window_seconds:
                requests.popleft()
            if len(requests) >= limit:
                return True
            requests.append(now)
            return False

    def clear(self) -> None:
        """Reset in-memory counters (used by tests and local diagnostics)."""
        self._requests.clear()


def is_write_endpoint(method: str, path: str) -> bool:
    if method != "POST":
        return False
    return path in {"/accounts", "/transfers"} or _REVERSAL_PATH.fullmatch(path) is not None


def seed_token_matches(supplied: str | None, configured: str | None) -> bool:
    return bool(supplied and configured and hmac.compare_digest(supplied, configured))

"""Per-IP rate limiting middleware implemented as pure ASGI3.

This middleware avoids BaseHTTPMiddleware to prevent buffering of streaming
responses (e.g., Server-Sent Events at /events).
"""

import json
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "rate_limit.json"
with _CONFIG.open(encoding="utf-8") as stream:
    LIMITS = json.load(stream)


class PerIPRateLimitMiddleware:
    """ASGI3 middleware that enforces per-IP request rate limits.

    Tracks request timestamps per IP in a sliding window. When the limit
    is exceeded, returns 429 with a Retry-After header. Normal requests
    pass through to the wrapped app without buffering.
    """

    def __init__(self, app, limit=None, window_seconds=None):
        self.app = app
        self.limit = int(limit if limit is not None else LIMITS["requests"])
        self.window_seconds = int(
            window_seconds if window_seconds is not None else LIMITS["window_seconds"]
        )
        self._hits = defaultdict(deque)
        self._lock = Lock()

    async def __call__(self, scope, receive, send):
        # Pass through non-HTTP scopes (lifespan, etc.) unchanged
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract client IP from ASGI scope
        client = scope.get("client")
        ip = client[0] if client else "unknown"

        # Check rate limit using sliding window
        now = time.monotonic()
        with self._lock:
            hits = self._hits[ip]
            cutoff = now - self.window_seconds
            # Remove expired timestamps
            while hits and hits[0] <= cutoff:
                hits.popleft()
            
            if len(hits) >= self.limit:
                # Rate limit exceeded - send 429 response directly
                await self._send_rate_limit_response(send)
                return
            
            # Record this request
            hits.append(now)

        # Not rate limited - pass through to the wrapped app
        await self.app(scope, receive, send)

    async def _send_rate_limit_response(self, send):
        """Send a 429 response with Retry-After header via ASGI."""
        body = json.dumps({"error": "rate limit exceeded"}).encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                    [b"retry-after", str(self.window_seconds).encode()],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )


class DailyPasteLimiter:
    """Per-IP daily caps on pasted links and on new domains, enforced server-side.

    Counts only foreign-link pastes (the sample basket and ISBN or title
    searches never touch it). The day rolls at Bucharest midnight.
    """

    def __init__(self, pastes_per_day=None, new_domains_per_day=None, today=None):
        self.pastes_per_day = int(pastes_per_day if pastes_per_day is not None else LIMITS["pastes_per_day"])
        self.new_domains_per_day = int(
            new_domains_per_day if new_domains_per_day is not None else LIMITS["new_domains_per_day"]
        )
        self._today = today or _bucharest_today
        self._day = None
        self._pastes = defaultdict(int)
        self._domains = defaultdict(set)
        self._lock = Lock()

    def check(self, ip, domain):
        """Record one paste and return None, or the reason it is refused."""
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day = day
                self._pastes.clear()
                self._domains.clear()
            if self._pastes[ip] >= self.pastes_per_day:
                return "paste_limit"
            if domain not in self._domains[ip] and len(self._domains[ip]) >= self.new_domains_per_day:
                return "new_domain_limit"
            self._pastes[ip] += 1
            self._domains[ip].add(domain)
            return None


def _bucharest_today():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Bucharest")).date()

"""Small per-process fixed-window API rate limiter."""

import json
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "rate_limit.json"
with _CONFIG.open(encoding="utf-8") as stream:
    LIMITS = json.load(stream)


class PerIPRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit=None, window_seconds=None):
        super().__init__(app)
        self.limit = int(limit if limit is not None else LIMITS["requests"])
        self.window_seconds = int(window_seconds if window_seconds is not None else LIMITS["window_seconds"])
        self._hits = defaultdict(deque)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[ip]
            cutoff = now - self.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return JSONResponse(status_code=429, content={"error": "rate limit exceeded"}, headers={"Retry-After": str(self.window_seconds)})
            hits.append(now)
        return await call_next(request)

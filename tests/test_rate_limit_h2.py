"""H2: the per-IP limiter never holds its lock across an await, and only API paths count.

Before: the 429 was sent while a threading.Lock was held, so a slow client could stall the
event loop, and every static file (index.html, scripts, fixtures) counted toward the 60 a minute.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from api import rate_limit
from api.app import create_app


def _scope(path: str, ip: str = "1.2.3.4") -> dict:
    return {"type": "http", "method": "GET", "path": path, "headers": [], "client": (ip, 5000)}


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def test_the_lock_is_released_before_the_429_is_sent():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = rate_limit.PerIPRateLimitMiddleware(app, limit=1, window_seconds=60)
    held: list[bool] = []
    statuses: list[int] = []

    async def send(message):
        held.append(middleware._lock.locked())
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
        await asyncio.sleep(0)

    async def run():
        await middleware(_scope("/solve"), _receive, send)
        await middleware(_scope("/solve"), _receive, send)

    asyncio.run(run())
    assert statuses == [200, 429]
    assert held and not any(held)


def test_a_slow_429_does_not_hold_up_another_ip():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = rate_limit.PerIPRateLimitMiddleware(app, limit=1, window_seconds=60)
    release = asyncio.Event
    done: list[str] = []

    async def run():
        gate = release()

        async def slow_send(message):
            await gate.wait()

        async def fast_send(message):
            if message["type"] == "http.response.start":
                done.append(f"other ip {message['status']}")

        await middleware(_scope("/solve", "9.9.9.9"), _receive, fast_send)  # uses up 9.9.9.9
        done.clear()
        await middleware(_scope("/solve", "1.1.1.1"), _receive, fast_send)  # uses up 1.1.1.1
        slow = asyncio.create_task(middleware(_scope("/solve", "1.1.1.1"), _receive, slow_send))
        await asyncio.sleep(0.01)  # the 429 for 1.1.1.1 is now waiting on its client
        if middleware._lock.locked():
            gate.set()
            await slow
            raise AssertionError("the limiter lock is held while a 429 waits on its client")
        await middleware(_scope("/solve", "2.2.2.2"), _receive, fast_send)
        gate.set()
        await asyncio.wait_for(slow, 1)

    asyncio.run(run())
    assert done == ["other ip 200", "other ip 200"]


def _static_app(limit: int) -> TestClient:
    folder = Path(tempfile.mkdtemp())
    (folder / "index.html").write_text("<html></html>")
    (folder / "main.js").write_text("console.log(1)")
    app = FastAPI()
    app.add_middleware(rate_limit.PerIPRateLimitMiddleware, limit=limit, window_seconds=60)

    @app.get("/solve")
    def solve():
        return {"ok": True}

    app.mount("/", StaticFiles(directory=folder, html=True), name="ui")
    return TestClient(app)


def test_static_files_never_count_toward_the_limit():
    client = _static_app(limit=3)
    for path in ["/", "/index.html", "/main.js", "/fixtures/nope.json"] * 5:
        assert client.get(path).status_code in (200, 404)
    assert [client.get("/solve").status_code for _ in range(4)] == [200, 200, 200, 429]
    # Over the API limit, the page itself still loads.
    assert client.get("/main.js").status_code == 200
    assert client.get("/").status_code == 200


def test_every_api_route_counts(tmp_path):
    app = create_app(tmp_path / "pages.sqlite")
    routes = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert routes, "no API routes found"
    assert routes <= rate_limit.API_PATHS, f"not counted: {sorted(routes - rate_limit.API_PATHS)}"
    other = {getattr(route, "path", None) for route in app.routes if not isinstance(route, APIRoute)}
    assert other - {None, ""} <= rate_limit.API_PATHS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.rate_limit import LIMITS, PerIPRateLimitMiddleware


def test_configured_limits_are_loaded():
    assert LIMITS == {
        "requests": 60,
        "window_seconds": 60,
        "pastes_per_day": 20,
        "new_domains_per_day": 5,
        "why_calls_per_window": 10,
        "why_window_seconds": 600,
        "why_calls_per_day": 40,
    }


def test_burst_from_one_ip_is_limited():
    app = FastAPI()
    app.add_middleware(PerIPRateLimitMiddleware, limit=3, window_seconds=60)

    @app.get("/")
    def ok():
        return {"ok": True}

    client = TestClient(app)
    assert [client.get("/").status_code for _ in range(3)] == [200, 200, 200]
    response = client.get("/")
    assert response.status_code == 429
    assert response.json() == {"error": "rate limit exceeded"}
    assert response.headers["retry-after"] == "60"

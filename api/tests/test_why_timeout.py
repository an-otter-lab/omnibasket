"""The Why model call outlasts Muse's real latency, and a duplicate request waits for it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import why
from api.app import create_app


def test_timeout_covers_measured_latency_and_stays_under_the_duplicate_wait():
    assert 20 <= why.MODEL_TIMEOUT_S < why.INFLIGHT_WAIT_S


def test_the_model_call_uses_the_timeout(monkeypatch):
    seen = []

    def post(body, estimate, note, provider="meta", timeout=120):
        seen.append((note, timeout))
        return {"output_text": ""}, {}

    monkeypatch.setattr(why.meta_budget, "guarded_post", post)
    why.clear_cache()
    payload = TestClient(create_app()).post("/solve").json()
    TestClient(create_app()).post("/why", json={"payload": payload, "lang": "en"})
    assert seen == [("why-this-split", why.MODEL_TIMEOUT_S)]

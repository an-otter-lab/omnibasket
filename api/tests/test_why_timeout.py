"""The Why model call outlasts Muse's real latency, and a duplicate request gets the leader's outcome."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from api import why
from api.app import create_app
from api.tests.test_why_s17 import GOOD


@pytest.fixture()
def client(tmp_path) -> TestClient:
    # A tmp cache: the default path is the developer's real data/cache file.
    return TestClient(create_app(tmp_path / "pages.sqlite"))


@pytest.fixture(autouse=True)
def fresh_cache():
    why.clear_cache()
    yield
    why.clear_cache()


def test_timeout_covers_measured_latency_and_stays_under_the_duplicate_wait():
    assert 20 <= why.MODEL_TIMEOUT_S < why.INFLIGHT_WAIT_S


def test_the_model_call_uses_the_timeout(client, monkeypatch):
    seen = []

    def post(body, estimate, note, provider="meta", timeout=120):
        seen.append((note, timeout))
        return {"output_text": ""}, {}

    monkeypatch.setattr(why.meta_budget, "guarded_post", post)
    payload = client.post("/solve").json()
    client.post("/why", json={"payload": payload, "lang": "en"})
    assert seen == [("why-this-split", why.MODEL_TIMEOUT_S)]


def test_a_slow_call_is_cut_off_at_the_bound_and_the_late_answer_is_kept(client, monkeypatch):
    # urlopen's timeout is per socket operation and guarded_post may POST twice, so the
    # model call itself can outlast MODEL_TIMEOUT_S. The leader's wait must not.
    payload = client.post("/solve").json()
    release = threading.Event()
    calls = []

    def post(body, estimate, note, provider="meta", timeout=120):
        calls.append(note)
        release.wait(5)
        return {"output_text": GOOD}, {}

    monkeypatch.setattr(why.meta_budget, "guarded_post", post)
    monkeypatch.setattr(why, "MODEL_TIMEOUT_S", 0.1)
    monkeypatch.setattr(why, "INFLIGHT_WAIT_S", 2)

    out = []
    started = time.monotonic()
    leader = threading.Thread(target=lambda: out.append(why.explain(payload, "en")))
    leader.start()
    while not calls:
        time.sleep(0.01)
    duplicate = why.explain(payload, "en")
    leader.join(5)
    assert time.monotonic() - started < 1
    assert out[0]["reason"] == why.TIMED_OUT
    assert duplicate["source"] == "template"

    release.set()
    key = why.payload_hash(payload, "en")
    for _ in range(200):
        if key in why._cache:
            break
        time.sleep(0.01)
    assert why.explain(payload, "en")["text"] == GOOD
    assert len(calls) == 1

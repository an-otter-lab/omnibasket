"""POST /why with a mocked model: no network, no spend."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import why  # puts tools/ on sys.path
from api.app import create_app
from api.explain_check import fallback_sentences

meta_budget = why.meta_budget


@pytest.fixture(scope="module")
def payload() -> dict:
    return TestClient(create_app()).post("/solve").json()


@pytest.fixture()
def client():
    why.clear_cache()
    return TestClient(create_app())


@pytest.fixture()
def model(monkeypatch):
    """Replace guarded_post; .reply is the text, .calls counts calls."""

    class Fake:
        reply: object = ""
        calls: list = []
        error: Exception | None = None

    fake = Fake()
    fake.calls = []

    def post(body, estimate, note, provider="meta", timeout=120):
        fake.calls.append(body)
        if fake.error:
            raise fake.error
        return {"output_text": fake.reply}, {}

    monkeypatch.setattr(meta_budget, "guarded_post", post)
    return fake


GOOD_EN = (
    "The cheapest split is 515.16 lei in two orders: 4 books at Amazon.de and 3 books at Libris. "
    "One order at Libris would cost 558.73 lei, 43.57 lei more."
)


def _post(client, payload, lang="en"):
    return client.post("/why", json={"payload": payload, "lang": lang})


def test_checker_pass_returns_muse(client, payload, model):
    model.reply = GOOD_EN
    r = _post(client, payload)
    assert r.status_code == 200
    assert r.json() == {"text": GOOD_EN, "source": "muse", "lang": "en", "model": meta_budget.MODEL}
    body = model.calls[0]
    assert body["max_output_tokens"] >= 1200 and body["reasoning"]["effort"] == "low"


@pytest.mark.parametrize(
    "reply,why_text",
    [
        ("The cheapest split is 515.17 lei in 2 orders at Amazon.de and Libris.", "wrong price"),
        ("Books-Express and Libris split this basket for 515.16 lei in 2 orders.", "shop not in payload"),
        ("The cheapest split is 515.16 lei, and you save 99.99 lei on shipping.", "invented number"),
        ("", "empty"),
        ("   \n", "blank"),
    ],
)
def test_failures_return_template(client, payload, model, reply, why_text):
    model.reply = reply
    r = _post(client, payload)
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "template" and out["model"] is None
    assert out["text"] == fallback_sentences(payload)[1]
    assert "reason" not in out


def test_budget_refusal_returns_template(client, payload, model):
    model.error = meta_budget.CapExceeded(9.99, 0.5)
    r = _post(client, payload, "ro")
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "template" and out["lang"] == "ro"
    assert out["text"] == fallback_sentences(payload)[0]


def test_reason_is_logged_without_secrets(client, payload, model, caplog):
    model.reply = "Libris costs 999.99 lei."
    with caplog.at_level("WARNING", logger="omnibasket.why"):
        _post(client, payload)
    assert any("checker failed" in m for m in caplog.messages)


def test_second_call_same_payload_is_cached(client, payload, model):
    model.reply = GOOD_EN
    first = _post(client, payload).json()
    second = _post(client, payload).json()
    assert first == second and len(model.calls) == 1
    _post(client, payload, "ro")  # other language is a different key
    assert len(model.calls) == 2


def test_failures_are_cached_too(client, payload, model):
    model.reply = ""
    _post(client, payload)
    _post(client, payload)
    assert len(model.calls) == 1


def test_hash_is_stable_across_key_order(payload):
    shuffled = dict(reversed(list(payload.items())))
    assert why.payload_hash(payload, "en") == why.payload_hash(shuffled, "en")


def test_unroutable_host_returns_template(client, payload, monkeypatch):
    """Mock urllib to raise a timeout error; verify /why returns template with 200."""
    import urllib.error
    import urllib.request
    
    original_urlopen = urllib.request.urlopen
    
    def mock_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection timed out")
    
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    r = _post(client, payload)
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "template"
    assert out["model"] is None
    # Reason is logged but not returned in response

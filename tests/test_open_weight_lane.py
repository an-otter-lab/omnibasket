"""The open-weight lane (Adrian, 3 Nov): Ask Omnibasket and the free-text parse go to
Muse Spark Open on Baseten first, with Muse Spark 1.3 on Meta as the fallback.
No network: meta_budget._post is replaced and every key is a fake."""

import json
import urllib.error

import pytest

from tools import meta_budget as mb

OPEN_MODEL = "meta-models/muse-spark-open-1026"


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A fresh ledger, no spend windows, fake keys, no .env, and a recording _post."""
    monkeypatch.setenv("META_SPEND_PATH", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(tmp_path / "no-windows.json"))
    monkeypatch.setenv("META_API_KEY", "fake-meta")
    monkeypatch.setenv("BASETEN_API_KEY", "fake-baseten")
    for name in ("OMNIBASKET_OPEN_WEIGHT", "BASETEN_RATE_IN_PER_M", "BASETEN_RATE_OUT_PER_M"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mb, "load_dotenv", lambda: None)

    class Fake:
        calls = []
        replies = {
            "baseten": {"choices": [{"message": {"content": '{"actions": []}'}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}},
            "meta": {"output_text": '{"actions": []}', "usage": {"input_tokens": 100, "output_tokens": 20}},
        }

    def post(path, body, provider="meta", timeout=120):
        Fake.calls.append({"path": path, "body": body, "provider": provider, "timeout": timeout})
        reply = Fake.replies[provider]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(mb, "_post", post)
    return Fake


def rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "spend.jsonl").read_text().splitlines() if line]


def responses_body(text="map this", image=None):
    content = [{"type": "input_text", "text": text}]
    if image:
        content.append({"type": "input_image", "image_url": image})
    return {
        "model": mb.MODEL,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 1500,
        "reasoning": {"effort": "low"},
    }


@pytest.mark.parametrize("note", ["ask-map", "input-free-text"])
def test_lane_notes_go_to_muse_spark_open(lane, tmp_path, note):
    payload, row = mb.guarded_post(responses_body(), 0.01, note=note)
    assert [c["provider"] for c in lane.calls] == ["baseten"]
    call = lane.calls[0]
    assert call["path"] == "/chat/completions"
    assert call["body"]["model"] == OPEN_MODEL
    assert call["timeout"] == mb.OPEN_WEIGHT_TIMEOUT_S
    assert row["provider"] == "baseten" and row["model"] == OPEN_MODEL
    assert row["tokens_in"] == 100 and row["tokens_out"] == 20
    assert row["cost_usd"] == pytest.approx(100 / 1e6 * 1.25 + 20 / 1e6 * 4.25)
    assert "fallback_from" not in row
    assert rows(tmp_path) == [row]


@pytest.mark.parametrize("note", ["why-this-split", "photo-read", "muse-gap-fill", "input-page-book"])
def test_other_notes_stay_on_meta(lane, note):
    _payload, row = mb.guarded_post(responses_body(), 0.01, note=note)
    assert [c["provider"] for c in lane.calls] == ["meta"]
    assert lane.calls[0]["path"] == "/responses"
    assert lane.calls[0]["body"]["model"] == mb.MODEL
    assert row["provider"] == "meta"


def test_an_explicit_provider_is_never_rerouted(lane):
    mb.guarded_post(responses_body(), 0.01, note="ask-map", provider="baseten")
    mb.guarded_post(responses_body(), 0.01, note="calibrate", provider="baseten")
    assert [c["provider"] for c in lane.calls] == ["baseten", "baseten"]


@pytest.mark.parametrize(
    "failure, reason",
    [
        (urllib.error.HTTPError("u", 400, "Bad Request", {}, None), "RuntimeError: model HTTP 400"),
        (TimeoutError("timed out"), "TimeoutError"),
        (OSError("connection refused"), "OSError"),
    ],
)
def test_a_failed_open_call_falls_back_to_meta(lane, tmp_path, failure, reason):
    lane.replies = {**lane.replies, "baseten": failure}
    payload, row = mb.guarded_post(responses_body(), 0.01, note="ask-map", timeout=30)
    assert [c["provider"] for c in lane.calls] == ["baseten", "meta"]
    assert lane.calls[1]["timeout"] == 30
    assert payload["output_text"] == '{"actions": []}'
    assert row["provider"] == "meta"
    assert row["fallback_from"] == "baseten"
    assert row["fallback_reason"] == reason
    assert [r["provider"] for r in rows(tmp_path)] == ["meta"]


def test_an_empty_open_reply_is_recorded_then_falls_back(lane, tmp_path):
    lane.replies = {**lane.replies, "baseten": {"choices": [{"message": {"content": "  "}}],
                                                "usage": {"prompt_tokens": 90, "completion_tokens": 1500}}}
    _payload, row = mb.guarded_post(responses_body(), 0.01, note="input-free-text")
    assert row["provider"] == "meta" and row["fallback_reason"] == "empty reply"
    # The empty call was paid for, so it stays in the ledger.
    assert [r["provider"] for r in rows(tmp_path)] == ["baseten", "meta"]


def test_a_cap_refusal_is_not_retried_on_meta(lane, tmp_path, monkeypatch):
    windows = tmp_path / "windows.json"
    windows.write_text(json.dumps({"windows": [
        {"provider": "meta", "from": "2000-01-01T00:00:00+00:00", "until": None, "cap_usd": 0.001}
    ]}))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(windows))
    with pytest.raises(mb.WindowCapExceeded):
        mb.guarded_post(responses_body(), 0.01, note="ask-map")
    assert lane.calls == []


def test_no_baseten_key_means_meta_only(lane, monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY")
    _payload, row = mb.guarded_post(responses_body(), 0.01, note="ask-map")
    assert [c["provider"] for c in lane.calls] == ["meta"]
    assert "fallback_from" not in row


@pytest.mark.parametrize("value", ["0", "false", "off", "no"])
def test_the_switch_turns_the_lane_off(lane, monkeypatch, value):
    monkeypatch.setenv("OMNIBASKET_OPEN_WEIGHT", value)
    mb.guarded_post(responses_body(), 0.01, note="ask-map")
    assert [c["provider"] for c in lane.calls] == ["meta"]


def test_chat_body_carries_text_image_tokens_and_effort():
    body = mb._chat_body(responses_body("read this", image="data:image/png;base64,AAAA"), OPEN_MODEL)
    assert body == {
        "model": OPEN_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "read this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}],
        "max_tokens": 1500,
        "reasoning_effort": "low",
    }


def test_chat_body_with_text_only_is_one_string():
    body = mb._chat_body({"input": [{"role": "user", "content": [
        {"type": "input_text", "text": "a"}, {"type": "input_text", "text": "b"}]}]}, OPEN_MODEL)
    assert body == {"model": OPEN_MODEL, "messages": [{"role": "user", "content": "a\n\nb"}]}


def test_baseten_is_priced_and_env_overrides_the_rate(monkeypatch):
    for name in ("BASETEN_RATE_IN_PER_M", "BASETEN_RATE_OUT_PER_M"):
        monkeypatch.delenv(name, raising=False)
    assert mb.provider_rates("baseten") == (1.25, 4.25)
    monkeypatch.setenv("BASETEN_RATE_IN_PER_M", "2")
    monkeypatch.setenv("BASETEN_RATE_OUT_PER_M", "8")
    assert mb.provider_rates("baseten") == (2.0, 8.0)


def test_redact_hides_every_provider_key(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "meta-secret-1")
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-secret-2")
    assert mb._redact("x meta-secret-1 y baseten-secret-2") == "x [redacted] y [redacted]"


def test_ask_answers_through_the_open_lane(monkeypatch, tmp_path):
    """End to end through api.ask -> call_muse_json -> guarded_post, with the lane on."""
    from api import ask
    from api import input_understanding as iu
    from api import muse_integration

    budget = muse_integration.meta_budget  # the module object the app imports
    monkeypatch.setenv("META_SPEND_PATH", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(tmp_path / "no-windows.json"))
    monkeypatch.setenv("BASETEN_API_KEY", "fake-baseten")
    monkeypatch.delenv("OMNIBASKET_OPEN_WEIGHT", raising=False)
    monkeypatch.setattr(budget, "load_dotenv", lambda: None)
    seen = []

    def post(path, body, provider="meta", timeout=120):
        seen.append(provider)
        return {"choices": [{"message": {"content": '{"actions": [{"action": "set_tab", "tab": "one"}]}'}}],
                "usage": {"prompt_tokens": 400, "completion_tokens": 30}}

    monkeypatch.setattr(budget, "_post", post)
    parsed = iu.call_muse_json(ask.MAP_PROMPT, "SHOPPER: show me one order", "ask-map", strict=True)
    assert seen == ["baseten"]
    assert parsed == {"actions": [{"action": "set_tab", "tab": "one"}]}
    assert rows(tmp_path)[0]["note"] == "ask-map"

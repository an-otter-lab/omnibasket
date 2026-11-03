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


def test_a_reply_that_fails_accept_is_recorded_then_falls_back(lane, tmp_path):
    lane.replies = {**lane.replies, "baseten": {"choices": [{"message": {"content": "Sure! Here you go."}}],
                                                "usage": {"prompt_tokens": 90, "completion_tokens": 40}}}
    payload, row = mb.guarded_post(responses_body(), 0.01, note="ask-map", accept=lambda text: text.startswith("{"))
    assert [c["provider"] for c in lane.calls] == ["baseten", "meta"]
    assert payload["output_text"] == '{"actions": []}'
    assert row["provider"] == "meta" and row["fallback_reason"] == "unusable reply"
    assert [r["provider"] for r in rows(tmp_path)] == ["baseten", "meta"]


def test_a_reply_that_passes_accept_stays_on_baseten(lane):
    _payload, row = mb.guarded_post(responses_body(), 0.01, note="ask-map", accept=lambda text: text.startswith("{"))
    assert [c["provider"] for c in lane.calls] == ["baseten"]
    assert row["provider"] == "baseten"


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


def test_a_switch_in_dotenv_holds_from_the_first_call(lane, monkeypatch):
    """Key and switch both only in .env: the first routed call must already see the switch."""
    monkeypatch.delenv("BASETEN_API_KEY")

    def dotenv():
        monkeypatch.setenv("BASETEN_API_KEY", "fake-baseten")
        monkeypatch.setenv("OMNIBASKET_OPEN_WEIGHT", "0")

    monkeypatch.setattr(mb, "load_dotenv", dotenv)
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


def test_ask_falls_back_when_muse_spark_open_answers_in_prose(monkeypatch, tmp_path):
    """Ask is strict JSON: prose from Baseten must reach Meta, not end as 'unsupported'."""
    from api import ask
    from api import input_understanding as iu
    from api import muse_integration

    budget = muse_integration.meta_budget
    monkeypatch.setenv("META_SPEND_PATH", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(tmp_path / "no-windows.json"))
    monkeypatch.setenv("BASETEN_API_KEY", "fake-baseten")
    monkeypatch.delenv("OMNIBASKET_OPEN_WEIGHT", raising=False)
    monkeypatch.setattr(budget, "load_dotenv", lambda: None)
    seen = []
    good = '{"actions": [{"action": "set_tab", "tab": "one"}]}'

    def post(path, body, provider="meta", timeout=120):
        seen.append(provider)
        if provider == "baseten":
            return {"choices": [{"message": {"content": "Sure! " + good}}],
                    "usage": {"prompt_tokens": 400, "completion_tokens": 30}}
        return {"output_text": good, "usage": {"input_tokens": 300, "output_tokens": 30}}

    monkeypatch.setattr(budget, "_post", post)
    parsed = iu.call_muse_json(ask.MAP_PROMPT, "SHOPPER: show me one order", "ask-map", strict=True)
    assert seen == ["baseten", "meta"]
    assert parsed == {"actions": [{"action": "set_tab", "tab": "one"}]}
    assert [r.get("fallback_reason") for r in rows(tmp_path)] == [None, "unusable reply"]


BASETEN_DAY = {"provider": "baseten", "from": "2000-01-01T00:00:00+00:00", "until": None,
               "period": "day", "gates": "own", "cap_usd": 0.001}


def _windows(tmp_path, monkeypatch, rows_):
    path = tmp_path / "windows.json"
    path.write_text(json.dumps({"windows": rows_}))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(path))


def _ledger_row(tmp_path, ts, provider, cost):
    with (tmp_path / "spend.jsonl").open("a") as f:
        f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), "provider": provider,
                            "tokens_in": 1, "tokens_out": 1, "cost_usd": cost}) + "\n")


def test_a_full_baseten_window_sends_the_lane_to_meta(lane, tmp_path, monkeypatch):
    _windows(tmp_path, monkeypatch, [BASETEN_DAY])
    _payload, row = mb.guarded_post(responses_body(), 0.01, note="ask-map")
    assert [c["provider"] for c in lane.calls] == ["meta"]
    assert row["provider"] == "meta" and row["fallback_reason"] == "baseten window full"


def test_a_full_baseten_window_does_not_stop_meta_calls(lane, tmp_path, monkeypatch):
    _windows(tmp_path, monkeypatch, [BASETEN_DAY])
    _payload, row = mb.guarded_post(responses_body(), 0.01, note="why-this-split")
    assert row["provider"] == "meta" and "fallback_from" not in row


def test_an_explicit_baseten_call_is_refused_by_its_window(lane, tmp_path, monkeypatch):
    _windows(tmp_path, monkeypatch, [BASETEN_DAY])
    with pytest.raises(mb.WindowCapExceeded, match="baseten spend today"):
        mb.guarded_post(responses_body(), 0.01, note="calibrate", provider="baseten")
    assert lane.calls == []


def test_a_daily_window_counts_only_todays_rows(lane, tmp_path, monkeypatch):
    window = {**BASETEN_DAY, "cap_usd": 10.0}
    _windows(tmp_path, monkeypatch, [window])
    now = mb.datetime.now(mb.TZ)
    _ledger_row(tmp_path, now - mb.timedelta(days=1), "baseten", 9.99)
    _ledger_row(tmp_path, now, "meta", 5.0)  # another provider's spend never counts
    assert mb.window_spent_usd(window) == 0.0
    mb.guarded_post(responses_body(), 0.01, note="ask-map")
    assert [c["provider"] for c in lane.calls] == ["baseten"]
    _ledger_row(tmp_path, now, "baseten", 9.995)
    with pytest.raises(mb.WindowCapExceeded):
        mb.assert_can_spend(0.01, provider="baseten")


def test_the_committed_baseten_window_is_ten_dollars_a_day_and_in_force(monkeypatch):
    monkeypatch.setenv("META_SPEND_WINDOWS", str(mb.ROOT / "config" / "spend-windows.json"))
    baseten = [w for w in mb.active_windows() if w["provider"] == "baseten"]
    assert len(baseten) == 1
    w = baseten[0]
    assert (w["period"], w["gates"], w["cap_usd"], w["until"]) == ("day", "own", 10.0, None)
    assert mb.window_gates(w, "baseten") and not mb.window_gates(w, "meta")

"""POST /ask and api/ask.py with the model mocked: no network, no spend."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import ask, why  # why puts tools/ on sys.path
from api.app import create_app

meta_budget = why.meta_budget
FIX = json.loads((Path(__file__).parent / "fixtures" / "ask_cases.json").read_text(encoding="utf-8"))
STATE = FIX["state"]
CASES = FIX["cases"]
NAMES = ask.load_names()


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def model(monkeypatch):
    class Fake:
        reply: object = {"actions": []}
        calls: list = []
        error: Exception | None = None

    fake = Fake()
    fake.calls = []

    def post(body, estimate, note, provider="meta", timeout=120):
        fake.calls.append({"body": body, "note": note})
        if fake.error:
            raise fake.error
        text = fake.reply if isinstance(fake.reply, str) else json.dumps(fake.reply)
        return {"output_text": text}, {}

    monkeypatch.setattr(meta_budget, "guarded_post", post)
    return fake


def _ask(client, text="no amazon please?", state=None, lang="en"):
    return client.post("/ask", json={"text": text, "lang": lang, "state": state or STATE})


def _v(actions, state=None):
    return ask.validate({"actions": actions}, state or STATE, NAMES)


A = lambda n, **a: {"name": n, "args": a}  # noqa: E731
TAB = A("set_tab", tab="one")
EXC = A("exclude_store", store_id="amazon_de")
INC = A("include_store", store_id="libris")
MEM = A("set_membership", membership_id="emag_genius", on=True)
PIN = A("pin_editions", mode="current")


# ---------------------------------------------------------------- fixtures


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:50] for c in CASES])
def test_fixture_phrase(client, model, case):
    model.reply = case["model"] if case["path"] == "model" else {"actions": []}
    r = _ask(client, case["text"], lang=case["lang"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) - {"replies"} == {"status", "actions", "reply_key", "reply_args"}
    if case["expect"] == "unsupported":
        assert body["status"] == "unsupported" and body["actions"] == []
        assert body["reply_key"] == "askUnsupported"
    else:
        assert body["status"] == "ok" and body["actions"] == case["expect"]
        assert 1 <= len(body["actions"]) <= 4
    assert len(model.calls) == (0 if case["path"] == "fast" else 1)


def test_fixture_size_and_coverage():
    assert len(CASES) >= 50
    langs = {c["lang"] for c in CASES}
    assert langs == {"en", "ro"}
    assert sum(1 for c in CASES if c["path"] == "fast") >= 30
    assert sum(1 for c in CASES if c["expect"] == "unsupported") >= 8
    texts = {c["text"] for c in CASES}
    for demo in ("keep it to one order", "I have Genius", "no Amazon", "exact editions only",
                 "o singură comandă", "am Genius", "fără Amazon", "doar ediția exactă"):
        assert demo in texts


# ---------------------------------------------------------------- validation rules: pass and fail


def test_rule1_top_level():
    assert _v([TAB]).status == "ok"
    assert ask.validate([TAB], STATE).status == "unsupported"
    assert ask.validate({"actions": [TAB], "extra": 1}, STATE).status == "unsupported"
    assert ask.validate({"actions": "x"}, STATE).status == "unsupported"
    assert ask.validate({"actions": {"name": "set_tab"}}, STATE).status == "unsupported"
    assert ask.validate("text", STATE).status == "unsupported"
    assert _v([TAB, EXC, MEM, PIN]).status == "ok"  # 4 is the max
    assert _v([TAB, EXC, MEM, PIN, INC]).status == "unsupported"  # 5


def test_rule2_names_and_arg_keys():
    assert _v([EXC]).status == "ok"
    assert _v([A("Set_Tab", tab="one")]).status == "unsupported"  # no case folding
    assert _v([A("buy_now", x="y")]).status == "unsupported"
    assert _v([{"name": "set_tab", "args": {"tab": "one"}, "why": "x"}]).status == "unsupported"
    assert _v([{"name": "set_tab"}]).status == "unsupported"
    assert _v([A("set_tab", tab="one", extra="x")]).status == "unsupported"
    assert _v([A("set_tab")]).status == "unsupported"
    assert _v([A("set_membership", membership_id="emag_genius")]).status == "unsupported"
    assert _v([{"name": "set_tab", "args": []}]).status == "unsupported"
    assert _v(["set_tab"]).status == "unsupported"


def test_rule3_strict_types():
    assert _v([A("set_tab", tab="custom")]).status == "ok"
    assert _v([A("set_tab", tab="two")]).status == "unsupported"
    assert _v([A("set_tab", tab=["one"])]).status == "unsupported"
    assert _v([A("exclude_store", store_id="libris")]).status == "ok"
    assert _v([A("exclude_store", store_id="amazon_de; drop")]).status == "unsupported"
    assert _v([A("exclude_store", store_id="nowhere")]).status == "unsupported"
    assert _v([A("include_store", store_id="nowhere")]).status == "unsupported"
    assert _v([A("set_membership", membership_id="amazon_prime", on=False)]).status == "ok"
    assert _v([A("set_membership", membership_id="nope", on=True)]).status == "unsupported"
    for bad in ("true", 1, 0, None, "false"):
        assert _v([A("set_membership", membership_id="emag_genius", on=bad)]).status == "unsupported"
    assert _v([A("pin_editions", mode="clear")]).status == "ok"
    assert _v([A("pin_editions", mode="all")]).status == "unsupported"


def test_rule4_duplicates_and_contradictions():
    assert _v([EXC, INC]).status == "ok"
    assert _v([EXC, EXC]).status == "unsupported"
    assert _v([A("exclude_store", store_id="libris"), INC]).status == "unsupported"
    assert _v([INC, A("exclude_store", store_id="libris")]).status == "unsupported"
    on, off = MEM, A("set_membership", membership_id="emag_genius", on=False)
    assert _v([on, off]).status == "unsupported"
    assert _v([on, A("set_membership", membership_id="amazon_prime", on=False)]).status == "ok"
    assert _v([TAB, A("set_tab", tab="cheapest")]).status == "unsupported"
    assert _v([PIN, A("pin_editions", mode="clear")]).status == "unsupported"


def test_rule5_never_zero_shops():
    one = dict(STATE, store_ids=["libris"])
    assert _v([EXC], one).status == "unsupported"  # amazon_de is not a shop in this state (rule 3)
    assert _v([A("exclude_store", store_id="libris")], one).status == "unsupported"
    two = dict(STATE, store_ids=["libris", "emag"])
    assert _v([A("exclude_store", store_id="libris")], two).status == "ok"
    both = [A("exclude_store", store_id="libris"), A("exclude_store", store_id="emag")]
    assert _v(both, two).status == "unsupported"
    narrowed = dict(STATE, selected_store_ids=["emag"])
    assert _v([A("exclude_store", store_id="emag")], narrowed).status == "unsupported"
    assert _v([A("include_store", store_id="libris"), A("exclude_store", store_id="emag")], narrowed).status == "ok"


def test_rule6_empty_long_numeric_url():
    assert ask.validate({"actions": []}, STATE).status == "unsupported"
    long_id = "x" * 41
    st = dict(STATE, store_ids=STATE["store_ids"] + [long_id])
    assert _v([A("exclude_store", store_id=long_id)], st).status == "unsupported"
    assert _v([A("pin_editions", mode="current", price=1)]).status == "unsupported"
    assert _v([A("set_tab", tab="one", price=1.5)]).status == "unsupported"
    nested = {"actions": [TAB], "x": {"a": 1}}
    assert ask.validate(nested, STATE).status == "unsupported"
    url = dict(STATE, store_ids=["http://evil.example", "libris"])
    assert _v([A("exclude_store", store_id="http://evil.example")], url).status == "unsupported"


def test_rule7_model_errors(client, model):
    for bad in ("", "no json at all", "[1,2]", "null", "{"):
        model.reply = bad
        r = _ask(client, "do something unusual with the basket")
        assert r.status_code == 200
        assert r.json()["reply_key"] == "askUnsupported" and r.json()["status"] == "unsupported"
    model.error = RuntimeError("model HTTP 500")
    r = _ask(client, "do something unusual with the basket")
    assert r.status_code == 200 and r.json()["reply_key"] == "askUnsupported"
    model.error = TimeoutError("slow")
    assert _ask(client, "do something unusual with the basket").status_code == 200


def test_budget_refusal_is_unavailable(client, model):
    model.error = meta_budget.CapExceeded(9.99, 0.01)
    r = _ask(client, "put it all together somehow")
    assert r.status_code == 200
    assert r.json() == {"status": "unsupported", "actions": [], "reply_key": "askUnavailable", "reply_args": {}}
    window = {"provider": "meta", "from": "2026-10-30T00:00:00+02:00", "cap_usd": 10.0, "note": ""}
    model.error = meta_budget.WindowCapExceeded(window, 10.0, 0.01)
    assert _ask(client, "put it all together somehow").json()["reply_key"] == "askUnavailable"


# ---------------------------------------------------------------- hostile model outputs


HOSTILE = {
    "unknown action": {"actions": [A("delete_everything")]},
    "extra key": {"actions": [{"name": "set_tab", "args": {"tab": "one"}, "note": "hi"}]},
    "injected id": {"actions": [A("exclude_store", store_id="amazon_de; drop")]},
    "string bool": {"actions": [A("set_membership", membership_id="emag_genius", on="true")]},
    "five actions": {"actions": [TAB, EXC, INC, MEM, PIN]},
    "nested dict": {"actions": [A("exclude_store", store_id={"id": "amazon_de"})]},
    "10KB string": {"actions": [A("exclude_store", store_id="a" * 10240)]},
    "10KB key": {"actions": [TAB], "a" * 10240: 1},
    "top-level extra": {"actions": [TAB], "reply": "Done! Total is 12 lei."},
    "prose field": {"reply": "I bought it for you"},
    "price": {"actions": [A("set_tab", tab="one", price=12.5)]},
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_hostile_json_is_unsupported_not_500(client, model, name):
    model.reply = HOSTILE[name]
    r = _ask(client, "something the table does not know")
    assert r.status_code == 200
    assert r.json()["status"] == "unsupported" and r.json()["actions"] == []
    assert r.json()["reply_key"] == "askUnsupported"


@pytest.mark.parametrize(
    "raw",
    [
        'Sure! Here you go: {"actions":[{"name":"set_tab","args":{"tab":"one"}}]} hope that helps',
        'Here: {"actions":[{"name":"set_tab","args":{"tab":"one"}}]}',
        '{"actions":[{"name":"set_tab","args":{"tab":"one"}}]} Done!',
        '{"actions":[{"name":"set_tab","args":{"tab":"one"}}]}{"actions":[]}',
    ],
)
def test_prose_around_json_is_unsupported(client, model, raw):
    model.reply = raw
    r = _ask(client, "something the table does not know")
    assert r.status_code == 200 and r.json()["status"] == "unsupported"


def test_bare_json_and_one_fence_are_accepted(client, model):
    ok = '{"actions":[{"name":"set_tab","args":{"tab":"one"}}]}'
    for raw in (ok, "```json\n" + ok + "\n```"):
        model.reply = raw
        assert _ask(client, "something the table does not know").json()["status"] == "ok"


# ---------------------------------------------------------------- fast path and prompt


def test_fast_path_makes_zero_model_calls(client, model):
    model.error = AssertionError("model must not be called")
    for text in ("no Amazon", "keep it to one order", "I have Genius", "exact editions only", "fără Amazon"):
        r = _ask(client, text)
        assert r.status_code == 200 and r.json()["status"] == "ok", text
    assert model.calls == []


def test_fast_path_hostile_suffix_goes_to_model_not_executed(client, model):
    model.reply = {"actions": []}
    r = _ask(client, "no amazon_de; drop table books")
    assert r.json()["status"] == "unsupported" and len(model.calls) == 1


def test_fast_path_needs_ids_from_state(client, model):
    st = copy.deepcopy(STATE)
    st["store_ids"] = ["libris", "emag"]
    r = _ask(client, "no Amazon", st)
    assert r.json()["status"] == "unsupported"  # amazon_de is not in this state
    assert len(model.calls) == 1


def test_prompt_holds_only_sentence_and_id_lists(client, model):
    st = copy.deepcopy(STATE)
    st["items"] = [{"item_id": "SECRET-ITEM-9", "editions": ["Hardcover SECRET-EDITION"]}]
    st["edition_pins"] = {"SECRET-ITEM-9": "Hardcover SECRET-EDITION"}
    model.reply = {"actions": []}
    _ask(client, "bring them together somehow", st)
    assert len(model.calls) == 1
    body = model.calls[0]["body"]
    assert model.calls[0]["note"] == "ask-map"
    prompt = body["input"][0]["content"][0]["text"]
    assert prompt == ask.MAP_PROMPT + "\n\n" + ask.build_user_text("bring them together somehow", st)
    user_part = ask.build_user_text("bring them together somehow", st)
    assert user_part.splitlines()[0] == 'SENTENCE: "bring them together somehow"'
    assert json.loads(user_part.splitlines()[1].split(": ", 1)[1]) == st["store_ids"]
    assert json.loads(user_part.splitlines()[2].split(": ", 1)[1]) == st["membership_ids"]
    assert len(user_part.splitlines()) == 3
    assert "SECRET" not in prompt and "lei" not in prompt.lower().replace("lei.", "")


def test_no_http_in_ask_module():
    src = (Path(ask.__file__)).read_text(encoding="utf-8")
    for needle in ("urllib", "requests", "httpx", "http.client", "socket", "api.meta", "baseten"):
        assert needle not in src


# ---------------------------------------------------------------- reply keys, limits, input


def test_reply_keys_and_args(client, model):
    r = _ask(client, "no Amazon").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDoneExclude", {"shop": "Amazon.de"})
    r = _ask(client, "add back Libris").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDoneInclude", {"shop": "Libris"})
    r = _ask(client, "I have Genius").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDoneMembership", {"name": "eMAG Genius"})
    r = _ask(client, "I don't have Genius").json()
    assert r["reply_key"] == "askDoneMembershipOff"
    r = _ask(client, "one order").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDoneTab", {"tab": "one"})
    r = _ask(client, "exact editions only").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDonePinned", {"n": 1})  # one book has an edition
    r = _ask(client, "any edition").json()
    assert (r["reply_key"], r["reply_args"]) == ("askDonePinsCleared", {})
    r = _ask(client, "no Amazon and one order").json()
    assert [x["reply_key"] for x in r["replies"]] == ["askDoneExclude", "askDoneTab"]


def test_no_prose_or_numbers_in_ok_reply(client, model):
    r = _ask(client, "no Amazon and one order").json()
    flat = json.dumps(r)
    assert "lei" not in flat and "RON" not in flat


def test_input_limits(client, model):
    assert _ask(client, "x" * 300).status_code == 200
    assert _ask(client, "x" * 301).status_code == 422
    assert _ask(client, "").status_code == 422
    assert client.post("/ask", json={"text": "hi", "lang": "fr", "state": STATE}).status_code == 422
    assert client.post("/ask", json={"text": "   ", "lang": "en", "state": STATE}).json()["status"] == "unsupported"
    assert _ask(client, "x" * 300).json()["status"] == "unsupported"


def test_shares_per_ip_bucket_with_why():
    c = TestClient(create_app())
    for _ in range(59):
        assert _ask(c, "one order").status_code == 200
    assert c.get("/health").status_code == 200  # the 60th request, any route
    assert _ask(c, "one order").status_code == 429


def test_ro_v1_totals_unchanged():
    sol = TestClient(create_app()).post("/solve").json()
    assert sol["total_cents"] == 51516

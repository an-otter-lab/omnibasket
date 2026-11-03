"""S17: a smaller Why prompt, one in-flight Muse call per payload hash, and the checker's "one order" case.
The model is mocked: no network, no spend."""

from __future__ import annotations

import copy
import json
import threading

import pytest
from fastapi.testclient import TestClient

from api import why
from api.app import create_app
from api.explain_check import check_explanation

meta_budget = why.meta_budget


@pytest.fixture(scope="module")
def payload() -> dict:
    return TestClient(create_app()).post("/solve").json()


@pytest.fixture()
def live_payload(payload) -> dict:
    """The sample with what a live payload adds: a row per shop and ISBN, and no one-order answer."""
    p = copy.deepcopy(payload)
    p["live_offers"] = [
        {"store_id": s, "status": "failed", "reason": "no_match_in_index", "price_cents": None, "listing_url": None,
         "isbn13": "97800000000%02d" % n, "ranked": False, "not_ranked_reason": "no_offer"}
        for n in range(40) for s in ("emag", "bookzone", "carturesti", "elefant", "books_express")
    ]
    p["one_parcel"] = {"status": "not_possible", "reason": "no single shop lists every book", "best_store_id": None,
                       "answer": None, "per_book_delta": [], "shops": []}
    return p


@pytest.fixture(autouse=True)
def fresh_cache():
    why.clear_cache()
    yield
    why.clear_cache()


def _prompt_text(payload, lang="en"):
    return why.build_prompt(payload, lang)


def test_prompt_sends_only_the_facts_the_paragraph_needs(payload):
    text = _prompt_text(payload)
    assert len(json.dumps(payload)) > 30000
    assert len(text) < 4000
    facts = json.loads(text.split("JSON:\n", 1)[1])
    assert facts["cheapest"]["total_cents"] == payload["cheapest"]["total_cents"]
    assert facts["cheapest"]["order_count"] == 2
    assert [o["shop"] for o in facts["cheapest"]["orders"]] == ["Amazon.de", "Libris"]
    assert facts["one_order"] == {"status": "ranked", "shop": "Libris", "total_cents": 55873, "more_than_cheapest_cents": 4357}
    sent = text.split("JSON:\n", 1)[1]
    for dropped in ("listing_url", "pages", "memberships", "isbn13", "amazon_de", "one_parcel"):
        assert dropped not in sent


def test_a_live_payload_stays_small_and_says_one_order_is_not_possible(live_payload):
    text = _prompt_text(live_payload, "ro")
    assert len(json.dumps(live_payload)) > 45000
    assert len(text) < 4000
    facts = json.loads(text.split("JSON:\n", 1)[1])
    assert facts["one_order"]["status"] == "not_possible"
    assert "total_cents" not in facts["one_order"]
    assert "live_offers" not in text and "no_match_in_index" not in text


def test_checker_accepts_one_order_not_possible(live_payload):
    for text in (
        "The cheapest split is 515,16 lei in two orders, at Amazon.de and Libris. One order is not possible, because no single shop has every book.",
        "Cea mai ieftină împărțire este 515,16 lei în două comenzi, la Amazon.de și Libris. O singură comandă nu este posibilă.",
    ):
        assert check_explanation(text, live_payload).ok, text


def test_checker_still_rejects_a_wrong_order_count(live_payload):
    result = check_explanation("The cheapest split is 515,16 lei in five orders.", live_payload)
    assert not result.ok


def test_without_a_one_order_option_one_order_is_still_a_claim(payload):
    p = copy.deepcopy(payload)
    p.pop("one_parcel")
    p["cheapest"]["not_ranked"] = []
    p["edition"] = None
    assert not check_explanation("The cheapest split is 515,16 lei in one order.", p).ok


class _SlowModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.release = threading.Event()
        self.entered = threading.Event()

    def __call__(self, body, estimate, note, provider="meta", timeout=120):
        self.calls.append(body)
        self.entered.set()
        self.release.wait(5)
        return {"output_text": self.reply}, {}


GOOD = (
    "The cheapest split is 515,16 lei in two orders, at Amazon.de and Libris. "
    "One order at Libris would cost 558,73 lei, 43,57 lei more."
)


def _run_parallel(n, fn):
    out, threads = [None] * n, []
    for i in range(n):
        t = threading.Thread(target=lambda i=i: out.__setitem__(i, fn()))
        threads.append(t)
        t.start()
    return out, threads


def test_identical_requests_in_flight_make_one_model_call(payload, monkeypatch):
    model = _SlowModel(GOOD)
    monkeypatch.setattr(meta_budget, "guarded_post", model)
    out, threads = _run_parallel(3, lambda: why.explain(payload, "en"))
    assert model.entered.wait(5)
    model.release.set()
    for t in threads:
        t.join(5)
    assert len(model.calls) == 1
    assert [r["source"] for r in out] == ["muse"] * 3
    assert all(r["text"] == GOOD for r in out)


def test_each_language_is_its_own_call(payload, monkeypatch):
    model = _SlowModel(GOOD)
    model.release.set()
    monkeypatch.setattr(meta_budget, "guarded_post", model)
    why.explain(payload, "en")
    why.explain(payload, "ro")
    why.explain(payload, "en")
    assert len(model.calls) == 2


def test_a_waiter_that_times_out_gets_the_template_and_no_second_call(payload, monkeypatch):
    model = _SlowModel(GOOD)
    monkeypatch.setattr(meta_budget, "guarded_post", model)
    monkeypatch.setattr(why, "INFLIGHT_WAIT_S", 0.05)
    out, threads = _run_parallel(1, lambda: why.explain(payload, "en"))
    assert model.entered.wait(5)
    second = why.explain(payload, "en")
    model.release.set()
    threads[0].join(5)
    assert second["source"] == "template"
    assert out[0]["source"] == "muse"
    assert len(model.calls) == 1


def test_a_failed_call_releases_the_waiters(payload, monkeypatch):
    def boom(body, estimate, note, provider="meta", timeout=120):
        raise TimeoutError("slow")

    monkeypatch.setattr(meta_budget, "guarded_post", boom)
    assert why.explain(payload, "en")["source"] == "template"
    assert why._inflight == {}


def test_max_output_tokens_is_the_approved_budget():
    # Card V2: Adrian approved 3000 (31 Oct); 1600 left reasoning runs with an empty answer.
    assert why.MAX_OUTPUT_TOKENS == 3000


# --- #12 review: what the browser posts to /why. The UI's adapt() (app.component.ts) renames
# /solve's one-shop key to `one_order` and deletes the old key, so a live /why payload carries
# `one_order` only. The facts, the checker and the template must read it (old key as fallback).
ONE_SHOP_KEY = "_".join(["one", "par" + "cel"])


@pytest.fixture()
def posted_live_payload(live_payload) -> dict:
    p = copy.deepcopy(live_payload)
    p["one_order"] = p.pop(ONE_SHOP_KEY)  # exactly what adapt() does in the browser
    return p


LIVE_EN = ("The cheapest split is 515,16 lei in two orders, at Amazon.de and Libris. "
           "No single shop has every book, so one order is not possible.")
LIVE_RO = ("Cea mai ieftină împărțire este 515,16 lei în două comenzi, la Amazon.de și Libris. "
           "Nicio librărie nu are toate cărțile, deci o comandă nu este posibilă.")


def test_posted_live_payload_has_no_old_key(posted_live_payload):
    assert ONE_SHOP_KEY not in posted_live_payload
    assert posted_live_payload["one_order"]["status"] == "not_possible"


def test_prompt_reads_one_order_from_a_posted_live_payload(posted_live_payload):
    facts = json.loads(_prompt_text(posted_live_payload, "en").split("JSON:\n", 1)[1])
    assert facts["one_order"]["status"] == "not_possible"
    assert "total_cents" not in facts["one_order"]


def test_checker_accepts_one_order_not_possible_on_a_posted_live_payload(posted_live_payload):
    for text in (LIVE_EN, LIVE_RO):
        result = check_explanation(text, posted_live_payload)
        assert result.ok, (text, result.failures)
    assert not check_explanation("The cheapest split is 515,16 lei in five orders.", posted_live_payload).ok


def test_template_is_the_same_for_either_key(live_payload, posted_live_payload):
    from api.explain_check import fallback_sentences

    assert fallback_sentences(posted_live_payload) == fallback_sentences(live_payload)


@pytest.mark.parametrize("lang,text", [("en", LIVE_EN), ("ro", LIVE_RO)])
def test_why_endpoint_keeps_the_muse_paragraph_for_a_posted_live_payload(posted_live_payload, monkeypatch, lang, text):
    calls = []

    def model(body, estimate, note, provider="meta", timeout=120):
        calls.append(body)
        return {"output_text": text}, {}

    monkeypatch.setattr(meta_budget, "guarded_post", model)
    res = TestClient(create_app()).post("/why", json={"payload": posted_live_payload, "lang": lang})
    assert res.status_code == 200
    body = res.json()
    assert (body["source"], body["text"]) == ("muse", text)
    assert len(calls) == 1


def _one_order_ties(payload, order_count):
    p = copy.deepcopy(payload)
    p["cheapest"]["order_count"] = order_count
    for key in ("one_order", "one_parcel"):
        if isinstance(p.get(key), dict) and isinstance(p[key].get("answer"), dict):
            p[key]["answer"]["delta_vs_cheapest_cents"] = 0
    return p


def test_one_order_that_is_the_cheapest_sends_no_comparison(payload):
    """3 Nov: a one-order cheapest answer read "…so it is 0,00 lei more than the cheapest". No 0,00 fact is sent."""
    facts = why.facts_of(_one_order_ties(payload, 1))
    assert facts["one_order"] == {"status": "is_the_cheapest", "shop": "Libris"}
    assert "0,00" not in why.build_prompt(_one_order_ties(payload, 1), "en").split("JSON:")[1]
    assert "is_the_cheapest" in why.PROMPT


def test_a_split_that_ties_one_order_says_same_total(payload):
    facts = why.facts_of(_one_order_ties(payload, 2))
    assert facts["one_order"]["same_total_as_cheapest"] is True
    assert "more_than_cheapest_cents" not in facts["one_order"]

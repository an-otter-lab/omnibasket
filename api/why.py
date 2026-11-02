"""Feature 3 backend: a short "why this split" paragraph written by Muse.

Muse writes; the checker decides. The paragraph is returned as source "muse"
only when api.explain_check.check_explanation passed. Any other outcome
(empty output, budget refusal, HTTP error, failed check) returns the plain
template sentence and logs the reason. No secret is ever logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402
from api.explain_check import check_explanation, display_name, fallback_sentences, one_order_of  # noqa: E402

log = logging.getLogger("omnibasket.why")

MAX_OUTPUT_TOKENS = 3000  # reasoning shares this budget; Adrian approved 3000 (card V2, 31 Oct)
EFFORT = "low"
INFLIGHT_WAIT_S = 30  # a second identical request waits for the first call instead of paying again
# One Why call: Muse spends most of its 3000 output tokens on reasoning and answers in 12 to 15 s
# (measured 3 Nov, 1,400 to 1,700 tokens out). 8 s cut every such call off, so the shopper always
# got the template sentence and the tokens were spent without a ledger row. The leader waits at
# most this long in total (connect, read and the /chat/completions fallback together; urlopen's own
# timeout is per socket operation), and it stays below INFLIGHT_WAIT_S, so a duplicate request
# always receives the leader's outcome.
MODEL_TIMEOUT_S = 25
TIMED_OUT = "model call timed out"

PROMPT = """You explain one shopping result to a shopper. Write ONE short paragraph (2 to 4 sentences) in {language}.

Rules:
- Use only facts from the JSON below: shop names, amounts, counts, shipping and fees.
- Write every amount exactly as the JSON states it (cents divided by 100, in lei), copied, never computed. Do not add, subtract or round anything yourself.
- Write amounts with a comma decimal and lei after the number, in both languages (515,16 lei). Never a dot decimal: 515.16 is wrong.
- Write shop names as Libris, Amazon.de, eMAG, Bookzone, never as ids like amazon_de.
- Name only shops that appear in the JSON. Say "order" (RO: "comandă"), never "parcel".
- Say why the cheapest split is cheapest for this basket and how it compares with buying everything in one order, if the JSON has that comparison. If one_order.status is "not_possible", say that no single shop has every book, and do not invent a one-order total.
- No headings, no lists, no markdown, no advice to buy.
- Output only the paragraph.

JSON:
{facts}
"""

# Muse sometimes writes a RON amount with a dot decimal (126.13 lei); the box shows 126,13 lei.
# Only a plain digits.dd token is rewritten, so a thousands separator (1.234) is left alone.
_DOT_DECIMAL = re.compile(r"(?<![\d.,])(\d+)\.(\d{2})(?!\d)")
_TRAILING = "\"'”’»)]}"


def normalize_amounts(text: str) -> str:
    """Rewrite a dot decimal as the comma decimal the box shows. 1.234,56 is untouched."""
    return _DOT_DECIMAL.sub(lambda m: m.group(1) + "," + m.group(2), text)


def sentence_ended(text: str) -> bool:
    """A paragraph cut mid-answer ("also totals 182") does not end in . ! ? and is not shown."""
    trimmed = (text or "").rstrip().rstrip(_TRAILING).rstrip()
    return bool(trimmed) and trimmed[-1] in ".!?"


MAX_CACHE = 256  # H1: answers kept in memory; the least recently used is dropped first
_cache: OrderedDict[str, dict] = OrderedDict()
_inflight: dict[str, threading.Event] = {}
_lock = threading.Lock()


def payload_hash(payload: dict, lang: str) -> str:
    """Stable sha256 of the canonical payload and language."""
    canonical = json.dumps({"lang": lang, "payload": payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# H1: /why accepts only a body shaped like a /solve result, so an arbitrary JSON body never reaches Muse.
_STATUSES = {"ranked", "not_ranked", "not_possible"}
_STORE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
MAX_BOOKS = 100
MAX_ORDERS = 20
MAX_TITLE = 500
MAX_CENTS = 100_000_000
_CENTS_KEYS = (
    "total_cents",
    "books_subtotal_cents",
    "delivery_cents",
    "order_fee_cents",
    "order_total_cents",
    "free_delivery_threshold_cents",
    "short_of_threshold_cents",
    "delta_vs_cheapest_cents",
    "price_cents",
)


def _cents_problem(row: dict, where: str) -> str | None:
    for key in _CENTS_KEYS:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_CENTS:
            return f"{where}.{key} is not an amount in cents"
    return None


def _order_problem(order: object, where: str) -> str | None:
    if not isinstance(order, dict):
        return f"{where} is not an object"
    store = order.get("store_id")
    if not isinstance(store, str) or not _STORE_ID.match(store):
        return f"{where}.store_id is not a shop id"
    books = order.get("books")
    if not isinstance(books, list) or len(books) > MAX_BOOKS:
        return f"{where}.books is not a list of at most {MAX_BOOKS}"
    for i, book in enumerate(books):
        if not isinstance(book, dict):
            return f"{where}.books[{i}] is not an object"
        title = book.get("title")
        if title is not None and (not isinstance(title, str) or len(title) > MAX_TITLE):
            return f"{where}.books[{i}].title is not a short string"
        problem = _cents_problem(book, f"{where}.books[{i}]")
        if problem:
            return problem
    known = order.get("delivery_known")
    if known is not None and not isinstance(known, bool):
        return f"{where}.delivery_known is not true or false"
    return _cents_problem(order, where)


def solve_result_problem(payload: object) -> str | None:
    """None when the body is shaped like a /solve result the UI would describe, else what is wrong."""
    if not isinstance(payload, dict):
        return "payload is not an object"
    books = payload.get("books")
    if not isinstance(books, list) or not 1 <= len(books) <= MAX_BOOKS:
        return f"books is not a list of 1 to {MAX_BOOKS}"
    if not all(isinstance(b, dict) for b in books):
        return "books holds a non-object"
    currency = payload.get("currency")
    if currency is not None and (not isinstance(currency, str) or len(currency) > 8):
        return "currency is not a currency code"
    problem = _cents_problem(payload, "payload")
    if problem:
        return problem
    cheapest = payload.get("cheapest")
    if not isinstance(cheapest, dict) or cheapest.get("status") not in _STATUSES:
        return "cheapest is not a split with a known status"
    orders = cheapest.get("orders")
    if not isinstance(orders, list) or not 1 <= len(orders) <= MAX_ORDERS:
        return f"cheapest.orders is not a list of 1 to {MAX_ORDERS}"
    count = cheapest.get("order_count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_ORDERS):
        return "cheapest.order_count is not a count"
    problem = _cents_problem(cheapest, "cheapest")
    for i, order in enumerate(orders):
        problem = problem or _order_problem(order, f"cheapest.orders[{i}]")
    if problem:
        return problem
    for key in ("one_order", "one_parcel"):
        one = payload.get(key)
        if one is None:
            continue
        if not isinstance(one, dict) or one.get("status") not in _STATUSES:
            return f"{key} is not a one-order answer with a known status"
        best = one.get("best_store_id")
        if best is not None and (not isinstance(best, str) or not _STORE_ID.match(best)):
            return f"{key}.best_store_id is not a shop id"
        answer = one.get("answer")
        if answer is not None:
            if not isinstance(answer, dict):
                return f"{key}.answer is not an object"
            problem = _cents_problem(answer, f"{key}.answer")
            if problem:
                return problem
    return None


def _remember(key: str, result: dict) -> None:
    """Store one answer; the caller holds _lock. Past MAX_CACHE the oldest-used answer goes."""
    _cache[key] = result
    _cache.move_to_end(key)
    while len(_cache) > MAX_CACHE:
        _cache.popitem(last=False)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _inflight.clear()


def _text_of(response: dict) -> str:
    if not isinstance(response, dict):
        return ""
    if response.get("output_text"):
        return str(response["output_text"])
    parts = []
    for block in response.get("output") or []:
        if not isinstance(block, dict):
            continue
        for piece in block.get("content") or []:
            if isinstance(piece, dict) and piece.get("text"):
                parts.append(piece["text"])
    if parts:
        return "".join(parts)
    choices = response.get("choices") or []
    if choices:
        return str((choices[0].get("message") or {}).get("content") or "")
    return ""


def _shop(store_id: object) -> str | None:
    return display_name(store_id) if isinstance(store_id, str) and store_id else None


def _order_facts(order: dict) -> dict:
    books = order.get("books") if isinstance(order.get("books"), list) else []
    row = {
        "shop": _shop(order.get("store_id")),
        "books": [b.get("title") for b in books if isinstance(b, dict) and b.get("title")],
    }
    for key in (
        "books_subtotal_cents",
        "delivery_cents",
        "delivery_known",
        "order_fee_cents",
        "order_total_cents",
        "free_delivery_threshold_cents",
        "threshold_crossed",
        "short_of_threshold_cents",
    ):
        if key in order:
            row[key] = order[key]
    return row


def facts_of(payload: dict) -> dict:
    """S17: only what the paragraph needs. A live payload carries every shop row, offer and read
    reason; sending all of it made Muse spend its whole output budget reasoning. The checker still
    judges the paragraph against the full payload."""
    cheapest = payload.get("cheapest") if isinstance(payload.get("cheapest"), dict) else {}
    orders = cheapest.get("orders") if isinstance(cheapest.get("orders"), list) else []
    books = payload.get("books") if isinstance(payload.get("books"), list) else []
    facts: dict = {
        "currency": cheapest.get("currency") or payload.get("currency") or "RON",
        "book_count": len(books) if books else sum(len(o.get("books") or []) for o in orders if isinstance(o, dict)),
        "cheapest": {
            "status": cheapest.get("status"),
            "total_cents": cheapest.get("total_cents", payload.get("total_cents")),
            "books_subtotal_cents": cheapest.get("books_subtotal_cents"),
            "order_count": cheapest.get("order_count", len(orders)),
            "orders": [_order_facts(o) for o in orders if isinstance(o, dict)],
        },
    }
    one = one_order_of(payload)
    if one is not None:
        answer = one.get("answer") if isinstance(one.get("answer"), dict) else {}
        one_facts: dict = {"status": one.get("status"), "shop": _shop(one.get("best_store_id"))}
        if answer:
            one_facts["total_cents"] = answer.get("total_cents")
            one_facts["more_than_cheapest_cents"] = answer.get("delta_vs_cheapest_cents")
        if one.get("status") == "not_possible" and one.get("reason"):
            one_facts["reason"] = one.get("reason")
        facts["one_order"] = one_facts
    return facts


def _facts(payload: dict) -> str:
    return json.dumps(facts_of(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_prompt(payload: dict, lang: str) -> str:
    language = "Romanian" if lang == "ro" else "English"
    return PROMPT.format(language=language, facts=_facts(payload))


def _template(payload: dict, lang: str, reason: str) -> dict:
    ro, en = fallback_sentences(payload)
    log.warning("why: template used (%s)", reason)
    return {"text": ro if lang == "ro" else en, "source": "template", "lang": lang, "model": None, "reason": reason}


def explain(
    payload: dict,
    lang: str = "en",
    *,
    use_cache: bool = True,
    may_call: Callable[[], bool] | None = None,
) -> dict:
    """Return {text, source, lang, model[, reason]}. Never raises for model trouble.

    H1: may_call is asked only when Muse would be called (not for a cached answer or a request
    waiting on an identical one). When it says no, the template sentence is returned, uncached."""
    lang = "ro" if str(lang).lower().startswith("ro") else "en"
    key = payload_hash(payload, lang)
    if not use_cache:
        if may_call is not None and not may_call():
            return _template(payload, lang, "per-IP /why limit")
        return dict(_ask(payload, lang))
    # S17: one in-flight call per payload hash. A page load that posts the same /why three times
    # in the same second pays for one call; the others wait for its answer.
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return dict(hit)
        pending = _inflight.get(key)
        if pending is None:
            pending = _inflight[key] = threading.Event()
            leader = True
        else:
            leader = False
    if not leader:
        pending.wait(INFLIGHT_WAIT_S)
        with _lock:
            hit = _cache.get(key)
        if hit is not None:
            return dict(hit)
        return _template(payload, lang, "identical request still in flight")
    try:
        if may_call is not None and not may_call():
            return _template(payload, lang, "per-IP /why limit")
        result = _ask_within(payload, lang, key)
        if result.get("reason") != TIMED_OUT:
            with _lock:
                _remember(key, result)
    finally:
        with _lock:
            _inflight.pop(key, None)
        pending.set()
    return dict(result)


def _ask_within(payload: dict, lang: str, key: str) -> dict:
    """_ask with a hard MODEL_TIMEOUT_S bound on the caller's wait.

    The call runs on a daemon thread. Past the bound the caller gets the template; an answer
    that arrives later was paid for, so it is cached for the next identical request."""
    state: dict = {"result": None, "abandoned": False}
    finished = threading.Event()

    def run() -> None:
        try:
            result = _ask(payload, lang)
        except Exception as exc:  # _ask does not raise; this only guards the thread
            result = _template(payload, lang, f"model call failed: {type(exc).__name__}")
        with _lock:
            if state["abandoned"]:
                if result.get("source") == "muse":
                    _remember(key, result)
            else:
                state["result"] = result
        finished.set()

    threading.Thread(target=run, name="why-model-call", daemon=True).start()
    finished.wait(MODEL_TIMEOUT_S)
    with _lock:
        if state["result"] is not None:
            return state["result"]
        state["abandoned"] = True
    return _template(payload, lang, TIMED_OUT)


def _ask(payload: dict, lang: str) -> dict:
    prompt = build_prompt(payload, lang)
    body = {
        "model": meta_budget.MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "reasoning": {"effort": EFFORT},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    try:
        estimate = meta_budget.compute_cost(len(prompt) // 3 + 200, MAX_OUTPUT_TOKENS)
        response, _row = meta_budget.guarded_post(body, estimate, note="why-this-split", timeout=MODEL_TIMEOUT_S)
    except Exception as exc:  # budget refusal, HTTP, network, missing key, timeout
        return _template(payload, lang, f"model call failed: {type(exc).__name__}")
    text = _text_of(response).strip()
    if not text:
        return _template(payload, lang, "empty model output")
    if not sentence_ended(text):
        return _template(payload, lang, "truncated model output")
    # A dot decimal is shown as a comma decimal, or the paragraph is dropped by the checker below.
    text = normalize_amounts(text)
    try:
        check = check_explanation(text, payload)
    except Exception as exc:
        return _template(payload, lang, f"checker error: {type(exc).__name__}")
    if not check.ok:
        reasons = "; ".join(f.reason for f in check.failures[:4])
        return _template(payload, lang, f"checker failed: {reasons}")
    return {"text": text, "source": "muse", "lang": lang, "model": meta_budget.MODEL}

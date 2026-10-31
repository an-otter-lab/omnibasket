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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402
from api.explain_check import check_explanation, display_name, fallback_sentences, one_order_of  # noqa: E402

log = logging.getLogger("omnibasket.why")

MAX_OUTPUT_TOKENS = 3000  # reasoning shares this budget; Adrian approved 3000 (card V2, 31 Oct)
EFFORT = "low"
INFLIGHT_WAIT_S = 30  # a second identical request waits for the first call instead of paying again

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


_cache: dict[str, dict] = {}
_inflight: dict[str, threading.Event] = {}
_lock = threading.Lock()


def payload_hash(payload: dict, lang: str) -> str:
    """Stable sha256 of the canonical payload and language."""
    canonical = json.dumps({"lang": lang, "payload": payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def explain(payload: dict, lang: str = "en", *, use_cache: bool = True) -> dict:
    """Return {text, source, lang, model[, reason]}. Never raises for model trouble."""
    lang = "ro" if str(lang).lower().startswith("ro") else "en"
    key = payload_hash(payload, lang)
    if not use_cache:
        return dict(_ask(payload, lang))
    # S17: one in-flight call per payload hash. A page load that posts the same /why three times
    # in the same second pays for one call; the others wait for its answer.
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
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
        result = _ask(payload, lang)
        with _lock:
            _cache[key] = result
    finally:
        with _lock:
            _inflight.pop(key, None)
        pending.set()
    return dict(result)


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
        response, _row = meta_budget.guarded_post(body, estimate, note="why-this-split", timeout=8)
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

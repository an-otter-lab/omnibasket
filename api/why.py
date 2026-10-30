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
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402
from api.explain_check import check_explanation, fallback_sentences  # noqa: E402

log = logging.getLogger("omnibasket.why")

MAX_OUTPUT_TOKENS = 1600  # reasoning shares this budget; never below 1200
EFFORT = "low"
_DROPPED_KEYS = {"pages", "events"}

PROMPT = """You explain one shopping result to a shopper. Write ONE short paragraph (2 to 4 sentences) in {language}.

Rules:
- Use only facts from the JSON below: shop names, amounts, counts, shipping and fees.
- Write every amount exactly as the JSON states it (cents divided by 100, in lei), copied, never computed. Do not add, subtract or round anything yourself.
- Write shop names as Libris, Amazon.de, eMAG, Bookzone, never as ids like amazon_de. Write amounts with a comma decimal in Romanian (515,16 lei) and a dot in English (515.16 lei).
- Name only shops that appear in the JSON. Say "order" (RO: "comandă"), never "parcel".
- Say why the cheapest split is cheapest for this basket and how it compares with buying everything in one order, if the JSON has that comparison.
- No headings, no lists, no markdown, no advice to buy.
- Output only the paragraph.

JSON:
{facts}
"""

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def payload_hash(payload: dict, lang: str) -> str:
    """Stable sha256 of the canonical payload and language."""
    canonical = json.dumps({"lang": lang, "payload": payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


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


def _facts(payload: dict) -> str:
    kept = {k: v for k, v in payload.items() if k not in _DROPPED_KEYS}
    return json.dumps(kept, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit is not None:
            return dict(hit)
    result = _ask(payload, lang)
    if use_cache:
        with _lock:
            _cache[key] = result
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
        response, _row = meta_budget.guarded_post(body, estimate, note="why-this-split")
    except Exception as exc:  # budget refusal, HTTP, network, missing key
        return _template(payload, lang, f"model call failed: {type(exc).__name__}")
    text = _text_of(response).strip()
    if not text:
        return _template(payload, lang, "empty model output")
    try:
        check = check_explanation(text, payload)
    except Exception as exc:
        return _template(payload, lang, f"checker error: {type(exc).__name__}")
    if not check.ok:
        reasons = "; ".join(f.reason for f in check.failures[:4])
        return _template(payload, lang, f"checker failed: {reasons}")
    return {"text": text, "source": "muse", "lang": lang, "model": meta_budget.MODEL}

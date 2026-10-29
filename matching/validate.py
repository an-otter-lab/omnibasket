"""Reject extraction answers the 27 Oct spike showed were unsafe to keep.

A rejected answer is marked for re-read. It is not rewritten into a guess.
"""

from __future__ import annotations

import re

from matching.isbn import normalize_isbn13

# Points / stamp counters that the model parked in membership_note.
_POINTS = re.compile(
    r"puncte\s+express|\b\d+\s*puncte\b|loyalty\s+points|\bpoints?\s*[:#]?\s*\d+\b|\bstamps?\b",
    re.IGNORECASE,
)


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown"}:
        return None
    return text


def _as_tristate(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y"}:
        return True
    if text in {"false", "no", "n"}:
        return False
    if text in {"null", "none", ""}:
        return None
    return value


def _named_seller(sold_by, ships_from) -> bool:
    """A seller or fulfiller string is present. The store's own name still counts as named."""
    return bool(sold_by or ships_from)


def validate_extraction(obj: dict) -> tuple[dict, dict]:
    """Normalise ISBN and flag answers that must be read again.

    Rules:
    - sold_and_shipped_by_store false is rejected unless sold_by or ships_from
      names someone. Missing seller is null, not false.
    - membership_note that is only a points/loyalty counter is rejected.
    - isbn13 is hyphen-stripped and check-digit checked; invalid becomes null
      and, when the model sent a non-empty value, is a re-read reason.
    """
    if not isinstance(obj, dict):
        raise TypeError("extraction must be an object")
    out = dict(obj)
    reasons = []

    raw_isbn = out.get("isbn13")
    isbn = normalize_isbn13(raw_isbn)
    if _clean(raw_isbn) is not None and isbn is None:
        reasons.append("isbn_invalid")
    out["isbn13"] = isbn

    flag = _as_tristate(out.get("sold_and_shipped_by_store"))
    out["sold_and_shipped_by_store"] = flag if flag in (True, False, None) else None
    if flag not in (True, False, None):
        reasons.append("sold_flag_not_tristate")
        out["sold_and_shipped_by_store"] = None
    sold_by = _clean(out.get("sold_by"))
    ships_from = _clean(out.get("ships_from"))
    out["sold_by"] = sold_by
    out["ships_from"] = ships_from
    if out["sold_and_shipped_by_store"] is False and not _named_seller(sold_by, ships_from):
        reasons.append("false_without_named_seller")

    note = out.get("membership_note")
    if isinstance(note, str) and _POINTS.search(note):
        reasons.append("membership_is_points_counter")

    reread = bool(reasons)
    verdict = {"accepted": not reread, "reread": reread, "reasons": reasons}
    return out, verdict


# ---------------------------------------------------------------- read vs capture

# A model read is checked against the saved page, never written into it.
MATCH = "match"
MISMATCH = "mismatch"
NOT_READ = "not_read"

_LEI = {"lei", "ron", "lei românești", "lei romanești"}


def _price_cents(value):
    """The model's price is a number; the capture is integer cents."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = re.sub(r"[^\d.,-]", "", value)
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def read_fields(record):
    """The fields a stored read returned, across the two shapes we keep."""

    if not isinstance(record, dict):
        return None
    fields = record.get("fields")
    if isinstance(fields, dict):
        return fields
    result = record.get("result")
    return result if isinstance(result, dict) else None


def compare_read_to_capture(
    record,
    *,
    price_cents: int | None,
    isbn13: str | None = None,
    currency: str = "RON",
) -> dict:
    """Check one stored Muse Spark read against the captured page.

    ``match`` and ``mismatch`` come only from comparing what the model returned
    with what the capture holds. A read that has nothing to compare is
    ``not_read`` with a reason. Nothing here changes a price.
    """

    if not isinstance(record, dict):
        return {"status": NOT_READ, "mismatch_fields": [], "reason": "no_read"}
    status = str(record.get("status") or "")
    fields = read_fields(record)
    if status and status != "OK":
        return {"status": NOT_READ, "mismatch_fields": [], "reason": "read_failed"}
    if not fields:
        return {"status": NOT_READ, "mismatch_fields": [], "reason": "no_fields"}

    model_cents = _price_cents(fields.get("price"))
    if model_cents is None:
        return {"status": NOT_READ, "mismatch_fields": [], "reason": "price_not_printed"}
    if price_cents is None:
        return {"status": NOT_READ, "mismatch_fields": [], "reason": "capture_has_no_price"}

    differing = []
    if model_cents != int(price_cents):
        differing.append("price")

    printed_currency = str(fields.get("currency") or "").strip()
    if printed_currency and printed_currency.lower() not in _LEI | {currency.lower()}:
        differing.append("currency")

    printed_isbn = normalize_isbn13(fields.get("isbn13"))
    if printed_isbn and isbn13 and printed_isbn != isbn13:
        differing.append("isbn13")

    if differing:
        return {"status": MISMATCH, "mismatch_fields": differing, "reason": None}
    return {"status": MATCH, "mismatch_fields": [], "reason": None}

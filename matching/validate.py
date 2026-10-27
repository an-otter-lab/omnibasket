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

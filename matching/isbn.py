"""ISBN-13 normalisation. Hyphens are stripped; a bad check digit is not a guess."""

from __future__ import annotations

import re

BOOK_PREFIXES = ("978", "979")
_SEPARATORS = re.compile(r"[\s\-\u00ad\u2010\u2011\u2012\u2013\u2014]")


def isbn13_check_digit(first12: str) -> str:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("isbn13_check_digit wants 12 digits")
    total = 0
    for i, ch in enumerate(first12):
        n = ord(ch) - 48
        total += n if i % 2 == 0 else n * 3
    return str((10 - (total % 10)) % 10)


def normalize_isbn13(value) -> str | None:
    """Return 13 digits, or None when the value is missing, is not 978/979, or the check digit fails.

    Hyphens, spaces and other separators are removed first. ISBN-10 and bare
    product codes are not promoted into an ISBN-13.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    digits = _SEPARATORS.sub("", text)
    # Letters mean this is a product code or other token, not an ISBN-13.
    if len(digits) != 13 or not digits.isdigit():
        return None
    # S4b: an ISBN-13 always starts 978 or 979. Anything else (642..., 594...) is a shop or
    # product barcode, even when its check digit works out.
    if digits[:3] not in BOOK_PREFIXES:
        return None
    if isbn13_check_digit(digits[:12]) != digits[12]:
        return None
    return digits

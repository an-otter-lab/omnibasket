"""Strong title + author match, used only when a shop page declares another ISBN.

A different printing of the same work is shown honestly as such. A different
book with a merely similar title never matches.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

THRESHOLD = 0.92


def fold(text: str | None) -> str:
    """Lowercase, no diacritics, punctuation as single spaces."""
    if not text:
        return ""
    base = unicodedata.normalize("NFKD", str(text))
    base = "".join(ch for ch in base if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", base).split())


def surname(author: str | None) -> str:
    tokens = fold(author).split()
    return tokens[-1] if tokens else ""


def _strip_author_suffix(name: str, authors: list[str]) -> str:
    """Shop names read Title - Author; drop that trailing author part."""
    for sep in (" - ", " – ", " — "):
        if sep in name:
            head, _, tail = name.rpartition(sep)
            if any(surname(a) and surname(a) in fold(tail).split() for a in authors):
                return head
    return name


def strong_match(want_title: str | None, want_author: str | None, page_name: str | None, page_authors: list[str]) -> bool:
    """Same work: near-equal normalised title, same numbers, same author surname."""
    want = fold(want_title)
    last = surname(want_author)
    if not want or not last or not page_name or not page_authors:
        return False
    if not any(last in fold(a).split() for a in page_authors):
        return False
    have = fold(_strip_author_suffix(page_name, page_authors))
    if not have:
        return False
    if sorted(re.findall(r"\d+", want)) != sorted(re.findall(r"\d+", have)):
        return False
    return SequenceMatcher(None, want, have).ratio() >= THRESHOLD

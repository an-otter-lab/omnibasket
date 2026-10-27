"""Match offers by edition.

strict_isbn keeps only one ISBN-13 together.
same_story groups a title but keeps each edition separate.
Prices are never averaged across editions.
"""

from __future__ import annotations

import re
from collections import defaultdict

from matching.isbn import normalize_isbn13

_EDITION_WORDS = (
    "board book",
    "boardbook",
    "paperback",
    "hardcover",
    "hardback",
    "pappband",
    "taschenbuch",
    "cartonata",
    "cartonată",
    "integral",
    "edition",
    "editie",
    "ediție",
)


def story_key(title: str) -> str:
    text = (title or "").lower()
    text = text.replace("ă", "a").replace("â", "a").replace("î", "i").replace("ș", "s").replace("ț", "t")
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    for word in _EDITION_WORDS:
        text = text.replace(word, " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _edition_id(offer: dict, isbn: str | None) -> str:
    if isbn:
        return isbn
    label = (offer.get("edition") or offer.get("format") or "unspecified").strip().lower()
    return "no-isbn:" + re.sub(r"\s+", " ", label)


def _prices(offers: list[dict]) -> list[float]:
    found = []
    for offer in offers:
        price = offer.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            found.append(float(price))
    return found


def edition_price_summary(offers: list[dict]) -> dict:
    """Min and max inside one edition. No mean, so two editions cannot collapse to a midpoint."""
    prices = _prices(offers)
    if not prices:
        return {"n": 0, "min": None, "max": None, "prices": []}
    return {"n": len(prices), "min": min(prices), "max": max(prices), "prices": prices}


def _pack_edition(edition_key: str, offers: list[dict], primary_isbn: str | None) -> dict:
    isbn = edition_key if not edition_key.startswith("no-isbn:") else None
    labels = []
    for offer in offers:
        label = offer.get("edition") or offer.get("format")
        if label and label not in labels:
            labels.append(label)
    return {
        "edition_key": edition_key,
        "isbn13": isbn,
        "edition": labels[0] if labels else None,
        "differs": bool(primary_isbn and isbn != primary_isbn),
        "offers": offers,
        "price": edition_price_summary(offers),
    }


def match_offers(offers: list[dict], mode: str, primary_isbn: str | None = None) -> dict:
    """Group offers.

    strict_isbn: one group per valid ISBN-13. Offers with no valid ISBN stay unmatched
    and are not given a price slot in any group.
    same_story: one group per normalised title. Editions inside the group stay split.
    The group has no price field. Differing editions are marked differs=true against
    primary_isbn when that ISBN is passed, otherwise against the first ISBN seen.
    """
    if mode not in {"strict_isbn", "same_story"}:
        raise ValueError("mode must be strict_isbn or same_story")
    primary = normalize_isbn13(primary_isbn) if primary_isbn else None
    groups = []
    unmatched = []

    if mode == "strict_isbn":
        buckets: dict[str, list] = defaultdict(list)
        for offer in offers:
            isbn = normalize_isbn13(offer.get("isbn13"))
            if not isbn:
                unmatched.append(offer)
                continue
            buckets[isbn].append(offer)
        for isbn, bucket in buckets.items():
            edition = _pack_edition(isbn, bucket, primary or isbn)
            edition["differs"] = bool(primary and isbn != primary)
            groups.append(
                {
                    "mode": mode,
                    "key": isbn,
                    "title": bucket[0].get("title"),
                    "editions": [edition],
                    "price": None,
                }
            )
    else:
        buckets = defaultdict(list)
        for offer in offers:
            key = story_key(offer.get("title") or "")
            if not key:
                unmatched.append(offer)
                continue
            buckets[key].append(offer)
        for key, bucket in buckets.items():
            by_edition: dict[str, list] = defaultdict(list)
            order = []
            for offer in bucket:
                isbn = normalize_isbn13(offer.get("isbn13"))
                eid = _edition_id(offer, isbn)
                if eid not in by_edition:
                    order.append(eid)
                by_edition[eid].append(offer)
            anchor = primary
            if anchor is None:
                for eid in order:
                    if not eid.startswith("no-isbn:"):
                        anchor = eid
                        break
            editions = [_pack_edition(eid, by_edition[eid], anchor) for eid in order]
            groups.append(
                {
                    "mode": mode,
                    "key": key,
                    "title": bucket[0].get("title"),
                    "editions": editions,
                    "price": None,
                }
            )

    return {"mode": mode, "groups": groups, "unmatched": unmatched, "averaged": False}


def cross_edition_average(_group: dict):
    """Always None. Callers must read edition['price'], never a blend."""
    return None

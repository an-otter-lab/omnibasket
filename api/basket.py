"""Load the locked Romanian basket without changing its files.

A store whose threshold, shipping fee, or per-order fee is null is left
out. Those nulls are not filled from a percent, a minimum, or another
currency. eMAG is that case: the yaml fee is a percent with a floor, and
the solver only accepts one integer fee it was given.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from solver.optimize import unresolved_fee_fields, store_if_fees_resolved
from solver.types import Item, Offer, Store

ROOT = Path(__file__).resolve().parents[1]
BASKET_PATH = ROOT / "data" / "baskets" / "ro-v1.yaml"
STORES_PATH = ROOT / "data" / "stores" / "ro.yaml"

class BasketError(ValueError):
    pass


def load_locked() -> tuple[str, str, list[Store], list[Item], list[dict]]:
    """Return day, currency, stores, items, and the raw offer rows.

    Offer rows keep the ISBN and the capture date so the cache can be keyed
    without inventing a price.
    """

    basket = yaml.safe_load(BASKET_PATH.read_text())
    rules = yaml.safe_load(STORES_PATH.read_text())
    day = str(basket["checked_at"])
    currency = str(basket["currency"])
    allowed = set(basket["solved_store_ids"])
    by_id = {}
    for row in rules["stores"]:
        if row["id"] not in allowed:
            continue
        store = _store(row, currency)
        if store is None:
            continue
        by_id[row["id"]] = store
    unknown = allowed - {row["id"] for row in rules["stores"] if row["id"] in allowed}
    if unknown:
        raise BasketError("locked basket names unknown stores: " + ", ".join(sorted(unknown)))
    stores = [by_id[store_id] for store_id in basket["solved_store_ids"] if store_id in by_id]
    items: list[Item] = []
    pages: list[dict] = []
    for book in basket["books"]:
        offers = []
        isbn = book.get("isbn13") or ""
        solvable = {store.id for store in stores}
        for offer in book["offers"]:
            # Page rows keep the ISBN the cache is keyed on. An excluded store is not solved.
            pages.append(
                {
                    "item_id": book["id"],
                    "title": book["title"],
                    "store_id": offer["store_id"],
                    "isbn13": isbn,
                    "day": day,
                    "capture": offer.get("capture"),
                    "price_cents": int(offer["price_cents"]),
                    "seller_certainty": offer["seller_certainty"],
                    "currency": currency,
                    # Optional, copied as printed. Null when the lock has none.
                    "listing_url": offer.get("listing_url"),
                    "edition": offer.get("edition"),
                    "read_at": _text(offer.get("read_at")),
                    "in_stock": offer.get("in_stock"),
                }
            )
            if offer["store_id"] not in solvable:
                continue
            offers.append(
                Offer(
                    store_id=offer["store_id"],
                    price_cents=int(offer["price_cents"]),
                    seller_certainty=offer["seller_certainty"],
                )
            )
        items.append(Item(id=book["id"], offers=tuple(offers)))
    return day, currency, stores, items, pages


def _text(value) -> str | None:
    """YAML dates arrive as date objects; the API carries them as text."""

    return None if value is None else str(value)


def locked_shop_rows() -> list[dict]:
    """Every shop the lock names, solvable or not, with its read stamp.

    Fee fields are copied unchanged. Null stays null.
    """

    basket = yaml.safe_load(BASKET_PATH.read_text())
    rules = yaml.safe_load(STORES_PATH.read_text())
    by_id = {row["id"]: row for row in rules["stores"]}
    rows = []
    for store_id in basket["solved_store_ids"]:
        row = by_id[store_id]
        rows.append(
            {
                "id": store_id,
                "solvable": store_if_fees_resolved(row) is not None,
                "read_at": _text(row.get("read_at")),
                "fees": unresolved_fee_fields(row),
                "shipping_fee_cents": row.get("shipping_fee_cents"),
            }
        )
    return rows


def excluded_for_unresolved_fees() -> list[dict]:
    """Stores named by the lock whose solver fees are still null."""

    basket = yaml.safe_load(BASKET_PATH.read_text())
    rules = yaml.safe_load(STORES_PATH.read_text())
    allowed = set(basket["solved_store_ids"])
    excluded = []
    for row in rules["stores"]:
        if row["id"] not in allowed:
            continue
        if store_if_fees_resolved(row) is not None:
            continue
        excluded.append(
            {
                "id": row["id"],
                "reason": "unresolved fee",
                **unresolved_fee_fields(row),
            }
        )
    return excluded


def _store(row: dict, basket_currency: str) -> Store | None:
    currency = row.get("currency") or ""
    if currency != basket_currency:
        # Leave the mismatch for the solver. Do not convert.
        pass
    return store_if_fees_resolved(row)

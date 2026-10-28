"""Load the locked Romanian basket without changing its files.

Store fees for eMAG follow the same integers the lock test passes into
solve(): the published minimum per-order fee, no shipping line, and a
threshold the flat fee never treats as free shipping. Null yaml fees are
not converted from another currency.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from solver.types import Item, Offer, Store

ROOT = Path(__file__).resolve().parents[1]
BASKET_PATH = ROOT / "data" / "baskets" / "ro-v1.yaml"
STORES_PATH = ROOT / "data" / "stores" / "ro.yaml"

# Matches solver/tests/test_ro_basket.py. The yaml records the fee as a
# percent with a 1.49 lei floor; the solver type takes one integer.
_EMAG_THRESHOLD = 10**9
_EMAG_FEE = 149
_EMAG_SHIPPING = 0
# Not a measured rate. A null yaml shipping fee means the cart did not
# print one. Zero would price an under-bar order as free. The locked
# Amazon order is over the threshold, so this stand-in is not charged.
_UNKNOWN_SHIPPING_CENTS = 10**9


class BasketError(ValueError):
    pass


def load_locked() -> tuple[str, str, list[Store], list[Item], list[dict]]:
    """Return day, currency, stores, items, and the raw offer rows.

    Offer rows keep the capture path and ISBN so the cache can be keyed
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
        by_id[row["id"]] = _store(row, currency)
    missing = allowed - set(by_id)
    if missing:
        raise BasketError("locked basket names unknown stores: " + ", ".join(sorted(missing)))
    stores = [by_id[store_id] for store_id in basket["solved_store_ids"]]
    items: list[Item] = []
    pages: list[dict] = []
    for book in basket["books"]:
        offers = []
        isbn = book.get("isbn13") or ""
        for offer in book["offers"]:
            offers.append(
                Offer(
                    store_id=offer["store_id"],
                    price_cents=int(offer["price_cents"]),
                    seller_certainty=offer["seller_certainty"],
                )
            )
            pages.append(
                {
                    "item_id": book["id"],
                    "title": book["title"],
                    "store_id": offer["store_id"],
                    "isbn13": isbn,
                    "day": day,
                    "capture": offer["capture"],
                    "price_cents": int(offer["price_cents"]),
                    "seller_certainty": offer["seller_certainty"],
                    "currency": currency,
                }
            )
        items.append(Item(id=book["id"], offers=tuple(offers)))
    return day, currency, stores, items, pages


def _store(row: dict, basket_currency: str) -> Store:
    store_id = row["id"]
    currency = row.get("currency") or ""
    if currency != basket_currency:
        # Leave the mismatch for the solver. Do not convert.
        pass
    if store_id == "emag":
        fee = row.get("per_order_fee_min_cents")
        return Store(
            id=store_id,
            currency=currency,
            free_shipping_threshold_cents=_EMAG_THRESHOLD if row.get("free_shipping_threshold_cents") is None else int(row["free_shipping_threshold_cents"]),
            shipping_fee_cents=_EMAG_SHIPPING if row.get("shipping_fee_cents") is None else int(row["shipping_fee_cents"]),
            per_order_fee_cents=_EMAG_FEE if fee is None else int(fee),
            membership=None,
        )
    shipping = row.get("shipping_fee_cents")
    per_order = row.get("per_order_fee_cents")
    if per_order is None:
        raise BasketError(f"{store_id} per-order fee is unknown")
    known = shipping is not None
    if shipping is None:
        shipping = _UNKNOWN_SHIPPING_CENTS
    return Store(
        id=store_id,
        currency=currency,
        free_shipping_threshold_cents=int(row["free_shipping_threshold_cents"]),
        shipping_fee_cents=int(shipping),
        per_order_fee_cents=int(per_order),
        membership=None,
        shipping_fee_known=known,
    )

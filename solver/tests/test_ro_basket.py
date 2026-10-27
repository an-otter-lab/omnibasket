"""Lock for the Romanian v1 basket after the 28 Oct point-3 reshape.

Prices, store thresholds and fees are read from data/baskets/ro-v1.yaml
and data/stores/ro.yaml. The Amazon.de under-bar charge is the published
4.99 EUR delivery component (2670 cents in the store file), a floor.
The winning assignment is over the bar, so its shipping is zero.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from solver import Item, Offer, Store, solve

ROOT = Path(__file__).resolve().parents[2]
BASKET_PATH = ROOT / "data" / "baskets" / "ro-v1.yaml"
STORES_PATH = ROOT / "data" / "stores" / "ro.yaml"

# eMAG's yaml fee is a percent with a 1.49 lei floor. The solver takes one integer.
_EMAG_THRESHOLD = 10**9
_EMAG_SHIPPING = 0


def _load() -> tuple[list[Store], list[Item]]:
    basket = yaml.safe_load(BASKET_PATH.read_text())
    rules = yaml.safe_load(STORES_PATH.read_text())
    by_id = {row["id"]: row for row in rules["stores"]}
    stores = []
    for store_id in basket["solved_store_ids"]:
        row = by_id[store_id]
        if store_id == "emag":
            stores.append(
                Store(
                    id=store_id,
                    currency=row["currency"],
                    free_shipping_threshold_cents=_EMAG_THRESHOLD,
                    shipping_fee_cents=_EMAG_SHIPPING,
                    per_order_fee_cents=int(row["per_order_fee_min_cents"]),
                )
            )
            continue
        stores.append(
            Store(
                id=store_id,
                currency=row["currency"],
                free_shipping_threshold_cents=int(row["free_shipping_threshold_cents"]),
                shipping_fee_cents=int(row["shipping_fee_cents"]),
                per_order_fee_cents=int(row["per_order_fee_cents"]),
            )
        )
    items = []
    for book in basket["books"]:
        items.append(
            Item(
                id=book["id"],
                offers=tuple(
                    Offer(
                        store_id=offer["store_id"],
                        price_cents=int(offer["price_cents"]),
                        seller_certainty=offer["seller_certainty"],
                    )
                    for offer in book["offers"]
                ),
            )
        )
    return stores, items


def _offer(items: list[Item], item_id: str, store_id: str) -> int:
    item = next(row for row in items if row.id == item_id)
    return next(offer.price_cents for offer in item.offers if offer.store_id == store_id)


def _store(stores: list[Store], store_id: str) -> Store:
    return next(row for row in stores if row.id == store_id)


def _cheapest_per_item_cents(stores: list[Store], items: list[Item]) -> int:
    """Each item at its cheapest shop, then that shop's measured fees."""

    by_store: dict[str, int] = {}
    store_by_id = {store.id: store for store in stores}
    for item in items:
        offer = min(item.offers, key=lambda row: (row.price_cents, row.store_id))
        by_store[offer.store_id] = by_store.get(offer.store_id, 0) + offer.price_cents
    total = 0
    for store_id, goods in by_store.items():
        store = store_by_id[store_id]
        shipping = 0 if goods >= store.free_shipping_threshold_cents else store.shipping_fee_cents
        total += goods + shipping + store.per_order_fee_cents
    return total


class RoV1BasketLock(unittest.TestCase):
    def test_yaml_carries_the_measured_cents(self) -> None:
        basket = yaml.safe_load(BASKET_PATH.read_text())
        rules = yaml.safe_load(STORES_PATH.read_text())
        prices = {
            (book["id"], offer["store_id"]): offer["price_cents"]
            for book in basket["books"]
            for offer in book["offers"]
        }
        self.assertEqual(prices[("mole", "amazon_de")], 11653)
        self.assertEqual(prices[("wild", "amazon_de")], 3986)
        self.assertEqual(prices[("matilda", "amazon_de")], 9433)
        self.assertEqual(prices[("charlie", "amazon_de")], 9433)
        self.assertEqual(prices[("mole", "libris")], 14256)
        self.assertEqual(prices[("wild", "libris")], 7770)
        self.assertEqual(prices[("matilda", "libris")], 8418)
        isbns = {book["id"]: book["isbn13"] for book in basket["books"]}
        self.assertEqual(isbns["mole"], "9781529105100")
        self.assertEqual(isbns["wild"], "9780064431781")
        self.assertEqual(isbns["matilda"], "9780141369365")
        self.assertEqual(isbns["charlie"], "9780141369372")
        amazon = next(row for row in rules["stores"] if row["id"] == "amazon_de")
        self.assertEqual(amazon["free_shipping_threshold_cents"], 26217)
        self.assertEqual(amazon["shipping_fee_cents"], 2670)
        self.assertIs(amazon["shipping_fee_is_floor"], True)

    def test_point_3_consolidation_beats_cheapest_per_item(self) -> None:
        stores, items = _load()
        result = solve(stores, items)

        amazon_goods = sum(
            _offer(items, item_id, "amazon_de")
            for item_id in ("mole", "wild", "matilda", "charlie")
        )
        amazon = _store(stores, "amazon_de")
        self.assertEqual(amazon_goods, 34505)
        self.assertGreaterEqual(amazon_goods, amazon.free_shipping_threshold_cents)

        self.assertEqual(len(items), 7)
        for item in items:
            self.assertGreaterEqual(len(item.offers), 2)

        self.assertLess(_offer(items, "ghici", "bookzone"), _offer(items, "ghici", "emag"))
        self.assertLess(_offer(items, "ghici", "bookzone"), _offer(items, "ghici", "libris"))
        self.assertLess(_offer(items, "vhc", "emag"), _offer(items, "vhc", "libris"))
        self.assertLess(_offer(items, "owl", "libris"), _offer(items, "owl", "emag"))
        self.assertLess(_offer(items, "mole", "amazon_de"), _offer(items, "mole", "libris"))
        self.assertLess(_offer(items, "wild", "amazon_de"), _offer(items, "wild", "libris"))
        self.assertLess(_offer(items, "matilda", "libris"), _offer(items, "matilda", "amazon_de"))

        self.assertEqual(result.total_cents, 51516)
        self.assertEqual(
            [(row.item_id, row.store_id, row.price_cents) for row in result.split],
            [
                ("ghici", "libris", _offer(items, "ghici", "libris")),
                ("vhc", "libris", _offer(items, "vhc", "libris")),
                ("owl", "libris", _offer(items, "owl", "libris")),
                ("mole", "amazon_de", _offer(items, "mole", "amazon_de")),
                ("wild", "amazon_de", _offer(items, "wild", "amazon_de")),
                ("matilda", "amazon_de", _offer(items, "matilda", "amazon_de")),
                ("charlie", "amazon_de", _offer(items, "charlie", "amazon_de")),
            ],
        )
        by_store = {row.store_id: row for row in result.stores}
        self.assertEqual(by_store["amazon_de"].qualifying_cents, 34505)
        self.assertTrue(by_store["amazon_de"].threshold_crossed)
        self.assertEqual(by_store["amazon_de"].shipping_cents, 0)
        self.assertEqual(by_store["libris"].qualifying_cents, 17011)
        self.assertTrue(by_store["libris"].threshold_crossed)
        self.assertEqual(by_store["libris"].shipping_cents, 0)

        cheapest = _cheapest_per_item_cents(stores, items)
        self.assertEqual(cheapest, 51764)
        self.assertLess(result.total_cents, cheapest)
        margin_cents = cheapest - result.total_cents
        self.assertEqual(margin_cents, 248)
        self.assertEqual(result.currency, "RON")
        self.assertEqual(result.membership, ())
        self.assertTrue(all(row.store_id != "emag" for row in result.split))


if __name__ == "__main__":
    unittest.main()

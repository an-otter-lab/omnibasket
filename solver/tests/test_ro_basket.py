"""Lock for the Romanian v1 basket after the 28 Oct point-3 reshape.

Prices and store thresholds are read from data/baskets/ro-v1.yaml and
data/stores/ro.yaml. Amazon.de's under-bar per-delivery and per-kg
amounts are null: the Romania cart did not print them. The winning
assignment is over the bar, so its shipping is zero. eMAG stays out
while its three solver fees are null. Bookzone under 200 lei is the
cart floor of 10.90 lei delivery plus 1.99 lei processing.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from solver import Item, Offer, Store, solve

ROOT = Path(__file__).resolve().parents[2]
BASKET_PATH = ROOT / "data" / "baskets" / "ro-v1.yaml"
STORES_PATH = ROOT / "data" / "stores" / "ro.yaml"

def _load() -> tuple[list[Store], list[Item]]:
    basket = yaml.safe_load(BASKET_PATH.read_text())
    rules = yaml.safe_load(STORES_PATH.read_text())
    by_id = {row["id"]: row for row in rules["stores"]}
    stores = []
    for store_id in basket["solved_store_ids"]:
        row = by_id[store_id]
        # Do not fill a null threshold or per-order fee from a percent or a minimum.
        if row.get("free_shipping_threshold_cents") is None or row.get("per_order_fee_cents") is None:
            continue
        shipping = row.get("shipping_fee_cents")
        stores.append(
            Store(
                id=store_id,
                currency=row["currency"],
                free_shipping_threshold_cents=int(row["free_shipping_threshold_cents"]),
                shipping_fee_cents=0 if shipping is None else int(shipping),
                per_order_fee_cents=int(row["per_order_fee_cents"]),
                shipping_fee_known=shipping is not None,
            )
        )
    allowed = {store.id for store in stores}
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
                    if offer["store_id"] in allowed
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
        bookzone = next(row for row in rules["stores"] if row["id"] == "bookzone")
        emag = next(row for row in rules["stores"] if row["id"] == "emag")
        self.assertEqual(amazon["free_shipping_threshold_cents"], 26219)
        self.assertIsNone(amazon["shipping_fee_cents"])
        self.assertIsNone(amazon["per_kg_fee_cents"])
        self.assertEqual(bookzone["shipping_fee_cents"], 1090)
        self.assertEqual(bookzone["per_order_fee_cents"], 199)
        self.assertIs(bookzone["shipping_fee_is_floor"], True)
        self.assertIsNone(emag["free_shipping_threshold_cents"])
        self.assertIsNone(emag["shipping_fee_cents"])
        self.assertIsNone(emag["per_order_fee_cents"])

    def test_point_3_consolidation_beats_cheapest_per_item(self) -> None:
        stores, items = _load()
        basket = yaml.safe_load(BASKET_PATH.read_text())
        prices = {
            (book["id"], offer["store_id"]): offer["price_cents"]
            for book in basket["books"]
            for offer in book["offers"]
        }
        result = solve(stores, items)

        amazon_goods = sum(
            _offer(items, item_id, "amazon_de")
            for item_id in ("mole", "wild", "matilda", "charlie")
        )
        amazon = _store(stores, "amazon_de")
        self.assertEqual(amazon_goods, 34505)
        self.assertGreaterEqual(amazon_goods, amazon.free_shipping_threshold_cents)

        self.assertEqual(len(items), 7)
        # Point 1 is on measured prices. eMAG prices stay in the basket file
        # even though its null fees keep it out of solve().
        offers_in_file = {book["id"]: book["offers"] for book in basket["books"]}
        for item in items:
            self.assertGreaterEqual(len(offers_in_file[item.id]), 2)
            self.assertGreaterEqual(len(item.offers), 1)

        self.assertLess(prices[("ghici", "bookzone")], prices[("ghici", "emag")])
        self.assertLess(prices[("ghici", "bookzone")], prices[("ghici", "libris")])
        self.assertLess(prices[("vhc", "emag")], prices[("vhc", "libris")])
        self.assertLess(prices[("owl", "libris")], prices[("owl", "emag")])
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

        self.assertEqual(result.currency, "RON")
        self.assertEqual(result.membership, ())
        self.assertTrue(all(row.store_id != "emag" for row in result.split))


if __name__ == "__main__":
    unittest.main()

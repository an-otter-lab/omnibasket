"""Lock for the Romanian v1 basket after the 28 Oct point-3 reshape.

The four Amazon.de titles are The Boy, the Mole, the Fox and the Horse
(9781529105100, 116.53 lei), Where the Wild Things Are (9780064431781,
39.86), Matilda colour edition (9780141369365, 94.33) and Charlie and the
Chocolate Factory colour edition (9780141369372, 94.33). Amazon dispatches
each one. The same ISBN is on Libris. Their Amazon prices sum to 345.05 lei,
over the 262.17 lei bar.

Amazon.de's under-bar charge is passed as 26.70 lei. That is only the
published 4.99 EUR delivery component, converted at the 49.00 EUR = 262.17 RON
rate printed on the buy box. The 1.99 EUR/kg term is not included because no
page states a weight. 26.70 lei is a floor. The winning assignment is over
the bar, so its shipping is zero and the missing per-kg term is not in the
total. The same winner is selected for any under-bar fee at or above that floor.
"""

from __future__ import annotations

import unittest

from solver import Item, Offer, Store, solve


AMAZON = {
    "mole": 11653,
    "wild": 3986,
    "matilda": 9433,
    "charlie": 9433,
}
AMAZON_THRESHOLD = 26217
AMAZON_FEE_FLOOR = 2670


def _stores() -> list[Store]:
    return [
        Store(
            id="libris",
            currency="RON",
            free_shipping_threshold_cents=13500,
            shipping_fee_cents=1290,
            per_order_fee_cents=0,
        ),
        Store(
            id="emag",
            currency="RON",
            free_shipping_threshold_cents=10**9,
            shipping_fee_cents=0,
            per_order_fee_cents=149,
        ),
        Store(
            id="bookzone",
            currency="RON",
            free_shipping_threshold_cents=20000,
            shipping_fee_cents=690,
            per_order_fee_cents=199,
        ),
        Store(
            id="amazon_de",
            currency="RON",
            free_shipping_threshold_cents=AMAZON_THRESHOLD,
            shipping_fee_cents=AMAZON_FEE_FLOOR,
            per_order_fee_cents=0,
        ),
    ]


def _items() -> list[Item]:
    return [
        Item(
            id="ghici",
            offers=(
                Offer("libris", 5700, "direct"),
                Offer("emag", 5600, "marketplace"),
                Offer("bookzone", 4650, "direct"),
            ),
        ),
        Item(
            id="vhc",
            offers=(
                Offer("libris", 6133, "direct"),
                Offer("emag", 5753, "marketplace"),
            ),
        ),
        Item(
            id="owl",
            offers=(
                Offer("libris", 5178, "direct"),
                Offer("emag", 15700, "marketplace"),
            ),
        ),
        Item(
            id="mole",
            offers=(
                Offer("amazon_de", 11653, "direct"),
                Offer("libris", 14256, "direct"),
            ),
        ),
        Item(
            id="wild",
            offers=(
                Offer("amazon_de", 3986, "direct"),
                Offer("libris", 7770, "direct"),
            ),
        ),
        Item(
            id="matilda",
            offers=(
                Offer("amazon_de", 9433, "direct"),
                Offer("libris", 8418, "direct"),
            ),
        ),
        Item(
            id="charlie",
            offers=(
                Offer("amazon_de", 9433, "direct"),
                Offer("libris", 8418, "direct"),
            ),
        ),
    ]


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
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        basket = (root / "data" / "baskets" / "ro-v1.yaml").read_text()
        rules = (root / "data" / "stores" / "ro.yaml").read_text()
        for snippet in (
            "price_cents: 11653",
            "price_cents: 3986",
            "price_cents: 9433",
            "price_cents: 14256",
            "price_cents: 7770",
            "price_cents: 8418",
            'isbn13: "9781529105100"',
            'isbn13: "9780064431781"',
            'isbn13: "9780141369365"',
            'isbn13: "9780141369372"',
        ):
            self.assertIn(snippet, basket)
        self.assertIn("free_shipping_threshold_cents: 26217", rules)
        self.assertIn("shipping_fee_cents: 2670", rules)
        self.assertIn("shipping_fee_is_floor: true", rules)

    def test_point_3_consolidation_beats_cheapest_per_item(self) -> None:
        stores = _stores()
        items = _items()
        result = solve(stores, items)

        amazon_goods = sum(AMAZON.values())
        self.assertEqual(amazon_goods, 34505)
        self.assertGreaterEqual(amazon_goods, AMAZON_THRESHOLD)

        # Point 1. Seven titles, each in at least two stores.
        self.assertEqual(len(items), 7)
        for item in items:
            self.assertGreaterEqual(len(item.offers), 2)

        # Point 2, on the item price, not on who wins the assignment.
        # Bookzone is cheapest on Ghici. eMAG is cheapest on the caterpillar.
        # Libris is cheapest on Owl Babies. Amazon.de is cheapest on the
        # mole hardback and on Where the Wild Things Are.
        self.assertLess(4650, 5600)
        self.assertLess(4650, 5700)
        self.assertLess(5753, 6133)
        self.assertLess(5178, 15700)
        self.assertLess(11653, 14256)
        self.assertLess(3986, 7770)
        self.assertLess(8418, 9433)

        # Winning assignment. All four Amazon.de titles in one order, over
        # the bar, so delivery is zero. Ghici, the caterpillar and Owl Babies
        # stay at Libris and clear 135 lei.
        self.assertEqual(result.total_cents, 51516)
        self.assertEqual(
            [(row.item_id, row.store_id, row.price_cents) for row in result.split],
            [
                ("ghici", "libris", 5700),
                ("vhc", "libris", 6133),
                ("owl", "libris", 5178),
                ("mole", "amazon_de", 11653),
                ("wild", "amazon_de", 3986),
                ("matilda", "amazon_de", 9433),
                ("charlie", "amazon_de", 9433),
            ],
        )
        by_store = {row.store_id: row for row in result.stores}
        self.assertEqual(by_store["amazon_de"].qualifying_cents, 34505)
        self.assertTrue(by_store["amazon_de"].threshold_crossed)
        self.assertEqual(by_store["amazon_de"].shipping_cents, 0)
        self.assertEqual(by_store["libris"].qualifying_cents, 17011)
        self.assertTrue(by_store["libris"].threshold_crossed)
        self.assertEqual(by_store["libris"].shipping_cents, 0)

        # Point 3. Cheapest-per-item keeps Matilda and Charlie at Libris
        # (84.18 vs 94.33) and leaves Amazon at 156.39 lei, under the bar,
        # so the 26.70 lei floor is charged. That total is 517.64 lei.
        # Consolidation pays the 10.15 lei premium on each colour edition,
        # drops the Amazon fee to zero, and moves Ghici and the caterpillar
        # onto Libris so that order still clears 135 lei. 515.16 < 517.64.
        cheapest = _cheapest_per_item_cents(stores, items)
        self.assertEqual(cheapest, 51764)
        self.assertLess(result.total_cents, cheapest)
        self.assertEqual(result.currency, "RON")
        self.assertEqual(result.membership, ())

        # Point 4 stays out of scope. No solved line is an eMAG-sold offer.
        self.assertTrue(all(row.store_id != "emag" for row in result.split))


if __name__ == "__main__":
    unittest.main()

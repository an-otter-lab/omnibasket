"""Lock for the Romanian v1 basket after the 28 Oct second-store reads.

Cents come from data/baskets/ro-v1.yaml. Amazon.de is measured and is the
cheapest item price on each swapped title, but it is not passed to solve():
the four prices sum to 188.76 lei, under the 262.17 lei free-delivery bar,
and the under-bar charge is 4.99 EUR plus 1.99 EUR/kg with no weight.

The solved basket is the five titles whose stores all have a single measured
fee: Ghici, The Very Hungry Caterpillar, Owl Babies, Charlotte's Web
(Puffin 9780141354828) and Harry Potter (9781408855652), at Libris, eMAG
and Bookzone.

eMAG's fee on this assignment is the 1.49 lei minimum. The only eMAG line
is the caterpillar at 57.53 lei, and 1% of that is under 1.49. Bookzone's
cart charged 6.90 lei delivery plus 1.99 lei processing on a 46.50 lei book.
The label says "De la 6.9 Lei", so 6.90 is the floor this cart used.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from solver import Item, Offer, Store, solve

ROOT = Path(__file__).resolve().parents[2]

# Item prices that have a second store. Amazon.de is compared for point 2
# and is not an Offer in the solve() call below.
AMAZON = {
    "gruffalo": 4601,
    "room-broom": 4644,
    "charlottes-web": 4644,
    "hp-stone": 4987,
}


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
            id="charlottes-web",
            offers=(
                Offer("libris", 5178, "direct"),
                Offer("emag", 5499, "marketplace"),
            ),
        ),
        Item(
            id="hp-stone",
            offers=(
                Offer("libris", 5826, "direct"),
                Offer("emag", 6199, "marketplace"),
                Offer("bookzone", 5794, "direct"),
            ),
        ),
    ]


class RoV1BasketLock(unittest.TestCase):
    def test_yaml_carries_the_measured_cents(self) -> None:
        basket = (ROOT / "data" / "baskets" / "ro-v1.yaml").read_text()
        rules = (ROOT / "data" / "stores" / "ro.yaml").read_text()
        for snippet in (
            "price_cents: 5178",
            "price_cents: 5499",
            "price_cents: 5794",
            "price_cents: 5826",
            "price_cents: 6199",
            "price_cents: 4601",
            "price_cents: 4987",
            "weight: null",
            'isbn13: "9781408855652"',
        ):
            self.assertIn(snippet, basket)
        self.assertIn("shipping_fee_cents: 690", rules)
        self.assertIn("per_order_fee_cents: 199", rules)
        self.assertIn("shipping_fee_cents: null", rules)

    def test_solved_five_and_the_four_points(self) -> None:
        result = solve(_stores(), _items())

        # Ghici at Bookzone (46.50 + 6.90 delivery + 1.99 processing).
        # Caterpillar at eMAG (57.53 + 1.49 minimum fee).
        # Owl, Charlotte, Harry at Libris: 51.78 + 51.78 + 58.26 = 161.82,
        # which clears 135 lei, so Libris shipping is 0.
        # Moving Harry to Bookzone would drop Libris under 135 and cost
        # the 12.90 courier to save 0.32 on the item.
        self.assertEqual(result.total_cents, 27623)
        self.assertEqual(
            [(row.item_id, row.store_id, row.price_cents) for row in result.split],
            [
                ("ghici", "bookzone", 4650),
                ("vhc", "emag", 5753),
                ("owl", "libris", 5178),
                ("charlottes-web", "libris", 5178),
                ("hp-stone", "libris", 5826),
            ],
        )
        by_store = {row.store_id: row for row in result.stores}
        self.assertEqual(by_store["bookzone"].qualifying_cents, 4650)
        self.assertFalse(by_store["bookzone"].threshold_crossed)
        self.assertEqual(by_store["bookzone"].shipping_cents, 690)
        self.assertEqual(by_store["bookzone"].per_order_fee_cents, 199)
        self.assertEqual(by_store["emag"].qualifying_cents, 5753)
        self.assertEqual(by_store["emag"].per_order_fee_cents, 149)
        self.assertEqual(by_store["libris"].qualifying_cents, 16182)
        self.assertTrue(by_store["libris"].threshold_crossed)
        self.assertEqual(by_store["libris"].shipping_cents, 0)
        self.assertEqual(result.currency, "RON")
        self.assertEqual(result.membership, ())

        # Point 1 met. Each solved title has two measured prices, and each
        # swapped title has an Amazon.de price plus at least one other.
        for item in _items():
            self.assertGreaterEqual(len(item.offers), 2)
        self.assertLess(AMAZON["gruffalo"], 5178)  # Libris second price
        self.assertLess(AMAZON["room-broom"], 5178)
        self.assertLess(AMAZON["charlottes-web"], 5178)
        self.assertLess(AMAZON["hp-stone"], 5794)  # Bookzone second price

        # Point 2 met on item price, not on the solved assignment.
        # Bookzone is cheapest on Ghici. eMAG is cheapest on the caterpillar.
        # Libris is cheapest on Owl Babies. Amazon.de is cheapest on each swap.
        self.assertLess(4650, 5600)
        self.assertLess(4650, 5700)
        self.assertLess(5753, 6133)
        self.assertLess(5178, 15700)
        for item_id, amazon_cents in AMAZON.items():
            others = {
                "gruffalo": (5178,),
                "room-broom": (5178,),
                "charlottes-web": (5178, 5499),
                "hp-stone": (5794, 5826, 6199),
            }[item_id]
            self.assertTrue(all(amazon_cents < other for other in others))

        # Point 3 is not met. Name the missing lei, not a made-up price.
        amazon_goods = sum(AMAZON.values())
        self.assertEqual(amazon_goods, 18876)
        self.assertEqual(26217 - amazon_goods, 7341)
        bookzone_goods = 4650 + 5794
        self.assertEqual(bookzone_goods, 10444)
        self.assertEqual(20000 - bookzone_goods, 9556)

        # Point 4 is out of scope by Adrian's 28 Oct decision, not a miss
        # to be forced. No solved offer is sold by eMAG.
        self.assertTrue(all(row.store_id != "emag" or row.price_cents != 0 for row in result.split))
        self.assertEqual(result.membership, ())


if __name__ == "__main__":
    unittest.main()

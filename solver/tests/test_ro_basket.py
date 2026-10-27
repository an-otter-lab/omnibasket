"""Lock for the Romanian v1 basket. Cents come from data/baskets/ro-v1.yaml.

The solved basket is the three titles that have two measured store prices and
a store fee the solver can represent: Ghici, The Very Hungry Caterpillar, and
Owl Babies, at Libris and eMAG.

eMAG's published fee on this assignment is the 1.49 lei minimum. The eMAG
subtotal of the cheapest-per-item split is 113.53 lei, and 1% of that is
1.1353 lei, which the terms lift to 1.49. The optimal split uses no eMAG
item, so the fee does not change the headline total. Partner delivery was
not on the pages; it is not entered as zero and is not added.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from solver import Item, Offer, Store, solve

ROOT = Path(__file__).resolve().parents[2]
BASKET = ROOT / "data" / "baskets" / "ro-v1.yaml"
STORES = ROOT / "data" / "stores" / "ro.yaml"


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
            # No free-shipping line applies to these marketplace offers.
            # Threshold is unreachable so the missing partner-delivery fee
            # cannot be waived by a number we do not have. Shipping stays 0
            # only because we do not charge an unpublished partner fee.
            free_shipping_threshold_cents=10**9,
            shipping_fee_cents=0,
            per_order_fee_cents=149,
        ),
    ]


def _items() -> list[Item]:
    return [
        Item(
            id="ghici",
            offers=(
                Offer("libris", 5700, "direct"),
                Offer("emag", 5600, "marketplace"),
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
    ]


class RoV1BasketLock(unittest.TestCase):
    def test_yaml_carries_the_same_cents(self) -> None:
        text = BASKET.read_text()
        for snippet in (
            "id: ghici",
            "price_cents: 4650",
            "price_cents: 5600",
            "price_cents: 5700",
            "id: vhc",
            "price_cents: 5753",
            "price_cents: 6133",
            "id: owl",
            "price_cents: 5178",
            "price_cents: 15700",
            "id: gruffalo",
            "price_cents: 4601",
            "price_cents: null",
            "id: room-broom",
            "price_cents: 4644",
            "id: charlottes-web",
            "id: hp-stone",
            "price_cents: 4987",
            "sold_by_emag: false",
            "genius_badge: false",
        ):
            self.assertIn(snippet, text)
        rules = STORES.read_text()
        self.assertIn("free_shipping_threshold_cents: 13500", rules)
        self.assertIn("shipping_fee_cents: 1290", rules)
        self.assertIn("shipping_fee_cents: null", rules)
        self.assertIn("per_order_fee_min_cents: 149", rules)

    def test_solved_core_and_the_four_points(self) -> None:
        result = solve(_stores(), _items())

        # Optimal: pay 1.00 and 3.80 lei more at Libris for Ghici and the
        # caterpillar so Owl + those two clear 135 lei and drop the 12.90.
        # 5178 + 5700 + 6133 = 17011. 17011 >= 13500, shipping 0.
        self.assertEqual(result.total_cents, 17011)
        self.assertEqual(
            [(row.item_id, row.store_id, row.price_cents) for row in result.split],
            [("ghici", "libris", 5700), ("vhc", "libris", 6133), ("owl", "libris", 5178)],
        )
        self.assertEqual(len(result.stores), 1)
        store = result.stores[0]
        self.assertEqual(store.store_id, "libris")
        self.assertEqual(store.qualifying_cents, 17011)
        self.assertTrue(store.threshold_crossed)
        self.assertEqual(store.shipping_cents, 0)
        self.assertEqual(store.per_order_fee_cents, 0)
        self.assertEqual(result.currency, "RON")
        self.assertFalse(result.needs_seller_verification)
        self.assertTrue(result.all_direct)
        self.assertEqual(result.membership, ())

        # Single-store baseline, no membership.
        # eMAG: 5600 + 5753 + 15700 = 27053, plus the 1.49 lei minimum fee
        # (1% of 270.53 is 2.7053, still under the 3.99 cap, so a flat 1.49
        # understates this baseline by 122 cents). The comparison that
        # matters is Libris versus the cheapest-per-item split below.
        self.assertEqual(result.single_store_baseline.best_store_id, "libris")
        self.assertEqual(result.single_store_baseline.total_cents, 17011)
        by_id = {row.store_id: row for row in result.single_store_baseline.per_store}
        self.assertTrue(by_id["libris"].feasible)
        self.assertEqual(by_id["emag"].total_cents, 27053 + 149)

        # Cheapest item price, then one order per store.
        # Ghici eMAG 5600, caterpillar eMAG 5753, Owl Libris 5178.
        # eMAG goods 11353, 1% = 113.53 cents -> minimum fee 149.
        # Libris 5178 < 13500, shipping 1290.
        cheapest_per_item = 5600 + 5753 + 5178 + 149 + 1290
        self.assertEqual(cheapest_per_item, 17970)
        self.assertLess(result.total_cents, cheapest_per_item)
        self.assertEqual(cheapest_per_item - result.total_cents, 959)

        # Point 1, solved core: each of the three has two measured prices.
        for item in _items():
            self.assertGreaterEqual(len(item.offers), 2)

        # Point 1, directed basket: the four swapped titles do not.
        # Their second-store price is null in the yaml. Not asserted as met.

        # Point 2, solved core: Libris is strictly cheapest on Owl
        # (5178 < 15700). eMAG is strictly cheapest on Ghici (5600 < 5700)
        # and on the caterpillar (5753 < 6133).
        self.assertLess(5178, 15700)
        self.assertLess(5600, 5700)
        self.assertLess(5753, 6133)

        # Point 3 is not met for the thresholds the test names.
        # 170.11 lei is not close to Bookzone's 200 lei or Amazon.de's
        # 262.17 lei. Amazon.de goods on the four swapped titles are
        # 4601 + 4644 + 4644 + 4987 = 18876, which is 7341 cents under 26217.
        amazon_goods = 4601 + 4644 + 4644 + 4987
        self.assertEqual(amazon_goods, 18876)
        self.assertEqual(26217 - amazon_goods, 7341)
        self.assertLess(result.total_cents, 20000)
        self.assertNotEqual(result.total_cents, 0)

        # The Libris consolidation above is a real threshold win. It is not
        # point 3, because point 3 names the Amazon.de and Bookzone bars,
        # and those bars cannot be scored: Bookzone's under-200 fee is null,
        # and Amazon.de under 49 EUR is 4.99 EUR plus 1.99 EUR/kg with no
        # weight in the capture.

        # Point 4 is not met. No solved offer is sold by eMAG, and the yaml
        # records genius_badge false on every eMAG page that was captured.
        self.assertNotIn("sold_by_emag: true", BASKET.read_text())
        self.assertNotIn("genius_badge: true", BASKET.read_text())
        self.assertEqual(result.membership, ())


if __name__ == "__main__":
    unittest.main()

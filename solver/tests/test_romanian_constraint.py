"""Forced Romanian-store constraint: feasible, infeasible, and null fees.

Romanian here means eMAG or Bookzone. Amounts are integer cents.
"""

from __future__ import annotations

import unittest

from solver import Item, Offer, SolverError, Store, solve
from solver.optimize import ROMANIAN_STORE_IDS, store_if_fees_resolved, unresolved_fee_fields


def _store(store_id: str, *, threshold: int = 0, shipping: int = 0, fee: int = 0) -> Store:
    return Store(
        id=store_id,
        currency="RON",
        free_shipping_threshold_cents=threshold,
        shipping_fee_cents=shipping,
        per_order_fee_cents=fee,
    )


def _item(item_id: str, *offers: tuple[str, int]) -> Item:
    return Item(
        id=item_id,
        offers=tuple(
            Offer(store_id=store_id, price_cents=price, seller_certainty="direct")
            for store_id, price in offers
        ),
    )


class ForcedRomanianStore(unittest.TestCase):
    def test_feasible_split_names_the_romanian_store_and_keeps_its_own_total(self) -> None:
        # Foreign-only is 1000. Forcing Bookzone adds that 1500 line plus its 100 fee.
        # 1000 + 1500 + 100 = 2600. eMAG at 4000 is worse, so the named store is bookzone.
        stores = [
            _store("amazon_de"),
            _store("bookzone", fee=100),
            _store("emag", fee=149),
        ]
        items = [
            _item("foreign", ("amazon_de", 1000), ("bookzone", 5000)),
            _item("local", ("bookzone", 1500), ("emag", 4000)),
        ]
        optimum = solve(stores, items)
        forced = solve(stores, items, require_any_store=ROMANIAN_STORE_IDS)

        self.assertEqual(optimum.total_cents, 1000 + 1500 + 100)
        # Optimum already uses Bookzone for the local line, so the two answers match.
        # A second basket where the optimum avoids both Romanian shops:
        stores = [
            _store("amazon_de"),
            _store("libris"),
            _store("bookzone", fee=199),
            _store("emag", fee=149),
        ]
        items = [
            _item("one", ("amazon_de", 1000), ("libris", 1100), ("bookzone", 3000), ("emag", 2800)),
            _item("two", ("libris", 2000), ("amazon_de", 2500), ("bookzone", 4000)),
        ]
        optimum = solve(stores, items)
        forced = solve(stores, items, require_any_store=ROMANIAN_STORE_IDS)
        self.assertEqual(optimum.total_cents, 1000 + 2000)
        self.assertTrue(all(row.store_id not in ROMANIAN_STORE_IDS for row in optimum.split))
        used = {row.store_id for row in forced.split}
        self.assertTrue(used & ROMANIAN_STORE_IDS)
        # Cheapest forced split puts "one" at eMAG (2800+149) and "two" at Libris (2000).
        self.assertEqual(forced.total_cents, 2800 + 149 + 2000)
        self.assertEqual(
            [(row.item_id, row.store_id) for row in forced.split],
            [("one", "emag"), ("two", "libris")],
        )
        self.assertIn("emag", used)

    def test_infeasible_when_no_romanian_offer_exists(self) -> None:
        stores = [_store("amazon_de"), _store("libris")]
        items = [_item("one", ("amazon_de", 1000), ("libris", 900))]
        with self.assertRaises(SolverError) as caught:
            solve(stores, items, require_any_store=ROMANIAN_STORE_IDS)
        self.assertIn("bookzone", str(caught.exception))
        self.assertIn("emag", str(caught.exception))

    def test_unresolved_fee_stays_null_and_the_store_is_not_built(self) -> None:
        row = {
            "id": "emag",
            "currency": "RON",
            "free_shipping_threshold_cents": None,
            "shipping_fee_cents": None,
            "per_order_fee_cents": None,
            "per_order_fee_min_cents": 149,
            "per_order_fee_percent": 1,
        }
        self.assertIsNone(store_if_fees_resolved(row))
        fields = unresolved_fee_fields(row)
        self.assertEqual(fields["free_shipping_threshold_cents"], None)
        self.assertEqual(fields["shipping_fee_cents"], None)
        self.assertEqual(fields["per_order_fee_cents"], None)
        self.assertNotIn("per_order_fee_min_cents", fields)


if __name__ == "__main__":
    unittest.main()

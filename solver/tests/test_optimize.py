"""Exact-total fixtures for the basket solver.

Every asserted cent is derived in the test name's comment from the inputs,
not from a range.
"""

from __future__ import annotations

import unittest

from solver import Item, Membership, Offer, SolverError, Store, solve


def _store(
    store_id: str,
    *,
    threshold: int,
    shipping: int,
    fee: int = 0,
    membership: Membership | None = None,
    currency: str = "USD",
) -> Store:
    return Store(
        id=store_id,
        currency=currency,
        free_shipping_threshold_cents=threshold,
        shipping_fee_cents=shipping,
        per_order_fee_cents=fee,
        membership=membership,
    )


def _item(item_id: str, *offers: tuple[str, int, str]) -> Item:
    return Item(
        id=item_id,
        offers=tuple(
            Offer(store_id=store_id, price_cents=price, seller_certainty=certainty)  # type: ignore[arg-type]
            for store_id, price, certainty in offers
        ),
    )


class ThresholdCrossingWin(unittest.TestCase):
    """Paying 200 cents more for book1 at B crosses B's threshold and wins.

    Stores: A threshold 5000 ship 800; B threshold 3000 ship 1000. Fees 0.
    book1: A 2000 direct, B 2200 direct.
    book2: A 1500 direct, B 1200 direct.

    Greedy cheapest-each:
      book1 at A = 2000 + 800 shipping (2000 < 5000) = 2800
      book2 at B = 1200 + 1000 shipping (1200 < 3000) = 2200
      greedy total = 5000

    Both at B: items 2200 + 1200 = 3400 >= 3000, shipping 0, total 3400.
    Both at A: items 3500 < 5000, shipping 800, total 4300.
    """

    def test_more_expensive_item_wins_the_basket(self) -> None:
        result = solve(
            [
                _store("A", threshold=5000, shipping=800),
                _store("B", threshold=3000, shipping=1000),
            ],
            [
                _item("book1", ("A", 2000, "direct"), ("B", 2200, "direct")),
                _item("book2", ("A", 1500, "direct"), ("B", 1200, "direct")),
            ],
        )

        self.assertEqual(result.total_cents, 3400)
        self.assertEqual(
            [(row.item_id, row.store_id, row.price_cents) for row in result.split],
            [("book1", "B", 2200), ("book2", "B", 1200)],
        )
        self.assertGreater(2200, 2000)
        self.assertEqual(result.currency, "USD")
        self.assertFalse(result.needs_seller_verification)
        self.assertTrue(result.all_direct)
        self.assertEqual(len(result.stores), 1)
        store = result.stores[0]
        self.assertEqual(store.store_id, "B")
        self.assertTrue(store.threshold_crossed)
        self.assertEqual(store.qualifying_cents, 3400)
        self.assertEqual(store.shipping_cents, 0)
        self.assertEqual(store.per_order_fee_cents, 0)
        self.assertEqual(store.store_total_cents, 3400)
        self.assertIn("3400 cents >= threshold 3000 cents", store.threshold_reason)
        self.assertEqual(result.single_store_baseline.best_store_id, "B")
        self.assertEqual(result.single_store_baseline.total_cents, 3400)
        by_id = {row.store_id: row for row in result.single_store_baseline.per_store}
        self.assertEqual(by_id["A"].total_cents, 4300)
        self.assertEqual(by_id["B"].total_cents, 3400)


class PerOrderFeeLoss(unittest.TestCase):
    """A 100-cent cheaper line does not justify opening a second order.

    A fee 500, B fee 300, both shipping 0 (thresholds unreachable).
    big: A 2000, B 5000. tiny: A 1000, B 900.

    Split A+B = 2000 + 500 + 900 + 300 = 3700.
    Both at A = 2000 + 1000 + 500 = 3500.
    Both at B = 5000 + 900 + 300 = 6200.
    """

    def test_extra_order_loses(self) -> None:
        result = solve(
            [
                _store("A", threshold=100_000, shipping=0, fee=500),
                _store("B", threshold=100_000, shipping=0, fee=300),
            ],
            [
                _item("big", ("A", 2000, "direct"), ("B", 5000, "direct")),
                _item("tiny", ("A", 1000, "direct"), ("B", 900, "direct")),
            ],
        )

        self.assertEqual(result.total_cents, 3500)
        self.assertEqual({row.store_id for row in result.split}, {"A"})
        self.assertEqual(len(result.stores), 1)
        store = result.stores[0]
        self.assertEqual(store.per_order_fee_cents, 500)
        self.assertEqual(store.items_cents, 3000)
        self.assertEqual(store.store_total_cents, 3500)
        self.assertFalse(store.threshold_crossed)
        self.assertEqual(result.single_store_baseline.total_cents, 3500)


class SellerCertainty(unittest.TestCase):
    """Unknown never counts toward the threshold. Marketplace does, but is not direct.

    Store S threshold 2500, shipping 700, fee 0. One item priced 2500.
    Direct: qualifying 2500 >= 2500, total 2500.
    Marketplace: same money, all_direct false, total 2500.
    Unknown: qualifying 0, shipping 700, total 3200, verification required.

    Mixed basket, threshold 3000, shipping 500:
    direct 2000 + unknown 2000 -> qualifying 2000, shipping charged, total 4500.
    direct 1000 + marketplace 2000 -> qualifying 3000, shipping waived, total 3000.
    """

    def _one(self, certainty: str):
        return solve(
            [_store("S", threshold=2500, shipping=700)],
            [_item("book", ("S", 2500, certainty))],
        )

    def test_unknown_excludes_threshold_and_flags_verification(self) -> None:
        result = self._one("unknown")
        self.assertEqual(result.total_cents, 3200)
        self.assertTrue(result.needs_seller_verification)
        self.assertFalse(result.all_direct)
        self.assertEqual(result.split[0].seller_certainty, "unknown")
        store = result.stores[0]
        self.assertEqual(store.items_cents, 2500)
        self.assertEqual(store.qualifying_cents, 0)
        self.assertEqual(store.unknown_cents, 2500)
        self.assertFalse(store.threshold_crossed)
        self.assertEqual(store.shipping_cents, 700)
        self.assertIn("unknown 2500 cents excluded", store.threshold_reason)

    def test_marketplace_is_payable_and_not_direct(self) -> None:
        direct = self._one("direct")
        market = self._one("marketplace")
        self.assertEqual(direct.total_cents, 2500)
        self.assertTrue(direct.all_direct)
        self.assertFalse(direct.needs_seller_verification)
        self.assertEqual(market.total_cents, 2500)
        self.assertFalse(market.all_direct)
        self.assertFalse(market.needs_seller_verification)
        self.assertEqual(market.split[0].seller_certainty, "marketplace")
        self.assertEqual(market.stores[0].qualifying_cents, 2500)
        self.assertTrue(market.stores[0].threshold_crossed)
        self.assertEqual(market.stores[0].shipping_cents, 0)

    def test_unknown_changes_the_total_versus_counting_it(self) -> None:
        result = solve(
            [_store("S", threshold=3000, shipping=500)],
            [
                _item("known", ("S", 2000, "direct")),
                _item("mystery", ("S", 2000, "unknown")),
            ],
        )
        # If the unknown 2000 counted, qualifying would be 4000 and shipping 0.
        self.assertEqual(result.stores[0].qualifying_cents, 2000)
        self.assertEqual(result.stores[0].shipping_cents, 500)
        self.assertEqual(result.total_cents, 4500)
        self.assertTrue(result.needs_seller_verification)
        self.assertFalse(result.all_direct)

    def test_marketplace_changes_directness_but_still_clears_threshold(self) -> None:
        result = solve(
            [_store("S", threshold=3000, shipping=500)],
            [
                _item("shelf", ("S", 1000, "direct")),
                _item("third-party", ("S", 2000, "marketplace")),
            ],
        )
        self.assertEqual(result.stores[0].qualifying_cents, 3000)
        self.assertTrue(result.stores[0].threshold_crossed)
        self.assertEqual(result.total_cents, 3000)
        self.assertFalse(result.all_direct)
        self.assertFalse(result.needs_seller_verification)


class MembershipVerdicts(unittest.TestCase):
    """Membership is solved with and without. Break-even is in orders of this basket.

    One item at 4000, shipping 2000, threshold unreachable, fee 0.
    Without membership: 6000.
    With covers_shipping, before the membership price: 4000. Gross savings 2000.
    """

    def _basket(self, price: int):
        return solve(
            [
                _store(
                    "M",
                    threshold=100_000,
                    shipping=2000,
                    membership=Membership(price_cents=price, period="year", covers_shipping=True),
                )
            ],
            [_item("book", ("M", 4000, "direct"))],
        )

    def test_membership_pays_for_itself(self) -> None:
        result = self._basket(1500)
        self.assertEqual(result.total_cents, 6000)
        self.assertFalse(result.membership_applied)
        self.assertEqual(len(result.membership), 1)
        verdict = result.membership[0]
        self.assertEqual(verdict.without_membership_total_cents, 6000)
        self.assertEqual(verdict.with_membership_before_price_cents, 4000)
        self.assertEqual(verdict.with_membership_total_cents, 5500)
        self.assertEqual(verdict.gross_savings_cents, 2000)
        self.assertEqual(verdict.cost_difference_cents, 500)
        self.assertTrue(verdict.pays_for_itself)
        self.assertEqual(verdict.break_even_orders, 1)
        self.assertEqual(verdict.period, "year")
        self.assertEqual(result.stores[0].shipping_cents, 2000)
        self.assertIn("not crossed", result.stores[0].threshold_reason)

    def test_membership_does_not_pay_for_itself(self) -> None:
        result = self._basket(5000)
        verdict = result.membership[0]
        self.assertEqual(result.total_cents, 6000)
        self.assertEqual(verdict.with_membership_total_cents, 9000)
        self.assertEqual(verdict.cost_difference_cents, -3000)
        self.assertEqual(verdict.gross_savings_cents, 2000)
        self.assertFalse(verdict.pays_for_itself)
        self.assertEqual(verdict.break_even_orders, 3)


class AwkwardSingleItem(unittest.TestCase):
    """Two stores, one item, and neither order can reach its threshold.

    A: price 1000, threshold 5000, ship 400, fee 100 -> 1500.
    B: price 1500, threshold 8000, ship 200, fee 0 -> 1700.
    """

    def test_neither_threshold_is_reached(self) -> None:
        result = solve(
            [
                _store("A", threshold=5000, shipping=400, fee=100),
                _store("B", threshold=8000, shipping=200, fee=0),
            ],
            [_item("only", ("A", 1000, "direct"), ("B", 1500, "direct"))],
        )

        self.assertEqual(result.total_cents, 1500)
        self.assertEqual(result.split[0].store_id, "A")
        self.assertEqual(len(result.stores), 1)
        chosen = result.stores[0]
        self.assertFalse(chosen.threshold_crossed)
        self.assertEqual(chosen.qualifying_cents, 1000)
        self.assertEqual(chosen.shipping_cents, 400)
        self.assertEqual(chosen.per_order_fee_cents, 100)
        self.assertEqual(chosen.store_total_cents, 1500)
        self.assertIn("1000 cents < threshold 5000 cents", chosen.threshold_reason)

        baseline = {row.store_id: row for row in result.single_store_baseline.per_store}
        self.assertTrue(baseline["A"].feasible)
        self.assertTrue(baseline["B"].feasible)
        self.assertEqual(baseline["A"].total_cents, 1500)
        self.assertEqual(baseline["B"].total_cents, 1700)
        self.assertEqual(result.single_store_baseline.best_store_id, "A")
        self.assertEqual(result.single_store_baseline.total_cents, 1500)
        self.assertEqual(result.membership, ())


class ReproducibleRules(unittest.TestCase):
    def test_per_order_fee_is_once_for_three_items(self) -> None:
        result = solve(
            [_store("A", threshold=10_000, shipping=100, fee=250)],
            [
                _item("a", ("A", 100, "direct")),
                _item("b", ("A", 100, "direct")),
                _item("c", ("A", 100, "direct")),
            ],
        )
        # 300 items + 100 shipping + 250 fee once = 650. Not 300 + 100 + 750.
        self.assertEqual(result.total_cents, 650)
        self.assertEqual(result.stores[0].per_order_fee_cents, 250)

    def test_unknown_is_rejected_as_a_synonym_for_direct(self) -> None:
        result = solve(
            [_store("A", threshold=100, shipping=50)],
            [_item("a", ("A", 100, "unknown"))],
        )
        self.assertEqual(result.split[0].seller_certainty, "unknown")
        self.assertNotEqual(result.split[0].seller_certainty, "direct")
        self.assertFalse(result.stores[0].threshold_crossed)
        self.assertEqual(result.total_cents, 150)

    def test_tie_breaks_on_fewer_stores_then_name(self) -> None:
        # Equal money either way: one store at 1000, or the same item only at A.
        result = solve(
            [
                _store("B", threshold=0, shipping=0),
                _store("A", threshold=0, shipping=0),
            ],
            [_item("a", ("B", 1000, "direct"), ("A", 1000, "direct"))],
        )
        self.assertEqual(result.total_cents, 1000)
        self.assertEqual(result.split[0].store_id, "A")

    def test_mixed_currency_is_refused(self) -> None:
        with self.assertRaises(SolverError):
            solve(
                [
                    _store("A", threshold=0, shipping=0, currency="USD"),
                    _store("B", threshold=0, shipping=0, currency="RON"),
                ],
                [_item("a", ("A", 100, "direct"), ("B", 100, "direct"))],
            )


if __name__ == "__main__":
    unittest.main()

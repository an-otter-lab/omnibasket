"""Exhaustive, deterministic assignment of basket items to stores."""

from __future__ import annotations

import math
from itertools import product

from solver.types import (
    THRESHOLD_CERTAINTIES,
    Assignment,
    Item,
    MembershipVerdict,
    Offer,
    SingleStoreBaseline,
    SingleStoreOption,
    Solution,
    Store,
    StoreBreakdown,
)

_CERTAINTIES = frozenset({"direct", "marketplace", "unknown"})
# 8**10 is about 1e9; keep the search obviously small and fail closed.
_MAX_ASSIGNMENTS = 500_000


class SolverError(ValueError):
    """The basket or registry cannot be solved as given."""


def solve(stores: list[Store] | tuple[Store, ...], items: list[Item] | tuple[Item, ...]) -> Solution:
    """Return the cheapest split and the membership verdicts.

    The headline ``total_cents`` is the optimum with no membership applied.
    Each store that offers a membership is solved a second time with that
    membership covering shipping, and compared with the headline total.
    """

    store_by_id = _validate(stores, items)
    assignment = _optimal_assignment(store_by_id, items, membership_store_id=None)
    return _build_solution(store_by_id, items, assignment, membership_store_id=None)


def _validate(stores: list[Store] | tuple[Store, ...], items: list[Item] | tuple[Item, ...]) -> dict[str, Store]:
    if not stores:
        raise SolverError("store registry is empty")
    if not items:
        raise SolverError("basket is empty")

    store_by_id: dict[str, Store] = {}
    for store in stores:
        if store.id in store_by_id:
            raise SolverError(f"duplicate store id {store.id!r}")
        if not store.currency:
            raise SolverError(f"store {store.id!r} has no currency")
        _non_negative(store.free_shipping_threshold_cents, f"{store.id} threshold")
        _non_negative(store.shipping_fee_cents, f"{store.id} shipping fee")
        _non_negative(store.per_order_fee_cents, f"{store.id} per-order fee")
        if store.membership is not None:
            _non_negative(store.membership.price_cents, f"{store.id} membership price")
            if not store.membership.period:
                raise SolverError(f"store {store.id!r} membership has no period")
        store_by_id[store.id] = store

    currencies = {store.currency for store in store_by_id.values()}
    if len(currencies) != 1:
        raise SolverError(
            "mixed currencies are not converted: " + ", ".join(sorted(currencies))
        )

    seen_items: set[str] = set()
    assignments = 1
    for item in items:
        if item.id in seen_items:
            raise SolverError(f"duplicate item id {item.id!r}")
        seen_items.add(item.id)
        if not item.offers:
            raise SolverError(f"item {item.id!r} has no offers")
        seen_stores: set[str] = set()
        for offer in item.offers:
            if offer.store_id not in store_by_id:
                raise SolverError(f"item {item.id!r} offers unknown store {offer.store_id!r}")
            if offer.store_id in seen_stores:
                raise SolverError(f"item {item.id!r} has two offers at {offer.store_id!r}")
            seen_stores.add(offer.store_id)
            if offer.seller_certainty not in _CERTAINTIES:
                raise SolverError(
                    f"item {item.id!r} seller certainty {offer.seller_certainty!r} "
                    "is not direct, marketplace or unknown"
                )
            if offer.seller_certainty == "unknown":
                # Never coerce. Callers and tests can rely on the flag surviving.
                pass
            _non_negative(offer.price_cents, f"{item.id} price at {offer.store_id}")
        assignments *= len(item.offers)
        if assignments > _MAX_ASSIGNMENTS:
            raise SolverError(
                f"search space {assignments} exceeds {_MAX_ASSIGNMENTS}; split the basket"
            )
    return store_by_id


def _non_negative(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SolverError(f"{label} must be an integer number of cents")
    if value < 0:
        raise SolverError(f"{label} is negative")


def _optimal_assignment(
    store_by_id: dict[str, Store],
    items: list[Item] | tuple[Item, ...],
    membership_store_id: str | None,
) -> tuple[Offer, ...]:
    """Pick the assignment with the lowest total, then a stable tie break."""

    best_key: tuple | None = None
    best: tuple[Offer, ...] | None = None
    offer_lists = [item.offers for item in items]
    for combo in product(*offer_lists):
        total = _evaluate(store_by_id, items, combo, membership_store_id)
        store_ids = tuple(offer.store_id for offer in combo)
        # Fewer orders wins a tie, then lexicographic store assignment,
        # so the same inputs always return the same split.
        key = (total, len(set(store_ids)), store_ids)
        if best_key is None or key < best_key:
            best_key = key
            best = combo
    assert best is not None
    return best


def _evaluate(
    store_by_id: dict[str, Store],
    items: list[Item] | tuple[Item, ...],
    combo: tuple[Offer, ...],
    membership_store_id: str | None,
) -> int:
    by_store: dict[str, list[tuple[Item, Offer]]] = {}
    for item, offer in zip(items, combo, strict=True):
        by_store.setdefault(offer.store_id, []).append((item, offer))

    total = 0
    for store_id, rows in by_store.items():
        store = store_by_id[store_id]
        total += _store_cost(store, rows, membership_on=store_id == membership_store_id)
    if membership_store_id is not None:
        membership = store_by_id[membership_store_id].membership
        assert membership is not None
        total += membership.price_cents
    return total


def _store_cost(store: Store, rows: list[tuple[Item, Offer]], membership_on: bool) -> int:
    items_cents = sum(offer.price_cents for _, offer in rows)
    qualifying = _qualifying_cents(rows)
    shipping = _shipping_cents(store, qualifying, membership_on)
    # One fee per store that received at least one item, never per item.
    return items_cents + shipping + store.per_order_fee_cents


def _qualifying_cents(rows: list[tuple[Item, Offer]]) -> int:
    return sum(
        offer.price_cents
        for _, offer in rows
        if offer.seller_certainty in THRESHOLD_CERTAINTIES
    )


def _shipping_cents(store: Store, qualifying_cents: int, membership_on: bool) -> int:
    if qualifying_cents >= store.free_shipping_threshold_cents:
        return 0
    if membership_on and store.membership is not None and store.membership.covers_shipping:
        return 0
    return store.shipping_fee_cents


def _build_solution(
    store_by_id: dict[str, Store],
    items: list[Item] | tuple[Item, ...],
    combo: tuple[Offer, ...],
    membership_store_id: str | None,
) -> Solution:
    by_store: dict[str, list[tuple[Item, Offer]]] = {}
    split: list[Assignment] = []
    for item, offer in zip(items, combo, strict=True):
        by_store.setdefault(offer.store_id, []).append((item, offer))
        split.append(
            Assignment(
                item_id=item.id,
                store_id=offer.store_id,
                price_cents=offer.price_cents,
                seller_certainty=offer.seller_certainty,
            )
        )

    breakdowns: list[StoreBreakdown] = []
    goods_and_fees = 0
    for store_id in sorted(by_store):
        store = store_by_id[store_id]
        rows = by_store[store_id]
        membership_on = store_id == membership_store_id
        breakdown = _breakdown(store, rows, membership_on)
        breakdowns.append(breakdown)
        goods_and_fees += breakdown.store_total_cents

    membership_price = 0
    if membership_store_id is not None:
        membership = store_by_id[membership_store_id].membership
        assert membership is not None
        membership_price = membership.price_cents

    certainties = [offer.seller_certainty for offer in combo]
    currency = next(iter(store_by_id.values())).currency
    headline_total = goods_and_fees + membership_price

    # Membership verdicts are always against the no-membership optimum.
    if membership_store_id is None:
        verdicts = _membership_verdicts(store_by_id, items, headline_total)
        single = _single_store_baseline(store_by_id, items)
    else:
        verdicts = ()
        single = SingleStoreBaseline(None, None, ())

    return Solution(
        split=tuple(split),
        total_cents=headline_total,
        currency=currency,
        needs_seller_verification=any(c == "unknown" for c in certainties),
        all_direct=all(c == "direct" for c in certainties),
        stores=tuple(breakdowns),
        single_store_baseline=single,
        membership=verdicts,
        membership_applied=membership_store_id is not None,
    )


def _breakdown(store: Store, rows: list[tuple[Item, Offer]], membership_on: bool) -> StoreBreakdown:
    items_cents = sum(offer.price_cents for _, offer in rows)
    qualifying = _qualifying_cents(rows)
    unknown = sum(offer.price_cents for _, offer in rows if offer.seller_certainty == "unknown")
    crossed = qualifying >= store.free_shipping_threshold_cents
    covers = bool(
        membership_on and store.membership is not None and store.membership.covers_shipping
    )
    if crossed:
        threshold_reason = (
            f"crossed: qualifying subtotal {qualifying} cents >= threshold "
            f"{store.free_shipping_threshold_cents} cents "
            f"(unknown {unknown} cents excluded; marketplace counts, direct counts)"
        )
        shipping_reason = "waived: qualifying subtotal reached the free-shipping threshold"
        shipping = 0
    else:
        threshold_reason = (
            f"not crossed: qualifying subtotal {qualifying} cents < threshold "
            f"{store.free_shipping_threshold_cents} cents "
            f"(unknown {unknown} cents excluded and never treated as direct)"
        )
        if covers:
            shipping_reason = (
                "waived: membership covers shipping; threshold was not crossed"
            )
            shipping = 0
        else:
            shipping_reason = (
                "charged: threshold not crossed and membership does not cover shipping"
            )
            shipping = store.shipping_fee_cents

    fee = store.per_order_fee_cents
    certainties = tuple(offer.seller_certainty for _, offer in rows)
    return StoreBreakdown(
        store_id=store.id,
        currency=store.currency,
        item_ids=tuple(item.id for item, _ in rows),
        items_cents=items_cents,
        qualifying_cents=qualifying,
        unknown_cents=unknown,
        threshold_cents=store.free_shipping_threshold_cents,
        threshold_crossed=crossed,
        threshold_reason=threshold_reason,
        shipping_cents=shipping,
        shipping_reason=shipping_reason,
        per_order_fee_cents=fee,
        store_total_cents=items_cents + shipping + fee,
        seller_certainties=certainties,
    )


def _membership_verdicts(
    store_by_id: dict[str, Store],
    items: list[Item] | tuple[Item, ...],
    without_total: int,
) -> tuple[MembershipVerdict, ...]:
    verdicts: list[MembershipVerdict] = []
    for store_id in sorted(store_by_id):
        store = store_by_id[store_id]
        membership = store.membership
        if membership is None:
            continue
        with_assignment = _optimal_assignment(store_by_id, items, membership_store_id=store_id)
        with_total = _evaluate(store_by_id, items, with_assignment, membership_store_id=store_id)
        before_price = with_total - membership.price_cents
        gross = without_total - before_price
        difference = without_total - with_total
        verdicts.append(
            MembershipVerdict(
                store_id=store_id,
                period=membership.period,
                membership_price_cents=membership.price_cents,
                without_membership_total_cents=without_total,
                with_membership_before_price_cents=before_price,
                with_membership_total_cents=with_total,
                cost_difference_cents=difference,
                gross_savings_cents=gross,
                pays_for_itself=difference >= 0,
                break_even_orders=_break_even_orders(membership.price_cents, gross),
            )
        )
    return tuple(verdicts)


def _break_even_orders(price_cents: int, gross_savings_cents: int) -> int | None:
    if gross_savings_cents <= 0:
        return None
    return math.ceil(price_cents / gross_savings_cents)


def _single_store_baseline(
    store_by_id: dict[str, Store],
    items: list[Item] | tuple[Item, ...],
) -> SingleStoreBaseline:
    options: list[SingleStoreOption] = []
    best_id: str | None = None
    best_total: int | None = None
    for store_id in sorted(store_by_id):
        offers: list[Offer] = []
        missing: list[str] = []
        for item in items:
            match = next((offer for offer in item.offers if offer.store_id == store_id), None)
            if match is None:
                missing.append(item.id)
            else:
                offers.append(match)
        if missing:
            options.append(
                SingleStoreOption(
                    store_id=store_id,
                    total_cents=0,
                    feasible=False,
                    reason="missing offers for " + ", ".join(missing),
                )
            )
            continue
        total = _evaluate(store_by_id, items, tuple(offers), membership_store_id=None)
        options.append(
            SingleStoreOption(
                store_id=store_id,
                total_cents=total,
                feasible=True,
                reason="all items assigned to this store; no membership",
            )
        )
        if best_total is None or total < best_total or (total == best_total and store_id < (best_id or "")):
            best_total = total
            best_id = store_id
    return SingleStoreBaseline(best_id, best_total, tuple(options))

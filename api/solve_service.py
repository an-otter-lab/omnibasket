"""Cache-only solve of the locked basket, plus a JSON shape for the solver."""

from __future__ import annotations

from solver import solve
from solver.optimize import ROMANIAN_STORE_IDS, SolverError
from solver.types import Assignment, Item, Offer, Solution, Store, StoreBreakdown

from api.cache import PageCache


def cheapest_per_item(stores: list[Store], items: list[Item]) -> dict:
    """Each item at its cheapest shop, then that shop's measured fees.

    Same rule as the basket lock: goods count toward the threshold, then
    one shipping fee and one per-order fee for each shop that was used.
    """

    store_by_id = {store.id: store for store in stores}
    chosen: list[dict] = []
    goods_by_store: dict[str, int] = {}
    for item in items:
        offer = min(item.offers, key=lambda row: (row.price_cents, row.store_id))
        goods_by_store[offer.store_id] = goods_by_store.get(offer.store_id, 0) + offer.price_cents
        chosen.append(
            {
                "item_id": item.id,
                "store_id": offer.store_id,
                "price_cents": offer.price_cents,
            }
        )
    store_rows = []
    total = 0
    for store_id in sorted(goods_by_store):
        store = store_by_id[store_id]
        goods = goods_by_store[store_id]
        under_bar = goods < store.free_shipping_threshold_cents
        unknown = under_bar and not store.shipping_fee_known
        shipping = None if unknown else (0 if not under_bar else store.shipping_fee_cents)
        row_total = None if shipping is None else goods + shipping + store.per_order_fee_cents
        if row_total is None:
            total = None
        elif total is not None:
            total += row_total
        store_rows.append(
            {
                "store_id": store_id,
                "items_cents": goods,
                "shipping_cents": shipping,
                "per_order_fee_cents": store.per_order_fee_cents,
                "store_total_cents": row_total,
            }
        )
    currency = stores[0].currency if stores else ""
    return {
        "currency": currency,
        "total_cents": total,
        "lines": chosen,
        "stores": store_rows,
    }


def offers_from_cache(
    cache: PageCache,
    pages: list[dict],
    *,
    source: str,
) -> tuple[list[Item], list[dict]]:
    """Keep an offer only when source=cache has its saved page.

    Prices stay the locked integer cents. The cache proves the page was
    captured; it is not asked to re-price the line.
    """

    if source != "cache":
        raise SolverError(f"unsupported solve source {source!r}")
    events: list[dict] = []
    by_item: dict[str, list[Offer]] = {}
    order: list[str] = []
    for page in pages:
        hit = cache.get(page["store_id"], page["isbn13"], page["item_id"], page["day"])
        event = {
            "store_id": page["store_id"],
            "isbn13": page["isbn13"] or None,
            "item_id": page["item_id"],
            "day": page["day"],
            "cache": "hit" if hit else "miss",
            "status": "ok" if hit else "failed",
            "reason": None if hit else "cache_miss",
        }
        events.append(event)
        if hit is None:
            continue
        if page["item_id"] not in by_item:
            order.append(page["item_id"])
            by_item[page["item_id"]] = []
        by_item[page["item_id"]].append(
            Offer(page["store_id"], int(page["price_cents"]), page["seller_certainty"])
        )
    items = [Item(item_id, tuple(by_item[item_id])) for item_id in order if by_item[item_id]]
    if len(items) != len({page["item_id"] for page in pages}):
        missing = sorted({page["item_id"] for page in pages} - {item.id for item in items})
        missed = [
            {
                "item_id": page["item_id"],
                "store_id": page["store_id"],
                "title": page.get("title") or "",
            }
            for page in pages
            if page["item_id"] in missing
            and not any(
                event["item_id"] == page["item_id"]
                and event["store_id"] == page["store_id"]
                and event["cache"] == "hit"
                for event in events
            )
        ]
        error = SolverError("cache miss for items: " + ", ".join(missing))
        error.misses = missed  # type: ignore[attr-defined]
        raise error
    return items, events


def solution_payload(
    stores: list[Store],
    items: list[Item],
    *,
    require_romanian_store: bool = False,
    excluded_stores: list[dict] | None = None,
) -> dict:
    """Honest optimum plus the cheapest split that uses eMAG or Bookzone.

    The top-level total is the optimum unless ``require_romanian_store``
    is set, in which case it is the constrained split. Both answers are
    always present. An infeasible constraint raises ``SolverError``.
    """

    optimum = solve(stores, items)
    try:
        romanian = solve(stores, items, require_any_store=ROMANIAN_STORE_IDS)
    except SolverError:
        romanian = None
    if require_romanian_store and romanian is None:
        raise SolverError(
            "no feasible assignment includes one of: " + ", ".join(sorted(ROMANIAN_STORE_IDS))
        )
    headline = romanian if require_romanian_store else optimum
    assert headline is not None
    baseline = cheapest_per_item(stores, items)
    payload = _public_solution(headline)
    payload["cheapest_per_item"] = baseline
    payload["membership"] = [
        {
            "store_id": row.store_id,
            "period": row.period,
            "membership_price_cents": row.membership_price_cents,
            "without_membership_total_cents": row.without_membership_total_cents,
            "with_membership_total_cents": row.with_membership_total_cents,
            "cost_difference_cents": row.cost_difference_cents,
            "gross_savings_cents": row.gross_savings_cents,
            "pays_for_itself": row.pays_for_itself,
            "break_even_orders": row.break_even_orders,
        }
        for row in headline.membership
    ]
    payload["needs_seller_verification"] = headline.needs_seller_verification
    payload["optimum"] = _public_solution(optimum)
    payload["romanian_inclusive"] = _romanian_answer(romanian)
    payload["excluded_stores"] = list(excluded_stores or [])
    return payload


def _assignment_rows(split: tuple[Assignment, ...]) -> list[dict]:
    return [
        {
            "item_id": row.item_id,
            "store_id": row.store_id,
            "price_cents": row.price_cents,
            "seller_certainty": row.seller_certainty,
        }
        for row in split
    ]


def _store_rows(stores: tuple[StoreBreakdown, ...]) -> list[dict]:
    return [
        {
            "store_id": row.store_id,
            "currency": row.currency,
            "item_ids": list(row.item_ids),
            "items_cents": row.items_cents,
            "qualifying_cents": row.qualifying_cents,
            "shipping_cents": row.shipping_cents,
            "per_order_fee_cents": row.per_order_fee_cents,
            "store_total_cents": row.store_total_cents,
            "threshold_cents": row.threshold_cents,
            "threshold_crossed": row.threshold_crossed,
        }
        for row in stores
    ]


def _public_solution(result: Solution) -> dict:
    return {
        "currency": result.currency,
        "total_cents": result.total_cents,
        "assignment": _assignment_rows(result.split),
        "stores": _store_rows(result.stores),
    }


def _romanian_answer(result: Solution | None) -> dict | None:
    if result is None:
        return None
    used = sorted({row.store_id for row in result.split if row.store_id in ROMANIAN_STORE_IDS})
    body = _public_solution(result)
    body["romanian_stores"] = used
    return body


def stores_from_body(rows: list[dict]) -> list[Store]:
    stores = []
    for row in rows:
        stores.append(
            Store(
                id=row["id"],
                currency=row["currency"],
                free_shipping_threshold_cents=int(row["free_shipping_threshold_cents"]),
                shipping_fee_cents=int(row["shipping_fee_cents"]),
                per_order_fee_cents=int(row["per_order_fee_cents"]),
                membership=None,
            )
        )
    return stores


def items_from_body(rows: list[dict]) -> list[Item]:
    items = []
    for row in rows:
        offers = tuple(
            Offer(offer["store_id"], int(offer["price_cents"]), offer["seller_certainty"])
            for offer in row["offers"]
        )
        items.append(Item(id=row["id"], offers=offers))
    return items

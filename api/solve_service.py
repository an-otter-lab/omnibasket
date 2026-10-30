"""Cache-only solve of the locked basket, plus a JSON shape for the solver."""

from __future__ import annotations

from solver import solve
from solver.optimize import ROMANIAN_STORE_IDS, SolverError
from solver.types import Assignment, Item, Offer, Solution, Store, StoreBreakdown

from api.cache import PageCache
from api.plan import PlanContext, _usable, build_plan, context_from_items
from matching.validate import compare_read_to_capture


def model_read_row(hit: dict | None, page: dict) -> dict:
    """What Muse Spark read on this saved page, and whether it agrees with it.

    The check compares the read with the captured price and ISBN. It never
    changes a price: a mismatch is reported on the offer and left alone.
    """

    record = (hit or {}).get("model_json")
    check = compare_read_to_capture(
        record,
        price_cents=page.get("price_cents"),
        isbn13=page.get("isbn13") or None,
        currency=page.get("currency") or "RON",
    )
    return {
        "status": check["status"],
        "model": (record or {}).get("model"),
        "read_at": (record or {}).get("read_at"),
        "mismatch_fields": list(check["mismatch_fields"]),
    }


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
            "model_read": model_read_row(hit, page),
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
    plan_ctx: PlanContext | None = None,
    selected_store_ids: list[str] | None = None,
    edition_pins: dict[str, str] | None = None,
) -> dict:
    """Honest optimum plus the cheapest split that uses eMAG or Bookzone.

    The top-level total is the optimum unless ``require_romanian_store``
    is set, in which case it is the constrained split. Both answers are
    always present. An infeasible constraint raises ``SolverError``.
    """

    ctx = plan_ctx or context_from_items(stores, items)
    pins = {k: v for k, v in (edition_pins or {}).items() if v and v != "any"}
    if pins:
        # The headline follows the pins when every book still has an offer.
        pinned, missing = _usable(ctx, pins)
        if not missing:
            items = pinned
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
    payload["single_store_baseline"] = {
        "best_store_id": optimum.single_store_baseline.best_store_id,
        "total_cents": optimum.single_store_baseline.total_cents,
    }
    payload["romanian_inclusive"] = _romanian_answer(romanian)
    payload["excluded_stores"] = list(excluded_stores or [])
    payload.update(
        build_plan(ctx, selected_store_ids=selected_store_ids, edition_pins=edition_pins)
    )
    return payload


def context_from_locked(
    stores: list[Store],
    items: list[Item],
    pages: list[dict],
    events: list[dict],
    shop_rows: list[dict],
) -> PlanContext:
    """Plan context for the cache path. Every field is what the lock and cache hold."""

    hit = {(e["item_id"], e["store_id"]) for e in events if e["cache"] == "hit"}
    read_by_key = {
        (e["item_id"], e["store_id"]): e.get("model_read") for e in events if e["cache"] == "hit"
    }
    priced = {store.id for store in stores}
    books: dict[str, dict] = {}
    meta: dict[tuple[str, str], dict] = {}
    other: list[dict] = []
    failed: list[dict] = []
    for page in pages:
        books.setdefault(
            page["item_id"],
            {"title": page.get("title") or page["item_id"], "isbn13": page.get("isbn13") or None},
        )
        key = (page["item_id"], page["store_id"])
        if key not in hit:
            # A cache miss means no read was tried in this solve.
            failed.append(
                {
                    "item_id": page["item_id"],
                    "store_id": page["store_id"],
                    "reason": "cache_miss",
                    "attempts": 0,
                    "failed_at": None,
                }
            )
            continue
        meta[key] = {
            "edition": page.get("edition"),
            "listing_url": page.get("listing_url"),
            "read_at": page.get("read_at"),
            "in_stock": page.get("in_stock"),
            "model_read": read_by_key.get(key),
        }
        if page["store_id"] not in priced:
            other.append(
                {
                    "item_id": page["item_id"],
                    "store_id": page["store_id"],
                    "price_cents": int(page["price_cents"]),
                    "seller_certainty": page["seller_certainty"],
                }
            )
    ordered = {item.id: item for item in items}
    return PlanContext(
        currency=stores[0].currency if stores else "",
        stores=stores,
        items=[ordered[i] for i in books if i in ordered],
        shops=shop_rows,
        books=books,
        offer_meta=meta,
        other_offers=other,
        failed_reads=failed,
        cached=True,
    )


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


def stores_from_body(rows: list[dict], profiles=None) -> list[Store]:
    """Posted store rows. The shop file, then the row, may say direct-only."""

    by_shop = {profile.id: profile for profile in (profiles or [])}
    stores = []
    for row in rows:
        shipping = row["shipping_fee_cents"]
        known = shipping is not None
        profile = by_shop.get(row["id"])
        seller_model = (
            profile.seller_model if profile is not None else row.get("seller_model") or "mixed"
        )
        stores.append(
            Store(
                id=row["id"],
                currency=row["currency"],
                free_shipping_threshold_cents=int(row["free_shipping_threshold_cents"]),
                shipping_fee_cents=int(shipping) if known else 0,
                per_order_fee_cents=int(row["per_order_fee_cents"]),
                membership=None,
                shipping_fee_known=known,
                direct_only=seller_model == "direct_only",
            )
        )
    return stores


def context_from_body(
    stores: list[Store],
    items: list[Item],
    rows: list[dict],
    store_rows: list[dict],
    excluded: list[dict],
) -> PlanContext:
    """Plan context for a posted basket: optional fields come from the post."""

    books: dict[str, dict] = {}
    meta: dict[tuple[str, str], dict] = {}
    for row in rows:
        books[row["id"]] = {"title": row.get("title") or row["id"], "isbn13": row.get("isbn13")}
        for offer in row["offers"]:
            meta[(row["id"], offer["store_id"])] = {
                "edition": offer.get("edition"),
                "listing_url": offer.get("listing_url"),
                "read_at": offer.get("read_at"),
                "in_stock": offer.get("in_stock"),
            }
    read = {row["id"]: row.get("read_at") for row in store_rows}
    shops = [
        {"id": s.id, "solvable": True, "read_at": read.get(s.id), "fees": {}} for s in stores
    ] + [
        {"id": e["id"], "solvable": False, "read_at": None, "fees": {k: v for k, v in e.items() if k.endswith("_cents")}}
        for e in excluded
    ]
    return PlanContext(
        currency=stores[0].currency if stores else "",
        stores=stores,
        items=items,
        shops=shops,
        books=books,
        offer_meta=meta,
    )


def items_from_body(rows: list[dict]) -> list[Item]:
    items = []
    for row in rows:
        offers = tuple(
            Offer(offer["store_id"], int(offer["price_cents"]), offer["seller_certainty"])
            for offer in row["offers"]
        )
        items.append(Item(id=row["id"], offers=offers))
    return items

"""Everything the screens read, built from solver calls and nothing else.

The view computes nothing. Every number a screen shows is a field here.
An unprinted fee stays null and is never summed as 0. An assignment that
needs one is "not ranked": it carries its books subtotal and the missing
fee, never a total.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from solver.optimize import NoFeasibleAssignment, cheapest_unranked, solve
from solver.types import THRESHOLD_CERTAINTIES, Item, Offer, Store

REASON_TEXT = {
    "not_listed": "not listed here",
    "out_of_stock": "out of stock",
    "fees_not_printed": "its delivery or per-order fee is not printed",
    "couldnt_read": "the page could not be read",
    "other_edition": "not in the pinned edition",
}

# Reasons a shop cannot take a book.
NOT_LISTED = "not_listed"
OUT_OF_STOCK = "out_of_stock"
FEES_NOT_PRINTED = "fees_not_printed"
COULDNT_READ = "couldnt_read"
OTHER_EDITION = "other_edition"


@dataclass
class PlanContext:
    currency: str
    stores: list[Store]  # shops the solver can price
    items: list[Item]  # basket order, every edition, solvable shops only
    shops: list[dict]  # every shop: id, solvable, read_at, fees
    books: dict[str, dict]  # item_id -> {title, isbn13}
    offer_meta: dict[tuple[str, str], dict] = field(default_factory=dict)
    other_offers: list[dict] = field(default_factory=list)  # offers at unpriced shops
    failed_reads: list[dict] = field(default_factory=list)
    cached: bool = False

    @property
    def store_by_id(self) -> dict[str, Store]:
        return {store.id: store for store in self.stores}


def context_from_items(stores: list[Store], items: list[Item], *, cached: bool = False) -> PlanContext:
    """Minimal context for a caller that posted only arithmetic."""

    return PlanContext(
        currency=stores[0].currency if stores else "",
        stores=stores,
        items=items,
        shops=[{"id": s.id, "solvable": True, "read_at": None, "fees": {}} for s in stores],
        books={item.id: {"title": item.id, "isbn13": None} for item in items},
        cached=cached,
    )


# ---------------------------------------------------------------- helpers


def _meta(ctx: PlanContext, item_id: str, store_id: str) -> dict:
    return ctx.offer_meta.get((item_id, store_id), {})


NO_MODEL_READ = {"status": "not_read", "model": None, "read_at": None, "mismatch_fields": []}


def _model_read(ctx: PlanContext, item_id: str, store_id: str) -> dict:
    """Every offer carries its read status. The UI renders it as it is."""

    row = _meta(ctx, item_id, store_id).get("model_read")
    return dict(row) if isinstance(row, dict) else dict(NO_MODEL_READ)


def _unavailable(ctx: PlanContext, item_id: str, store_id: str) -> bool:
    return _meta(ctx, item_id, store_id).get("in_stock") is False


def _usable(
    ctx: PlanContext,
    pins: dict[str, str],
    allowed: set[str] | frozenset[str] | None = None,
) -> tuple[list[Item], list[dict]]:
    """Items with only the offers this plan may use, plus books left with none."""

    kept: list[Item] = []
    missing: list[dict] = []
    for item in ctx.items:
        offers = []
        for offer in item.offers:
            if allowed is not None and offer.store_id not in allowed:
                continue
            if _unavailable(ctx, item.id, offer.store_id):
                continue
            pin = pins.get(item.id)
            if pin and _meta(ctx, item.id, offer.store_id).get("edition") != pin:
                continue
            offers.append(offer)
        if offers:
            kept.append(Item(item.id, tuple(offers)))
        else:
            missing.append(
                {
                    "item_id": item.id,
                    "title": ctx.books[item.id]["title"],
                    "pin": pins.get(item.id),
                }
            )
    return kept, missing


def _missing_reason(missing: list[dict], scope: str) -> str:
    first = missing[0]
    if first["pin"]:
        return f"no shop {scope}prints {first['title']} as {first['pin']}"
    return f"no shop {scope}lists {first['title']}"


def delivery_gap(
    threshold_cents: int | None,
    qualifying_cents: int,
    delivery_cents: int | None,
) -> dict | None:
    """How far this order is from its shop's free-delivery bar.

    The bar is the solver's own ``free_shipping_threshold_cents`` and the
    amount counted is the solver's qualifying subtotal, so the gap matches
    what the solver charged. Plain integer cents, no model.

    Returns None (the line is hidden) when the threshold is unknown, or when
    the order is over the bar but its delivery is still not proven to be 0
    (Bookzone's unprinted charge at the bar): "reached" is never claimed
    unless the solver priced delivery at 0.
    """

    if threshold_cents is None:
        return None
    short = threshold_cents - qualifying_cents
    if short > 0:
        return {"status": "short", "short_cents": short, "threshold_cents": threshold_cents}
    if delivery_cents != 0:
        return None
    return {"status": "reached", "short_cents": 0, "threshold_cents": threshold_cents}


def _order_rows(ctx: PlanContext, rows: list[dict]) -> list[dict]:
    """One order per distinct shop, with every per-book and per-fee line."""

    store_by_id = ctx.store_by_id
    shop_read = {shop["id"]: shop.get("read_at") for shop in ctx.shops}
    order_of = {item.id: i for i, item in enumerate(ctx.items)}
    by_store: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: order_of.get(r["item_id"], 0)):
        by_store.setdefault(row["store_id"], []).append(row)
    orders = []
    for store_id in sorted(by_store):
        store = store_by_id[store_id]
        lines = by_store[store_id]
        items_cents = sum(r["price_cents"] for r in lines)
        qualifying = sum(
            r["price_cents"] for r in lines if r["seller_certainty"] in THRESHOLD_CERTAINTIES
        )
        crossed = qualifying >= store.free_shipping_threshold_cents
        # Bookzone's unprinted delivery charge applies at the 200 lei bar
        # too; its advertised threshold does not make that fee known.
        unprinted_at_bar = store.id == "bookzone" and crossed and not store.shipping_fee_known
        if crossed and not unprinted_at_bar:
            shipping: int | None = 0
        elif store.shipping_fee_known:
            shipping = store.shipping_fee_cents
        else:
            shipping = None
        fee = store.per_order_fee_cents
        orders.append(
            {
                "store_id": store_id,
                "currency": store.currency,
                "books": [
                    {
                        "item_id": r["item_id"],
                        "title": ctx.books[r["item_id"]]["title"],
                        "isbn13": ctx.books[r["item_id"]]["isbn13"],
                        "edition": _meta(ctx, r["item_id"], store_id).get("edition"),
                        "price_cents": r["price_cents"],
                        "currency": store.currency,
                        "seller_certainty": r["seller_certainty"],
                        "listing_url": _meta(ctx, r["item_id"], store_id).get("listing_url"),
                        "read_at": _meta(ctx, r["item_id"], store_id).get("read_at"),
                    }
                    for r in lines
                ],
                "books_subtotal_cents": items_cents,
                "qualifying_cents": qualifying,
                "free_delivery_threshold_cents": store.free_shipping_threshold_cents,
                "threshold_crossed": crossed,
                # Positive: over the bar. Negative: short of it.
                "over_under_threshold_cents": qualifying - store.free_shipping_threshold_cents,
                "short_of_threshold_cents": max(0, store.free_shipping_threshold_cents - qualifying),
                # Feature 4: the free-delivery gap line. None hides it.
                "delivery_gap": delivery_gap(store.free_shipping_threshold_cents, qualifying, shipping),
                "delivery_known": shipping is not None,
                "delivery_cents": shipping,
                "order_fee_cents": fee,
                "order_total_cents": None if shipping is None else items_cents + shipping + fee,
                "read_at": shop_read.get(store_id),
            }
        )
    return orders


def _rows_from_offers(items: list[Item], combo: tuple[Offer, ...]) -> list[dict]:
    return [
        {
            "item_id": item.id,
            "store_id": offer.store_id,
            "price_cents": offer.price_cents,
            "seller_certainty": offer.seller_certainty,
        }
        for item, offer in zip(items, combo, strict=True)
    ]


def _answer(ctx: PlanContext, rows: list[dict] | None, *, reason: str | None = None) -> dict:
    """A ranked answer, or not possible. A total only when every fee is known."""

    if rows is None:
        return {
            "status": "not_possible",
            "reason": reason,
            "currency": ctx.currency,
            "total_cents": None,
            "books_subtotal_cents": None,
            "order_count": None,
            "orders": [],
            "delta_vs_cheapest_cents": None,
            "not_ranked": [],
        }
    orders = _order_rows(ctx, rows)
    missing = _missing_fees(ctx, orders)
    ranked = not missing
    return {
        "status": "ranked" if ranked else "not_ranked",
        "reason": None if ranked else "a delivery fee is not printed for this split",
        "currency": ctx.currency,
        "total_cents": sum(o["order_total_cents"] for o in orders) if ranked else None,
        "books_subtotal_cents": sum(o["books_subtotal_cents"] for o in orders),
        "order_count": len(orders),
        "orders": orders,
        "missing_fees": missing,
        "delta_vs_cheapest_cents": None,
        "not_ranked": [],
    }


def _missing_fees(ctx: PlanContext, orders: list[dict]) -> list[dict]:
    return [
        {"store_id": o["store_id"], "field": "shipping_fee_cents", "books_subtotal_cents": o["books_subtotal_cents"]}
        for o in orders
        if not o["delivery_known"]
    ]


def _solve_rows(
    ctx: PlanContext,
    items: list[Item],
    use_exactly: set[str] | None = None,
) -> tuple[str, list[dict] | None]:
    """("ranked"|"not_ranked"|"none", rows)."""

    try:
        solution = solve(ctx.stores, items, use_exactly=use_exactly)
    except NoFeasibleAssignment:
        found = cheapest_unranked(ctx.stores, items, use_exactly=use_exactly)
        if found is None:
            return "none", None
        combo, _subtotal = found
        return "not_ranked", _rows_from_offers(items, combo)
    return "ranked", [
        {
            "item_id": row.item_id,
            "store_id": row.store_id,
            "price_cents": row.price_cents,
            "seller_certainty": row.seller_certainty,
        }
        for row in solution.split
    ]


def _cheaper_unranked(ctx: PlanContext, items: list[Item], ranked_total: int | None) -> list[dict]:
    """A split that looks cheaper by books alone but needs an unprinted fee."""

    if ranked_total is None:
        return []
    found = cheapest_unranked(ctx.stores, items)
    if found is None:
        return []
    combo, subtotal = found
    if subtotal >= ranked_total:
        return []
    answer = _answer(ctx, _rows_from_offers(items, combo))
    return [
        {
            "books_subtotal_cents": subtotal,
            "total_cents": None,
            "orders": answer["orders"],
            "missing_fees": answer["missing_fees"],
        }
    ]


def _delta(answer: dict, cheapest: dict) -> None:
    if answer["total_cents"] is not None and cheapest["total_cents"] is not None:
        answer["delta_vs_cheapest_cents"] = answer["total_cents"] - cheapest["total_cents"]


def _assigned(answer: dict) -> dict[str, dict]:
    return {
        book["item_id"]: {**book, "store_id": order["store_id"]}
        for order in answer["orders"]
        for book in order["books"]
    }


# ----------------------------------------------------------------- shops


def _shop_states(ctx: PlanContext) -> list[dict]:
    listed: dict[str, int] = {}
    for item in ctx.items:
        for offer in item.offers:
            listed[offer.store_id] = listed.get(offer.store_id, 0) + 1
    for offer in ctx.other_offers:
        listed[offer["store_id"]] = listed.get(offer["store_id"], 0) + 1
    failed: dict[str, list[dict]] = {}
    for fail in ctx.failed_reads:
        failed.setdefault(fail["store_id"], []).append(fail)
    states = []
    for shop in ctx.shops:
        store = ctx.store_by_id.get(shop["id"])
        usable = sum(
            1
            for item in ctx.items
            for offer in item.offers
            if offer.store_id == shop["id"] and not _unavailable(ctx, item.id, shop["id"])
        )
        if not shop["solvable"]:
            selectable, reason, code = False, "its delivery or per-order fee is not printed, so it cannot be priced", FEES_NOT_PRINTED
        elif usable == 0 and failed.get(shop["id"]):
            selectable, reason, code = False, "its pages could not be read", COULDNT_READ
        elif usable == 0:
            selectable, reason, code = False, "it lists none of these books", NOT_LISTED
        else:
            selectable, reason, code = True, None, None
        states.append(
            {
                "store_id": shop["id"],
                "currency": ctx.currency,
                "priced": bool(shop["solvable"]),
                "excluded": not shop["solvable"],
                "selectable": selectable,
                "not_selectable_code": code,
                "not_selectable_reason": reason,
                "read_at": shop.get("read_at"),
                "books_listed": usable,
                "failed_reads": failed.get(shop["id"], []),
                "free_delivery_threshold_cents": store.free_shipping_threshold_cents if store else shop.get("fees", {}).get("free_shipping_threshold_cents"),
                "delivery_cents": (store.shipping_fee_cents if store and store.shipping_fee_known else None),
                "delivery_known": bool(store and store.shipping_fee_known),
                "order_fee_cents": store.per_order_fee_cents if store else shop.get("fees", {}).get("per_order_fee_cents"),
            }
        )
    return states


def _book_rows(ctx: PlanContext, pins: dict[str, str], cheapest: dict) -> list[dict]:
    assigned = _assigned(cheapest)
    failed = {(f["item_id"], f["store_id"]): f for f in ctx.failed_reads}
    priced_ids = {s.id for s in ctx.stores}
    books = []
    for item in ctx.items:
        offers_by_shop: dict[str, dict] = {}
        for offer in item.offers:
            offers_by_shop[offer.store_id] = {
                "price_cents": offer.price_cents,
                "seller_certainty": offer.seller_certainty,
            }
        for other in ctx.other_offers:
            if other["item_id"] == item.id:
                offers_by_shop[other["store_id"]] = {
                    "price_cents": other["price_cents"],
                    "seller_certainty": other["seller_certainty"],
                }
        shop_rows = []
        for shop in ctx.shops:
            sid = shop["id"]
            meta = _meta(ctx, item.id, sid)
            found = offers_by_shop.get(sid)
            if found is None:
                status = COULDNT_READ if (item.id, sid) in failed else NOT_LISTED
            elif _unavailable(ctx, item.id, sid):
                status = OUT_OF_STOCK
            elif sid not in priced_ids:
                status = FEES_NOT_PRINTED
            elif pins.get(item.id) and meta.get("edition") != pins[item.id]:
                status = OTHER_EDITION
            elif assigned.get(item.id, {}).get("store_id") == sid:
                status = "in_plan"
            else:
                status = "compared"
            shop_rows.append(
                {
                    "store_id": sid,
                    "status": status,
                    "price_cents": found["price_cents"] if found else None,
                    "currency": ctx.currency,
                    "seller_certainty": found["seller_certainty"] if found else None,
                    "edition": meta.get("edition"),
                    "listing_url": meta.get("listing_url"),
                    "read_at": meta.get("read_at"),
                    "model_read": _model_read(ctx, item.id, sid),
                }
            )
        editions: dict[str, dict] = {}
        for row in shop_rows:
            if row["price_cents"] is None or row["edition"] is None:
                continue
            slot = editions.setdefault(
                row["edition"], {"edition": row["edition"], "cheapest_price_cents": row["price_cents"], "store_ids": []}
            )
            slot["store_ids"].append(row["store_id"])
            slot["cheapest_price_cents"] = min(slot["cheapest_price_cents"], row["price_cents"])
        books.append(
            {
                "item_id": item.id,
                "title": ctx.books[item.id]["title"],
                "isbn13": ctx.books[item.id]["isbn13"],
                "edition_pin": pins.get(item.id),
                "editions": sorted(editions.values(), key=lambda e: e["edition"]),
                "assigned_store_id": assigned.get(item.id, {}).get("store_id"),
                "shops": shop_rows,
            }
        )
    return books


# ------------------------------------------------------------- the tabs


def _one_parcel(ctx: PlanContext, items: list[Item], missing_all: list[dict], pins: dict[str, str], cheapest: dict, states: list[dict]) -> dict:
    state_by_id = {s["store_id"]: s for s in states}
    failed = {(f["item_id"], f["store_id"]) for f in ctx.failed_reads}
    listed_by_shop: dict[str, set[str]] = {}
    for item in items:
        for offer in item.offers:
            listed_by_shop.setdefault(offer.store_id, set()).add(item.id)
    other_by_shop: dict[str, set[str]] = {}
    for other in ctx.other_offers:
        other_by_shop.setdefault(other["store_id"], set()).add(other["item_id"])
    shops = []
    for shop in ctx.shops:
        sid = shop["id"]
        reasons: list[dict] = []
        if not shop["solvable"]:
            reasons.append(
                {
                    "code": FEES_NOT_PRINTED,
                    "item_ids": [],
                    "text": "its delivery or per-order fee is not printed",
                }
            )
        for item in ctx.items:
            have = item.id in listed_by_shop.get(sid, set())
            if have:
                continue
            raw = any(o.store_id == sid for o in item.offers)
            if not shop["solvable"] and item.id in other_by_shop.get(sid, set()):
                continue
            if raw and _unavailable(ctx, item.id, sid):
                code = OUT_OF_STOCK
            elif raw and pins.get(item.id):
                code = OTHER_EDITION
            elif (item.id, sid) in failed:
                code = COULDNT_READ
            else:
                code = NOT_LISTED
            reasons.append({"code": code, "item_ids": [item.id], "text": REASON_TEXT[code]})
        # Fold per-code book lists together.
        folded: dict[str, dict] = {}
        for reason in reasons:
            slot = folded.setdefault(reason["code"], {"code": reason["code"], "item_ids": [], "text": reason["text"]})
            slot["item_ids"].extend(reason["item_ids"])
        reasons = list(folded.values())
        entry = {
            "store_id": sid,
            "status": "not_possible",
            "reasons": reasons,
            "total_cents": None,
            "books_subtotal_cents": None,
            "delta_vs_cheapest_cents": None,
            "missing_fees": [],
            "answer": None,
        }
        if not reasons and state_by_id[sid]["selectable"]:
            only = [Item(i.id, tuple(o for o in i.offers if o.store_id == sid)) for i in items]
            kind, rows = _solve_rows(ctx, only, {sid})
            if kind != "none" and rows is not None:
                ans = _answer(ctx, rows)
                entry["status"] = ans["status"]
                entry["total_cents"] = ans["total_cents"]
                entry["books_subtotal_cents"] = ans["books_subtotal_cents"]
                entry["missing_fees"] = ans.get("missing_fees", [])
                entry["answer"] = ans
                _delta(ans, cheapest)
                entry["delta_vs_cheapest_cents"] = ans["delta_vs_cheapest_cents"]
        shops.append(entry)
    order = {"ranked": 0, "not_ranked": 1, "not_possible": 2}
    shops.sort(
        key=lambda e: (
            order[e["status"]],
            e["total_cents"] if e["total_cents"] is not None else 0,
            e["books_subtotal_cents"] if e["books_subtotal_cents"] is not None else 0,
            e["store_id"],
        )
    )
    best = next((e for e in shops if e["status"] == "ranked"), None)
    result = {
        "status": "ranked" if best else ("not_ranked" if any(e["status"] == "not_ranked" for e in shops) else "not_possible"),
        "reason": None,
        "best_store_id": best["store_id"] if best else None,
        "answer": best["answer"] if best else None,
        "per_book_delta": [],
        "shops": [{k: v for k, v in e.items() if k != "answer"} for e in shops],
    }
    if best is None:
        result["reason"] = (
            "no single shop has a known delivery fee for every book"
            if result["status"] == "not_ranked"
            else "no single shop lists every book"
        )
    elif cheapest["status"] == "ranked":
        here = _assigned(best["answer"])
        there = _assigned(cheapest)
        for item_id, row in here.items():
            other = there.get(item_id)
            result["per_book_delta"].append(
                {
                    "item_id": item_id,
                    "title": row["title"],
                    "price_cents": row["price_cents"],
                    "cheapest_price_cents": other["price_cents"] if other else None,
                    "cheapest_store_id": other["store_id"] if other else None,
                    # Positive: costs more here than in the cheapest plan.
                    "delta_cents": row["price_cents"] - other["price_cents"] if other else None,
                }
            )
    return result


def _custom(
    ctx: PlanContext,
    selected: list[str] | None,
    pins: dict[str, str],
    states: list[dict],
    cheapest: dict,
) -> dict | None:
    if selected is None:
        return None
    chosen = list(dict.fromkeys(selected))
    state_by_id = {s["store_id"]: s for s in states}
    unselectable = []
    for sid in chosen:
        state = state_by_id.get(sid)
        if state is None:
            unselectable.append({"store_id": sid, "code": "unknown_shop", "reason": "this shop is not part of the basket"})
        elif not state["selectable"]:
            unselectable.append({"store_id": sid, "code": state["not_selectable_code"], "reason": state["not_selectable_reason"]})
    base = {
        "selected_store_ids": chosen,
        "unselectable": unselectable,
        "moves": [],
    }
    if not chosen:
        return {**base, **_answer(ctx, None, reason="choose at least one shop")}
    if unselectable:
        return {**base, **_answer(ctx, None, reason="a chosen shop cannot be used: " + ", ".join(u["store_id"] for u in unselectable))}
    items, missing = _usable(ctx, pins, set(chosen))
    if missing:
        return {**base, **_answer(ctx, None, reason=_missing_reason(missing, "chosen "))}
    kind, rows = _solve_rows(ctx, items, set(chosen))
    if rows is None:
        return {**base, **_answer(ctx, None, reason="no split gives every chosen shop at least one book")}
    answer = _answer(ctx, rows)
    if kind == "not_ranked":
        answer["reason"] = "every split for these shops needs a delivery fee that is not printed"
    _delta(answer, cheapest)
    moves = []
    if cheapest["status"] == "ranked":
        there = _assigned(cheapest)
        for item_id, row in _assigned(answer).items():
            before = there.get(item_id)
            if before and before["store_id"] != row["store_id"]:
                moves.append(
                    {
                        "item_id": item_id,
                        "title": row["title"],
                        "from_store_id": before["store_id"],
                        "to_store_id": row["store_id"],
                        "from_price_cents": before["price_cents"],
                        "to_price_cents": row["price_cents"],
                        "price_delta_cents": row["price_cents"] - before["price_cents"],
                    }
                )
    return {**base, **answer, "moves": moves}


def _degraded(ctx: PlanContext, items: list[Item]) -> dict | None:
    priced = {s.id for s in ctx.stores}
    shops_with_books = {o.store_id for item in items for o in item.offers if o.store_id in priced}
    if len(ctx.items) == 1:
        return {"kind": "one_book", "reason": "one book: shops are ranked by known total"}
    if len(shops_with_books) == 1:
        return {
            "kind": "one_shop",
            "store_id": next(iter(shops_with_books)),
            "reason": "only one shop can be priced for these books",
        }
    return None


def _read_range(ctx: PlanContext) -> dict:
    stamps = sorted(
        {m["read_at"] for m in ctx.offer_meta.values() if m.get("read_at")}
        | {s["read_at"] for s in ctx.shops if s.get("read_at")}
    )
    return {"oldest": stamps[0] if stamps else None, "newest": stamps[-1] if stamps else None}


def build_plan(
    ctx: PlanContext,
    *,
    selected_store_ids: list[str] | None = None,
    edition_pins: dict[str, str] | None = None,
) -> dict:
    pins = {k: v for k, v in (edition_pins or {}).items() if v and v != "any"}
    unknown_pins = sorted(k for k in pins if k not in ctx.books)
    pins = {k: v for k, v in pins.items() if k in ctx.books}

    # The unpinned cheapest is the reference for the pin delta.
    free_items, _ = _usable(ctx, {})
    free_kind, free_rows = (
        _solve_rows(ctx, free_items) if len(free_items) == len(ctx.items) else ("none", None)
    )
    free_answer = _answer(ctx, free_rows if free_kind == "ranked" else None, reason="no ranked split")

    items, missing = _usable(ctx, pins)
    if missing:
        cheapest = _answer(ctx, None, reason=_missing_reason(missing, ""))
    else:
        _kind, rows = _solve_rows(ctx, items)
        cheapest = _answer(ctx, rows, reason="no ranked split")
    degraded = _degraded(ctx, items) if not missing else None
    if cheapest["status"] == "ranked":
        cheapest["not_ranked"] = _cheaper_unranked(ctx, items, cheapest["total_cents"])
        cheapest["delta_vs_cheapest_cents"] = 0
    if degraded and degraded["kind"] == "one_shop":
        # One shop only: the one-parcel answer stands, the other tabs cannot differ.
        cheapest = {**_answer(ctx, None, reason=degraded["reason"]), "degraded": True}

    states = _shop_states(ctx)
    one_parcel = _one_parcel(ctx, items, missing, pins, cheapest, states)
    if missing:
        one_parcel.update({"status": "not_possible", "reason": _missing_reason(missing, ""), "answer": None, "best_store_id": None})
    custom = _custom(ctx, selected_store_ids, pins, states, cheapest)
    if custom is not None and degraded and degraded["kind"] == "one_shop":
        custom = {**custom, **_answer(ctx, None, reason=degraded["reason"]), "moves": []}

    edition_delta = None
    if cheapest["status"] == "ranked" and free_answer["status"] == "ranked":
        edition_delta = cheapest["total_cents"] - free_answer["total_cents"]
    edition = {
        "pins": pins,
        "unknown_pins": unknown_pins,
        "status": cheapest["status"],
        "reason": cheapest["reason"],
        "unpinned_total_cents": free_answer["total_cents"],
        "total_cents": cheapest["total_cents"],
        "delta_cents": edition_delta,
        "not_ranked": cheapest["not_ranked"],
    }
    book_ref = cheapest if cheapest["status"] == "ranked" else {"orders": []}
    return {
        "cached": ctx.cached,
        "read_at_range": _read_range(ctx),
        "degraded": degraded,
        "shops": states,
        "books": _book_rows(ctx, pins, book_ref),
        "cheapest": cheapest,
        "one_parcel": one_parcel,
        "custom": custom,
        "edition": edition,
        "failed_reads": list(ctx.failed_reads),
    }

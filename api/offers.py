"""Main orchestrator for reading offers from indexed shops.

Coordinates parallel page reads, schema.org extraction, Muse gap-filling,
validation, and caching. Streams read_progress events over /events.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

# Add tools directory to path for meta_budget import
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from api.cache import PageCache
from api.fetch_guard import fetch, FetchRefused, USER_AGENT
from api.schema_org import extract_schema_org, SchemaOrgData
from api.muse_integration import gap_fill_with_muse, MuseResult
from matching.isbn import normalize_isbn13
from shop_profiles.loader import load_profile, ShopProfile

from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")


@dataclass
class ReadProgress:
    """Progress event for a shop read."""
    
    store_id: str
    isbn13: str | None
    status: str  # "reading", "ok", "failed", "skipped"
    message: str
    timestamp: str | None = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(TZ).isoformat(timespec="seconds")


@dataclass
class OfferRead:
    """Result of reading an offer from a shop."""
    
    store_id: str
    isbn13: str | None
    item_id: str
    price_cents: int | None = None
    currency: str | None = None
    availability: str | None = None
    edition: str | None = None
    seller_certainty: str = "unknown"
    listing_url: str | None = None
    read_at: str | None = None
    in_stock: bool | None = None
    schema_org: SchemaOrgData | None = None
    muse_result: MuseResult | None = None
    status: str = "ok"  # "ok", "failed", "skipped"
    reason: str | None = None
    cache: str = "miss"  # "hit", "miss", "live"
    day: str | None = None


# Progress callback type
ProgressCallback = Callable[[ReadProgress], Awaitable[None] | None]


def _load_shop_profile(store_id: str) -> ShopProfile | None:
    """Load shop profile for a store."""
    profile_path = ROOT / "data" / "shops" / f"{store_id}.yaml"
    if not profile_path.exists():
        return None
    return load_profile(profile_path)


SHOP_LABEL = {
    "libris": "Libris",
    "bookzone": "Bookzone",
    "emag": "eMAG",
    "books_express": "Books-Express",
    "amazon_de": "Amazon.de",
}

_SEARCH_BITS = ("cauta", "cautare", "/search", "?q=", "/s?k=")
_INDEX_SHOP = {"books_express": "books-express"}


def _indexed_profiles() -> list[ShopProfile]:
    from shop_profiles.loader import load_all

    return [p for p in load_all(ROOT / "data" / "shops") if p.domain]


def default_live_stores() -> list[str]:
    """Every indexed shop with a profile in data/shops (paste-only has no domain)."""
    return [p.id for p in _indexed_profiles()]


def valid_live_stores() -> set[str]:
    return set(default_live_stores())


def shop_label(store_id: str) -> str:
    return SHOP_LABEL.get(store_id, store_id)


def progress_message(store_id: str, status: str) -> str:
    name = shop_label(store_id)
    if status == "cache":
        return f"{name}: read from cache"
    if status == "failed" and store_id != "emag":
        return f"{name}: read failed"
    if store_id == "emag" and status == "failed":
        return "eMAG couldn't be read, skipped"
    if store_id == "amazon_de" and status in {"skipped", "ok"}:
        return "Amazon.de: not read live"
    if status == "reading":
        return f"Reading {name}…"
    if status == "skipped" and store_id != "amazon_de":
        return f"{name}: no match in our index"
    return f"{name}: {status}"


def _searchish(url: str) -> bool:
    low = url.lower()
    return any(bit in low for bit in _SEARCH_BITS)


def lookup_product_url(store_id: str, isbn13: str | None, db_path: Path | None = None) -> str | None:
    """Product page from our sitemap index. Never a shop search URL.

    Amazon.de is not in the pulled index and is never fetched.
    """
    if not isbn13 or store_id == "amazon_de":
        return None
    path = db_path or (ROOT / "data" / "index" / "books.sqlite3")
    if not path.is_file():
        return None
    import sqlite3

    shop = _INDEX_SHOP.get(store_id, store_id)
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT url FROM books WHERE shop = ? AND isbn = ? ORDER BY last_seen DESC LIMIT 1",
            (shop, isbn13),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row or not row[0] or _searchish(row[0]):
        return None
    return row[0]


def captured_amazon() -> dict[str, str]:
    """ISBN -> listing URL for Amazon.de rows already in the locked basket."""
    import yaml

    basket = yaml.safe_load((ROOT / "data" / "baskets" / "ro-v1.yaml").read_text())
    found: dict[str, str] = {}
    for book in basket.get("books") or []:
        isbn = book.get("isbn13") or ""
        for offer in book.get("offers") or []:
            if offer.get("store_id") != "amazon_de":
                continue
            url = offer.get("listing_url")
            if isbn and url:
                found[str(isbn)] = str(url)
    return found


def amazon_check_link(isbn13: str | None) -> str | None:
    """Shopper link only. Never fetched. Captured ISBNs keep their product URL."""
    if not isbn13:
        return None
    captured = captured_amazon()
    if isbn13 in captured:
        return captured[isbn13]
    return f"https://www.amazon.de/s?k={isbn13}"


def _get_product_url(store_id: str, isbn13: str | None, index_lookup=None) -> str | None:
    """Resolve a product page from the index. Shop search URLs are never returned."""
    if store_id == "amazon_de":
        return None
    lookup = index_lookup or lookup_product_url
    url = lookup(store_id, isbn13)
    if not url or _searchish(url):
        return None
    return url


def run_matching_checks(fields: dict, primary_isbn: str | None) -> dict:
    """ISBN check digit, strict edition split, seller tri-state. Production path."""
    from matching.editions import match_offers
    from matching.validate import validate_extraction

    validated, verdict = validate_extraction(dict(fields))
    grouped = match_offers([validated], "strict_isbn", primary_isbn)
    primary = normalize_isbn13(primary_isbn) if primary_isbn else None
    isbn = validated.get("isbn13")
    edition_rejected = bool(primary and isbn and isbn != primary)
    if "false_without_named_seller" in verdict["reasons"]:
        validated["sold_and_shipped_by_store"] = None
        validated["seller_certainty"] = "unknown"
    elif validated.get("sold_and_shipped_by_store") is True:
        validated["seller_certainty"] = "direct"
    elif validated.get("sold_and_shipped_by_store") is False:
        validated["seller_certainty"] = "marketplace"
    else:
        validated["seller_certainty"] = "unknown"
    return {
        "fields": validated,
        "verdict": verdict,
        "groups": grouped,
        "edition_rejected": edition_rejected,
        "isbn_rejected": "isbn_invalid" in verdict["reasons"],
        "seller_rejected": "false_without_named_seller" in verdict["reasons"],
    }


async def _read_one_page(
    store_id: str,
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    progress_callback: ProgressCallback | None = None,
    index_lookup=None,
) -> OfferRead:
    """Read one product page from a shop.
    
    1. Check cache first
    2. Fetch page with schema.org-first strategy
    3. Extract structured data
    4. Use Muse for gap-fill and cross-check
    5. Validate ISBN, edition, seller
    6. Store in cache
    7. Return result
    """
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    
    # Check cache first
    if isbn13:
        cached = cache.get(store_id, isbn13, item_id, day)
        if cached:
            # Extract from cached page using schema.org first
            page_text = cached.get("page_text", "")
            model_json = cached.get("model_json")
            
            # Try schema.org extraction from cached HTML
            schema_org = extract_schema_org(page_text)
            
            # Build offer from cached data
            offer = OfferRead(
                store_id=store_id,
                isbn13=schema_org.isbn13 or isbn13,
                item_id=item_id,
                price_cents=schema_org.price_cents,
                currency=schema_org.currency,
                availability=schema_org.availability,
                edition=None,
                seller_certainty="unknown",
                listing_url=None,
                read_at=None,
                in_stock=None,
                schema_org=schema_org,
                muse_result=None,
                status="ok" if schema_org.price_cents else "failed",
                reason=None if schema_org.price_cents else "no_price_in_cached_page",
                cache="hit",
                day=day,
            )
            
            # Muse numbers from a previous read are checked against the saved page.
            if model_json:
                from api.muse_integration import adopt_muse_fields

                adopted = adopt_muse_fields(model_json, page_text, schema_org)
                checked = run_matching_checks(adopted, isbn13)
                fields = checked["fields"]
                if schema_org.price_cents is None and fields.get("price") is not None:
                    offer.price_cents = int(round(float(fields["price"]) * 100))
                    offer.currency = fields.get("currency") or offer.currency
                if fields.get("isbn13"):
                    offer.isbn13 = fields["isbn13"]
                offer.seller_certainty = fields.get("seller_certainty") or "unknown"
                offer.edition = fields.get("format")
                if offer.price_cents is None:
                    offer.status = "failed"
                    offer.reason = "muse_price_dropped"
                elif checked["edition_rejected"]:
                    offer.status = "failed"
                    offer.reason = "edition_mismatch"
                else:
                    offer.status = "ok"
                    offer.reason = None
            
            if progress_callback:
                await _emit_progress(progress_callback, ReadProgress(
                    store_id=store_id,
                    isbn13=isbn13,
                    status=offer.status,
                    message=progress_message(store_id, "cache"),
                ))
            return offer
    
    # Load shop profile
    profile = _load_shop_profile(store_id)
    if not profile:
        offer = OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="failed",
            reason=f"unknown shop: {store_id}",
            cache="miss",
            day=day,
        )
        if progress_callback:
            await _emit_progress(progress_callback, ReadProgress(
                store_id=store_id,
                isbn13=isbn13,
                status="failed",
                message=f"{shop_label(store_id)}: unknown shop",
            ))
        return offer
    
    # Special handling for Amazon.de (never read live)
    if store_id == "amazon_de":
        offer = OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            listing_url=amazon_check_link(isbn13),
            status="skipped",
            reason="amazon_de_never_read_live",
            cache="miss",
            day=day,
        )
        if progress_callback:
            await _emit_progress(progress_callback, ReadProgress(
                store_id=store_id,
                isbn13=isbn13,
                status="skipped",
                message="Amazon.de: not read live",
            ))
        return offer
    
    # Amazon.de returned above, so it never announces a read.
    # Emit reading progress
    if progress_callback:
        await _emit_progress(progress_callback, ReadProgress(
            store_id=store_id,
            isbn13=isbn13,
            status="reading",
            message=progress_message(store_id, "reading"),
        ))
    
    # Special handling for eMAG (one honest try)
    if store_id == "emag":
        # Try once, then skip if failed
        try:
            offer = await _fetch_and_extract(
                store_id, isbn13, item_id, profile, cache, day, index_lookup=index_lookup
            )
            if offer.status == "failed":
                # Emit skip message for eMAG
                if progress_callback:
                    await _emit_progress(progress_callback, ReadProgress(
                        store_id=store_id,
                        isbn13=isbn13,
                        status="failed",
                        message="eMAG couldn't be read, skipped",
                    ))
            else:
                if progress_callback:
                    await _emit_progress(progress_callback, ReadProgress(
                        store_id=store_id,
                        isbn13=isbn13,
                        status="ok",
                        message=progress_message(store_id, "ok"),
                    ))
            return offer
        except Exception as e:
            offer = OfferRead(
                store_id=store_id,
                isbn13=isbn13,
                item_id=item_id,
                listing_url=_get_product_url(store_id, isbn13, index_lookup),
                status="failed",
                reason=f"emag_read_error: {type(e).__name__}",
                cache="miss",
                day=day,
            )
            if progress_callback:
                await _emit_progress(progress_callback, ReadProgress(
                    store_id=store_id,
                    isbn13=isbn13,
                    status="failed",
                    message="eMAG couldn't be read, skipped",
                ))
            return offer
    
    # Normal read for other shops
    try:
        offer = await _fetch_and_extract(
            store_id, isbn13, item_id, profile, cache, day, index_lookup=index_lookup
        )
        if progress_callback:
            await _emit_progress(progress_callback, ReadProgress(
                store_id=store_id,
                isbn13=isbn13,
                status=offer.status,
                message=progress_message(store_id, offer.status),
            ))
        return offer
    except Exception as e:
        offer = OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="failed",
            reason=f"read_error: {type(e).__name__}",
            cache="miss",
            day=day,
        )
        if progress_callback:
            await _emit_progress(progress_callback, ReadProgress(
                store_id=store_id,
                isbn13=isbn13,
                status="failed",
                message=progress_message(store_id, "failed"),
            ))
        return offer


async def _fetch_and_extract(
    store_id: str,
    isbn13: str | None,
    item_id: str,
    profile: ShopProfile,
    cache: PageCache,
    day: str,
    index_lookup=None,
) -> OfferRead:
    """Fetch one indexed product page and extract offer data."""
    url = _get_product_url(store_id, isbn13, index_lookup)
    if not url:
        return OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="skipped",
            reason="no_match_in_index",
            cache="miss",
            day=day,
        )
    
    # Fetch page
    try:
        result = await asyncio.to_thread(fetch, url)
    except FetchRefused as e:
        return OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            listing_url=url,
            status="failed",
            reason=f"fetch_refused: {e.reason}",
            cache="miss",
            day=day,
        )
    
    # Extract schema.org data
    schema_org = extract_schema_org(result.text)
    
    # Gap-fill with Muse if needed
    muse_result = None
    if not schema_org.has_price or not schema_org.has_isbn:
        muse_result = await asyncio.to_thread(gap_fill_with_muse, result.text, schema_org)
    
    # Build offer from extracted data
    price_cents = schema_org.price_cents
    currency = schema_org.currency
    availability = schema_org.availability
    isbn = schema_org.isbn13
    
    edition = None
    in_stock = None
    seller_certainty = "unknown"
    edition_rejected = False
    if muse_result and muse_result.fields:
        checked = run_matching_checks(muse_result.fields, isbn13)
        fields = checked["fields"]
        edition_rejected = checked["edition_rejected"]
        if price_cents is None and fields.get("price") is not None:
            price_cents = int(round(float(fields["price"]) * 100))
        if currency is None and fields.get("currency"):
            currency = fields["currency"]
        if fields.get("isbn13"):
            isbn = fields["isbn13"]
        edition = fields.get("format")
        in_stock = fields.get("in_stock")
        seller_certainty = fields.get("seller_certainty") or "unknown"
    elif availability:
        in_stock = "instock" in availability.lower()
    if isbn:
        isbn = normalize_isbn13(isbn)
    
    # Build offer
    offer = OfferRead(
        store_id=store_id,
        isbn13=isbn or isbn13,
        item_id=item_id,
        price_cents=price_cents,
        currency=currency or profile.currency,
        availability=availability,
        edition=edition,
        seller_certainty=seller_certainty,
        listing_url=url,
        read_at=datetime.now(TZ).isoformat(timespec="seconds"),
        in_stock=in_stock,
        schema_org=schema_org,
        muse_result=muse_result,
        status="failed" if edition_rejected or price_cents is None else "ok",
        reason="edition_mismatch" if edition_rejected else (None if price_cents is not None else "no_price_extracted"),
        cache="live",
        day=day,
    )
    
    # Store in cache if successful
    if offer.status == "ok" and isbn:
        cache.put({
            "store_id": store_id,
            "isbn13": isbn,
            "item_id": item_id,
            "day": day,
            "page_text": result.text,
            "screenshot_path": None,
            "model_json": muse_result.fields if muse_result else None,
            "provenance": {
                "source": "live_read",
                "url": url,
                "read_at": offer.read_at,
            },
        })
    
    return offer


async def _emit_progress(callback: ProgressCallback, progress: ReadProgress) -> None:
    """Emit a progress event."""
    result = callback(progress)
    if asyncio.iscoroutine(result):
        await result


def store_from_profile(store_id: str):
    """Solver Store from a shop profile's printed rules, or None when a fee is unprinted.

    A percent-based fee (eMAG) or a missing threshold is not turned into a number.
    """
    from solver.optimize import store_if_fees_resolved

    profile = _load_shop_profile(store_id)
    if profile is None or not profile.shipping_rules or profile.currency != "RON":
        return None
    rules = profile.shipping_rules
    if any(r.get("kind") == "operational_fee_percent" for r in rules):
        return None

    def cents(kind):
        for rule in rules:
            if rule.get("kind") == kind and rule.get("amount") is not None:
                return int(round(float(rule["amount"]) * 100))
        return None

    below = cents("below_threshold_fee")
    if below is None:
        below = cents("below_threshold_fee_floor")
    per_order = cents("per_order_fee")
    return store_if_fees_resolved(
        {
            "id": store_id,
            "currency": profile.currency,
            "free_shipping_threshold_cents": cents("free_threshold"),
            "shipping_fee_cents": below,
            "per_order_fee_cents": 0 if per_order is None else per_order,
        }
    )


def solve_with_live_offers(offers: list[OfferRead], item_id: str, title: str | None, isbn13: str | None) -> dict:
    """Join the chosen book onto the locked basket and return a real /solve payload.

    The joined book may be assigned to any shop that returned an offer and whose
    printed fees resolve (Libris, Bookzone, Books-Express, Amazon.de). A shop whose
    fees are unprinted (eMAG) is listed in excluded_stores, not priced. The locked
    ro-v1 solve does not use this function.
    """
    from dataclasses import replace

    from api.basket import load_locked, locked_shop_rows
    from api.solve_service import context_from_locked, solution_payload
    from solver.types import Item, Offer

    _day, _currency, stores, items, pages = load_locked()
    locked_ids = {store.id for store in stores}
    stores = list(stores)
    extra_shops: list[dict] = []
    excluded: list[dict] = []
    for offer in offers:
        if offer.status != "ok" or offer.price_cents is None or offer.store_id in locked_ids:
            continue
        if any(s.id == offer.store_id for s in stores) or any(e["id"] == offer.store_id for e in excluded):
            continue
        extra = store_from_profile(offer.store_id)
        if extra is None:
            excluded.append(
                {
                    "id": offer.store_id,
                    "reason": "unresolved fee",
                    "free_shipping_threshold_cents": None,
                    "shipping_fee_cents": None,
                    "per_order_fee_cents": None,
                }
            )
        else:
            stores.append(extra)
            extra_shops.append({"id": extra.id, "solvable": True, "read_at": None, "fees": {}})
    priced = {store.id for store in stores}
    live = tuple(
        Offer(
            offer.store_id,
            int(offer.price_cents),
            offer.seller_certainty if offer.seller_certainty in {"direct", "marketplace", "unknown"} else "unknown",
        )
        for offer in offers
        if offer.status == "ok" and offer.price_cents is not None and offer.store_id in priced
    )
    merged: list[Item] = []
    replaced = False
    for item in items:
        if item.id == item_id and live:
            merged.append(Item(item_id, live))
            replaced = True
        else:
            merged.append(item)
    if not replaced and live:
        merged.append(Item(item_id, live))
    # Without any live offer the locked basket still solves, so a refused shop does not stop the answer.
    solve_items = merged if live else list(items)

    events = [
        {"item_id": p["item_id"], "store_id": p["store_id"], "cache": "hit", "model_read": None}
        for p in pages
    ]
    ctx = context_from_locked(stores, solve_items, pages, events, locked_shop_rows())
    books = dict(ctx.books)
    book_title = title or item_id
    books[item_id] = {"title": book_title, "isbn13": isbn13}
    meta = dict(ctx.offer_meta)
    for offer in offers:
        if offer.status == "ok" and offer.store_id in priced:
            meta[(item_id, offer.store_id)] = {
                "edition": offer.edition,
                "listing_url": offer.listing_url,
                "read_at": offer.read_at,
                "in_stock": offer.in_stock,
            }
    shops = list(ctx.shops) + extra_shops + [
        {"id": e["id"], "solvable": False, "read_at": None, "fees": {k: v for k, v in e.items() if k.endswith("_cents")}}
        for e in excluded
    ]
    ctx = replace(ctx, items=solve_items, books=books, offer_meta=meta, shops=shops)
    payload = solution_payload(stores, solve_items, excluded_stores=excluded, plan_ctx=ctx)
    payload["joined_item_id"] = item_id
    payload["joined_title"] = book_title
    payload["joined_isbn13"] = isbn13
    payload["live_offers"] = [
        {
            "store_id": offer.store_id,
            "status": offer.status,
            "reason": offer.reason,
            "price_cents": offer.price_cents,
            "listing_url": offer.listing_url,
            "isbn13": offer.isbn13,
        }
        for offer in offers
    ]
    return payload


async def read_offers_parallel(
    store_ids: list[str],
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    progress_callback: ProgressCallback | None = None,
    index_lookup=None,
) -> list[OfferRead]:
    """Read offers from multiple shops in parallel.
    
    Args:
        store_ids: List of store IDs to read from
        isbn13: ISBN-13 to search for
        item_id: Item identifier
        cache: Page cache instance
        progress_callback: Optional callback for progress events
    
    Returns:
        List of OfferRead results, one per shop
    """
    tasks = [
        _read_one_page(store_id, isbn13, item_id, cache, progress_callback, index_lookup)
        for store_id in store_ids
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to failed offers
    offers = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            offers.append(OfferRead(
                store_id=store_ids[i],
                isbn13=isbn13,
                item_id=item_id,
                status="failed",
                reason=f"exception: {type(result).__name__}: {result}",
                cache="miss",
            ))
        else:
            offers.append(result)
    
    return offers


def read_offers_sync(
    store_ids: list[str],
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    index_lookup=None,
) -> list[OfferRead]:
    """Synchronous wrapper for read_offers_parallel."""
    return asyncio.run(
        read_offers_parallel(store_ids, isbn13, item_id, cache, index_lookup=index_lookup)
    )

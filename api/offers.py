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


def _get_product_url(store_id: str, isbn13: str) -> str | None:
    """Get product URL for a shop and ISBN.
    
    Constructs search URLs for each indexed shop based on ISBN.
    In production, this would search the index for exact product URLs.
    """
    if not isbn13:
        return None
    
    # Construct search/product URLs for each shop
    url_patterns = {
        "libris": f"https://www.libris.ro/cauta?q={isbn13}",
        "bookzone": f"https://bookzone.ro/cauta?q={isbn13}",
        "emag": f"https://www.emag.ro/search?q={isbn13}",
        "books_express": f"https://www.books-express.ro/cauta?q={isbn13}",
        "amazon_de": f"https://www.amazon.de/s?k={isbn13}",
    }
    
    return url_patterns.get(store_id)


async def _read_one_page(
    store_id: str,
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    progress_callback: ProgressCallback | None = None,
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
            
            # If schema.org didn't find price but we have model_json, use it
            if not schema_org.price_cents and model_json:
                if "price" in model_json and model_json["price"] is not None:
                    offer.price_cents = int(round(float(model_json["price"]) * 100))
                    offer.currency = model_json.get("currency")
                    offer.status = "ok"
                    offer.reason = None
            
            if progress_callback:
                await _emit_progress(progress_callback, ReadProgress(
                    store_id=store_id,
                    isbn13=isbn13,
                    status=offer.status,
                    message=f"{store_id}: cache hit",
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
                message=f"{store_id}: unknown shop",
            ))
        return offer
    
    # Emit reading progress
    if progress_callback:
        await _emit_progress(progress_callback, ReadProgress(
            store_id=store_id,
            isbn13=isbn13,
            status="reading",
            message=f"Reading {store_id}…",
        ))
    
    # Special handling for Amazon.de (never read live)
    if store_id == "amazon_de":
        offer = OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
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
    
    # Special handling for eMAG (one honest try)
    if store_id == "emag":
        # Try once, then skip if failed
        try:
            offer = await _fetch_and_extract(store_id, isbn13, item_id, profile, cache, day)
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
                        message=f"{store_id}: ok",
                    ))
            return offer
        except Exception as e:
            offer = OfferRead(
                store_id=store_id,
                isbn13=isbn13,
                item_id=item_id,
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
        offer = await _fetch_and_extract(store_id, isbn13, item_id, profile, cache, day)
        if progress_callback:
            await _emit_progress(progress_callback, ReadProgress(
                store_id=store_id,
                isbn13=isbn13,
                status=offer.status,
                message=f"{store_id}: {offer.status}",
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
                message=f"{store_id}: read failed",
            ))
        return offer


async def _fetch_and_extract(
    store_id: str,
    isbn13: str | None,
    item_id: str,
    profile: ShopProfile,
    cache: PageCache,
    day: str,
) -> OfferRead:
    """Fetch a page and extract offer data."""
    # Get product URL
    url = _get_product_url(store_id, isbn13)
    if not url:
        return OfferRead(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="failed",
            reason="no_product_url",
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
        muse_result = gap_fill_with_muse(result.text, schema_org)
    
    # Build offer from extracted data
    price_cents = schema_org.price_cents
    currency = schema_org.currency
    availability = schema_org.availability
    isbn = schema_org.isbn13
    
    # Fill from Muse if schema.org was incomplete
    if muse_result and muse_result.fields:
        fields = muse_result.fields
        if price_cents is None and "price" in fields and fields["price"] is not None:
            price_cents = int(round(float(fields["price"]) * 100))
        if currency is None and "currency" in fields:
            currency = fields["currency"]
        if isbn is None and "isbn13" in fields:
            isbn = normalize_isbn13(fields["isbn13"])
        if "format" in fields:
            edition = fields["format"]
        else:
            edition = None
        if "in_stock" in fields:
            in_stock = fields["in_stock"]
        else:
            in_stock = None
        
        # Determine seller certainty
        if "sold_and_shipped_by_store" in fields:
            if fields["sold_and_shipped_by_store"] is True:
                seller_certainty = "direct"
            elif fields["sold_and_shipped_by_store"] is False:
                seller_certainty = "marketplace"
            else:
                seller_certainty = "unknown"
        else:
            seller_certainty = "unknown"
    else:
        edition = None
        in_stock = None
        seller_certainty = "unknown"
        if availability:
            in_stock = "instock" in availability.lower()
    
    # Validate ISBN
    if isbn:
        validated_isbn = normalize_isbn13(isbn)
        if validated_isbn is None:
            isbn = None
        else:
            isbn = validated_isbn
    
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
        status="ok" if price_cents is not None else "failed",
        reason=None if price_cents is not None else "no_price_extracted",
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


async def read_offers_parallel(
    store_ids: list[str],
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    progress_callback: ProgressCallback | None = None,
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
        _read_one_page(store_id, isbn13, item_id, cache, progress_callback)
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
) -> list[OfferRead]:
    """Synchronous wrapper for read_offers_parallel.
    
    Convenience function for non-async contexts.
    """
    return asyncio.run(read_offers_parallel(store_ids, isbn13, item_id, cache))

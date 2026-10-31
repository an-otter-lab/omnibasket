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
    status: str  # "reading", "ok", "cache", "failed", "skipped", "not_checked"
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
    other_printing: bool = False  # shop page declares another ISBN of the same work


# Progress callback type
ProgressCallback = Callable[[ReadProgress], Awaitable[None] | None]


def _load_shop_profile(store_id: str) -> ShopProfile | None:
    """Load shop profile for a store."""
    profile_path = ROOT / "data" / "shops" / f"{store_id}.yaml"
    if not profile_path.exists():
        return None
    return load_profile(profile_path)


def shop_seller_certainty(profile: ShopProfile | None, certainty: str) -> str:
    """The seller certainty a shop's data file allows for a live offer.

    A ``direct_only`` shop sells only its own stock, so an offer whose page
    did not name a seller is ``direct``: the shop file, not the page, is the
    evidence. Every other shop keeps the page's own verdict unchanged.
    """

    if profile is not None and profile.seller_model == "direct_only" and certainty == "unknown":
        return "direct"
    return certainty


def with_shop_seller_model(store):
    """The solver Store with the shop file's seller model applied."""
    from dataclasses import replace

    profile = _load_shop_profile(store.id)
    if profile is None or profile.seller_model != "direct_only" or store.direct_only:
        return store
    return replace(store, direct_only=True)


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
    if status == "ok":
        return f"{name}: read"
    # S9: not_checked (the shop is not indexed) and anything else: never "Bookzone: not_checked".
    return f"{name}: not checked"


def _searchish(url: str) -> bool:
    low = url.lower()
    return any(bit in low for bit in _SEARCH_BITS)


def shop_is_indexed(store_id: str, db_path: Path | None = None) -> bool:
    """Check if a shop has any entries in the index at all."""
    if store_id == "amazon_de":
        return False
    path = db_path or (ROOT / "data" / "index" / "books.sqlite3")
    if not path.is_file():
        return False
    import sqlite3

    shop = _INDEX_SHOP.get(store_id, store_id)
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM books WHERE shop = ? LIMIT 1",
            (shop,),
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return row is not None and row[0] > 0


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


def lookup_title_url(store_id: str, title: str | None, author: str | None, db_path: Path | None = None) -> str | None:
    """Product page for a shop row that has the title but no ISBN. Never a search URL.

    Only a candidate: the page itself must still match strongly on name and author.
    """
    from difflib import SequenceMatcher

    from api.title_match import core_title, surname, strong_match
    from api.title_match import fold

    want = core_title(title)
    last = surname(author)
    if not want or not last or store_id == "amazon_de":
        return None
    path = db_path or (ROOT / "data" / "index" / "books.sqlite3")
    if not path.is_file():
        return None
    import sqlite3

    shop = _INDEX_SHOP.get(store_id, store_id)
    first = " ".join(want.split()[:2])
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT url, title FROM books WHERE shop = ? AND (isbn IS NULL OR isbn = '') AND title LIKE ? LIMIT 400",
            (shop, first + "%"),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    
    # Score candidates using full title comparison, not just prefix
    # Prefer: containment > high similarity > author match
    best, best_score = None, 0.0
    for url, row_title in rows:
        key = fold(row_title)
        if not url or _searchish(url) or last not in key.split():
            continue
        
        # Use full title comparison, not just prefix
        row_core = core_title(row_title)
        
        # Containment bonus: if shop title contains book title, strong preference
        containment_bonus = 1.0 if want in key else 0.0
        
        # Full SequenceMatcher ratio on entire core title
        full_ratio = SequenceMatcher(None, want, row_core).ratio()
        
        # Combined score: containment is most important, then full similarity
        score = containment_bonus + full_ratio
        
        if score > best_score:
            best, best_score = url, score
    
    return best if best_score > 0 else None


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
    """Shopper link only. Never fetched. Captured ISBNs keep their product URL.

    S5 (R11): with no captured product page there is no link; never a search URL.
    """
    if not isbn13:
        return None
    return captured_amazon().get(isbn13)


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
    title: str | None = None,
    author: str | None = None,
    title_lookup=None,
    listing_urls: dict[str, str] | None = None,
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

    # The shop file decides whether an unnamed seller counts as direct, so it
    # is needed on the cache path too.
    profile = _load_shop_profile(store_id)
    forced_url = (listing_urls or {}).get(store_id)

    # Check cache first
    if isbn13:
        cached = cache.get(store_id, isbn13, item_id, day)
        if cached:
            # Extract from cached page using schema.org first
            page_text = cached.get("page_text", "")
            model_json = cached.get("model_json")
            
            # Try schema.org extraction from cached HTML
            schema_org = extract_schema_org(page_text)
            # S3: the link and read time come from the first read of the day.
            provenance = cached.get("provenance") or {}
            cached_url = provenance.get("url") or (provenance.get("meta") or {}).get("final_url")
            availability = schema_org.availability
            
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
                listing_url=cached_url,
                read_at=provenance.get("read_at"),
                in_stock=("instock" in availability.lower()) if availability else None,
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
                offer.in_stock = fields.get("in_stock")
                if offer.price_cents is None:
                    offer.status = "failed"
                    offer.reason = "muse_price_dropped"
                elif checked["edition_rejected"]:
                    offer.status = "failed"
                    offer.reason = "edition_mismatch"
                else:
                    offer.status = "ok"
                    offer.reason = None

            offer.seller_certainty = shop_seller_certainty(profile, offer.seller_certainty or "unknown")
            
            if progress_callback:
                await _emit_progress(progress_callback, ReadProgress(
                    store_id=store_id,
                    isbn13=isbn13,
                    status=offer.status,
                    message=progress_message(store_id, "cache"),
                ))
            return offer
    
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
                store_id, isbn13, item_id, profile, cache, day, index_lookup=index_lookup,
                title=title, author=author, title_lookup=title_lookup, forced_url=forced_url,
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
                # S9: the real status (not_checked, skipped, cache, ok), never "ok" for any non-failure.
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
            store_id, isbn13, item_id, profile, cache, day, index_lookup=index_lookup,
            title=title, author=author, title_lookup=title_lookup, forced_url=forced_url,
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
    title: str | None = None,
    author: str | None = None,
    title_lookup=None,
    forced_url: str | None = None,
) -> OfferRead:
    """Fetch one indexed product page and extract offer data."""
    # A pasted shop page is the listing to read: the shop plainly has the book there.
    url = forced_url or _get_product_url(store_id, isbn13, index_lookup)
    if not url and title and author and store_id != "amazon_de":
        return await _read_other_printing(store_id, isbn13, item_id, profile, day, title, author, title_lookup, cache)
    if not url:
        # Check if the shop is indexed at all
        if not shop_is_indexed(store_id):
            return OfferRead(
                store_id=store_id,
                isbn13=isbn13,
                item_id=item_id,
                status="not_checked",
                reason="not_indexed",
                cache="miss",
                day=day,
            )
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
    # The shop file decides the seller model: a direct-only shop makes an
    # unnamed seller direct. eMAG and Amazon.de have no such line, so their
    # pages must name the seller before an offer counts as direct.
    seller_certainty = shop_seller_certainty(profile, seller_certainty or "unknown")
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


async def _read_other_printing(
    store_id: str,
    isbn13: str | None,
    item_id: str,
    profile: ShopProfile,
    day: str,
    title: str,
    author: str,
    title_lookup=None,
    cache: PageCache | None = None,
) -> OfferRead:
    """The shop has the work but not under this ISBN. Attach it only on a strong match.

    The offer keeps the page's own ISBN and is flagged other_printing. If the page
    does carry the asked-for ISBN it is the same edition and the flag stays off.
    No Muse call: schema.org is the only source here. The confirmation (match result,
    ISBN, price, availability) is kept for CONFIRMATION_TTL (24 h) under
    store|asked ISBN|title|author, so a repeat pick of the same work fetches nothing.
    """
    from api.title_match import strong_match, MATCHER_VERSION

    key = "|".join(["printing", str(MATCHER_VERSION), store_id, isbn13 or "", title.strip().lower(), author.strip().lower()])
    kept = cache.get_confirmation(key) if cache is not None else None
    if kept is not None:
        return _offer_from_confirmation(kept, store_id, isbn13, item_id, profile, day)

    skipped = OfferRead(
        store_id=store_id, isbn13=isbn13, item_id=item_id, status="skipped",
        reason="no_match_in_index", cache="miss", day=day,
    )
    url = (title_lookup or lookup_title_url)(store_id, title, author)
    if not url or _searchish(url):
        # Check if the shop is indexed at all
        if not shop_is_indexed(store_id):
            return OfferRead(
                store_id=store_id, isbn13=isbn13, item_id=item_id,
                status="not_checked", reason="not_indexed",
                cache="miss", day=day,
            )
        return skipped
    try:
        result = await asyncio.to_thread(fetch, url)
    except FetchRefused as e:
        return OfferRead(
            store_id=store_id, isbn13=isbn13, item_id=item_id, listing_url=url,
            status="failed", reason=f"fetch_refused: {e.reason}", cache="miss", day=day,
        )
    data = extract_schema_org(result.text)
    if not strong_match(title, author, data.name, data.authors or []):
        return skipped
    if data.isbn13 and not _book_isbn(data.isbn13):
        # S4: a shop barcode (e.g. a 642 GS1 code) is not an ISBN, so the item may not be the book.
        if cache is not None:
            cache.put_confirmation(key, {"matched": False})
        return skipped
    if data.price_cents is None or not data.isbn13:
        return OfferRead(
            store_id=store_id, isbn13=isbn13, item_id=item_id, listing_url=url,
            status="failed", reason="no_price_extracted", cache="miss", day=day,
        )
    if cache is not None:
        cache.put_confirmation(key, {
            "matched": True, "url": url, "isbn13": data.isbn13, "price_cents": data.price_cents,
            "currency": data.currency, "availability": data.availability,
            "name": data.name, "authors": data.authors or [],
        })
    return OfferRead(
        store_id=store_id,
        isbn13=data.isbn13,
        item_id=item_id,
        price_cents=data.price_cents,
        currency=data.currency or profile.currency,
        availability=data.availability,
        seller_certainty=shop_seller_certainty(profile, "unknown"),
        listing_url=url,
        read_at=datetime.now(TZ).isoformat(timespec="seconds"),
        in_stock=("instock" in data.availability.lower()) if data.availability else None,
        schema_org=data,
        status="ok",
        cache="live",
        day=day,
        other_printing=data.isbn13 != isbn13,
    )


def _book_isbn(value) -> str | None:
    """A valid ISBN-13 that is a book number (978/979), else None. S4: 642... is a shop barcode."""
    digits = normalize_isbn13(value)
    return digits if digits and digits[:3] in ("978", "979") else None


def _offer_from_confirmation(kept, store_id, isbn13, item_id, profile, day) -> OfferRead:
    if not kept.get("matched") or not _book_isbn(kept.get("isbn13")):
        return OfferRead(store_id=store_id, isbn13=isbn13, item_id=item_id, status="skipped",
                         reason="no_match_in_index", cache="miss", day=day)
    avail = kept.get("availability")
    data = SchemaOrgData(
        price_cents=kept["price_cents"], currency=kept.get("currency"), availability=avail,
        isbn13=kept["isbn13"], name=kept.get("name"), authors=kept.get("authors"),
    )
    return OfferRead(
        store_id=store_id, isbn13=kept["isbn13"], item_id=item_id, price_cents=kept["price_cents"],
        currency=kept.get("currency") or profile.currency, availability=avail,
        seller_certainty=shop_seller_certainty(profile, "unknown"),
        listing_url=kept["url"], read_at=datetime.now(TZ).isoformat(timespec="seconds"),
        in_stock=("instock" in avail.lower()) if avail else None, schema_org=data,
        status="ok", cache="hit", day=day, other_printing=kept["isbn13"] != isbn13,
    )


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
            "seller_model": profile.seller_model,
        }
    )


_NOT_RANKED_FEE_FIELDS = (
    "free_shipping_threshold_cents",
    "shipping_fee_cents",
    "per_order_fee_cents",
)


def not_ranked_reason(offer: OfferRead, priced: set[str], unranked_fees: set[str]) -> str | None:
    """Stable machine reason an offer is not ranked, or None when it is priced."""
    if offer.status == "ok" and offer.price_cents is not None and offer.store_id in priced:
        return None
    if offer.store_id in unranked_fees:
        return "delivery_rules_not_read"
    reason = offer.reason or ""
    if reason == "amazon_de_never_read_live":
        return "not_read_live"
    if reason == "no_match_in_index":
        return "no_offer"
    if reason.startswith("fetch_refused"):
        return "fetch_refused"
    if reason == "no_price_extracted":
        return "no_price_extracted"
    return reason or "no_offer"


def live_offer_row(offer: OfferRead, priced: set[str], unranked_fees: set[str]) -> dict:
    reason = not_ranked_reason(offer, priced, unranked_fees)
    row = {
        "store_id": offer.store_id,
        "status": offer.status,
        "reason": offer.reason,
        "price_cents": offer.price_cents,
        "listing_url": offer.listing_url,
        "isbn13": offer.isbn13,
        "ranked": reason is None,
        "other_printing": bool(offer.other_printing),
    }
    if reason is not None:
        row["not_ranked_reason"] = reason
        if offer.store_id in unranked_fees:
            for name in _NOT_RANKED_FEE_FIELDS:
                row[name] = None
    return row


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
    # The shop file also decides the seller model on the locked stores, so a
    # cached offer with no named seller still counts toward its free-delivery bar.
    stores = [with_shop_seller_model(store) for store in stores]
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
    # A live offer is direct when its shop file says the shop sells only its
    # own stock; otherwise the page's own verdict stands.
    live = tuple(
        Offer(
            offer.store_id,
            int(offer.price_cents),
            shop_seller_certainty(
                _load_shop_profile(offer.store_id),
                offer.seller_certainty if offer.seller_certainty in {"direct", "marketplace", "unknown"} else "unknown",
            ),
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
    unranked_fees = {e["id"] for e in excluded}
    payload["live_offers"] = [
        live_offer_row(offer, priced, unranked_fees) for offer in offers
    ]
    return payload


async def read_offers_parallel(
    store_ids: list[str],
    isbn13: str | None,
    item_id: str,
    cache: PageCache,
    progress_callback: ProgressCallback | None = None,
    index_lookup=None,
    title: str | None = None,
    author: str | None = None,
    title_lookup=None,
    listing_urls: dict[str, str] | None = None,
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
        _read_one_page(
            store_id, isbn13, item_id, cache, progress_callback, index_lookup, title, author, title_lookup,
            listing_urls=listing_urls,
        )
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

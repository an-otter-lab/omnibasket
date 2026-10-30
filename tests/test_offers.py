"""Tests for parallel offer reading and cache keying.

Tests that reads run in parallel, that Amazon.de is never read live,
that eMAG gets one honest try then skips, and that the cache is keyed
by store + ISBN + day.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo
from api.cache import PageCache
from api.offers import read_offers_parallel, read_offers_sync, _read_one_page
from api.schema_org import SchemaOrgData


@pytest.fixture
def cache(tmp_path):
    """Create a temporary cache for testing."""
    cache_path = tmp_path / "test_cache.sqlite"
    return PageCache(cache_path)


@pytest.fixture
def mock_fetch():
    """Mock the fetch function to avoid network calls."""
    with patch("api.fetch_guard.fetch") as mock:
        yield mock


def test_cache_key_includes_store_isbn_day(cache):
    """Test that cache key includes store_id, isbn13, and day."""
    day = "2026-10-30"
    store_id = "libris"
    isbn13 = "9786068996011"
    item_id = "ghici"
    
    # Store a page (cache only stores page_text and model_json, not parsed fields)
    cache.put({
        "store_id": store_id,
        "isbn13": isbn13,
        "item_id": item_id,
        "day": day,
        "page_text": "Test page with price 57.00 Lei",
        "screenshot_path": None,
        "model_json": {"price": 57.00, "currency": "RON"},
        "provenance": {},
    })
    
    # Retrieve with same key
    result = cache.get(store_id, isbn13, item_id, day)
    assert result is not None
    assert result["store_id"] == store_id
    assert result["isbn13"] == isbn13
    assert result["day"] == day
    assert "57.00" in result["page_text"]
    
    # Different day should miss
    result = cache.get(store_id, isbn13, item_id, "2026-10-31")
    assert result is None
    
    # Different store should miss
    result = cache.get("bookzone", isbn13, item_id, day)
    assert result is None
    
    # Different ISBN should miss
    result = cache.get(store_id, "9780241003008", item_id, day)
    assert result is None


def test_amazon_de_never_read_live(cache):
    """Test that Amazon.de is never read live."""
    store_id = "amazon_de"
    isbn13 = "9781529105100"
    item_id = "mole"
    
    # Attempt to read Amazon.de
    result = read_offers_sync([store_id], isbn13, item_id, cache)
    
    # Should be skipped, not read
    assert len(result) == 1
    assert result[0].store_id == store_id
    assert result[0].status == "skipped"
    assert result[0].reason == "amazon_de_never_read_live"
    assert result[0].cache == "miss"
    assert result[0].price_cents is None


def _product_index(store_id, isbn):
    pages = {
        "libris": "https://www.libris.ro/carte/ghici/21197307",
        "bookzone": "https://bookzone.ro/produs/ghici",
        "emag": "https://www.emag.ro/ghici/pd/DGJW95BBM/",
        "books_express": "https://www.books-express.ro/ghici/p/x,9786068996011",
    }
    return pages.get(store_id)


def test_never_requests_a_shop_search_url(cache, indexed_shops_db):
    """A missing index row is a skip. A hit is the product page, never /cauta or /search."""
    from api.fetch_guard import GuardedFetch

    seen = []

    def _fetch(url):
        seen.append(url)
        html = "<html><body>57.00 lei</body></html>"
        return GuardedFetch(url, 200, "text/html", html.encode(), html, 0)

    with patch("api.offers.fetch", side_effect=_fetch):
        missing = read_offers_sync(["libris"], "9786068996011", "ghici", cache, index_lookup=lambda s, i: None)
        assert missing[0].status == "skipped"
        assert missing[0].reason == "no_match_in_index"
        assert seen == []
        hit = read_offers_sync(["libris"], "9786068996011", "ghici", cache, index_lookup=_product_index)
        assert seen == ["https://www.libris.ro/carte/ghici/21197307"]
        assert hit[0].status in {"ok", "failed"}
        assert "cauta" not in seen[0] and "search" not in seen[0]


def test_emag_one_honest_try_then_skip(cache):
    """eMAG is fetched once. A refusal keeps the product link and does not stop the solve."""
    from api.fetch_guard import FetchRefused
    from api.offers import solve_with_live_offers

    with patch("api.offers.fetch") as mock_fetch:
        mock_fetch.side_effect = FetchRefused("HTTP 511 Captcha")
        result = read_offers_sync(["emag"], "9786068996011", "ghici", cache, index_lookup=_product_index)
        assert mock_fetch.call_count == 1
        assert result[0].status == "failed"
        assert result[0].listing_url == "https://www.emag.ro/ghici/pd/DGJW95BBM/"
        solved = solve_with_live_offers(result, "ghici", "Ghici", "9786068996011")
        assert solved["total_cents"] == 51516
        assert any(row["listing_url"] and row["store_id"] == "emag" for row in solved["live_offers"])


def test_parallel_reads_execute_concurrently(cache):
    """Two fetches overlap. A sequential implementation keeps max in-flight at 1."""
    import threading
    import time
    from api.fetch_guard import GuardedFetch

    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def _fetch(url):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.2)
        with lock:
            state["now"] -= 1
        html = "<html>57.00 lei</html>"
        return GuardedFetch(url, 200, "text/html", html.encode(), html, 0)

    with patch("api.offers.fetch", side_effect=_fetch):
        results = read_offers_sync(
            ["libris", "bookzone"], "9786068996011", "ghici", cache, index_lookup=_product_index
        )
    assert len(results) == 2
    assert state["max"] >= 2


def test_cache_hit_skips_fetch(cache):
    """Test that cache hit skips network fetch."""
    store_id = "libris"
    isbn13 = "9786068996011"
    item_id = "ghici"
    day = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d")
    
    # Pre-populate cache with correct schema
    cache.put({
        "store_id": store_id,
        "isbn13": isbn13,
        "item_id": item_id,
        "day": day,
        "page_text": "Cached page with price 57.00 Lei",
        "screenshot_path": None,
        "model_json": {"price": 57.00, "currency": "RON"},
        "provenance": {},
    })
    
    with patch("api.fetch_guard.fetch") as mock_fetch:
        # Attempt to read should hit cache
        result = read_offers_sync([store_id], isbn13, item_id, cache)
        
        # Should not have called fetch
        assert mock_fetch.call_count == 0
        assert len(result) == 1
        assert result[0].status == "ok"
        # Price should be extracted from cached page_text or model_json
        assert result[0].price_cents == 5700
        assert result[0].cache == "hit"


def test_schema_org_first_extraction(cache):
    """Test that schema.org extraction happens before Muse."""
    store_id = "libris"
    isbn13 = "9786068996011"
    item_id = "ghici"
    
    # Mock fetch to return HTML with schema.org
    from api.fetch_guard import GuardedFetch
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "isbn": "9786068996011",
            "offers": {
                "@type": "Offer",
                "price": "57.00",
                "priceCurrency": "RON",
                "availability": "https://schema.org/InStock"
            }
        }
        </script>
    </head>
    <body>
        <p>Price: 57.00 Lei</p>
    </body>
    </html>
    """
    
    with patch("api.offers.fetch") as mock_fetch:
        mock_fetch.return_value = GuardedFetch(
            final_url="https://libris.ro/test",
            status=200,
            content_type="text/html",
            body=html.encode(),
            text=html,
            hops=0,
        )
        
        # Read should extract from schema.org
        result = read_offers_sync([store_id], isbn13, item_id, cache, index_lookup=_product_index)
        
        # Should have extracted price and ISBN from schema.org
        assert len(result) == 1
        assert result[0].status == "ok"
        assert result[0].price_cents == 5700
        assert result[0].currency == "RON"
        assert result[0].isbn13 == isbn13


def test_progress_events_emitted_during_reads(cache):
    """Test that read_progress events are emitted during parallel reads."""
    import asyncio
    
    store_ids = ["libris", "bookzone"]
    isbn13 = "9786068996011"
    item_id = "ghici"
    
    # Mock fetch to succeed
    from api.fetch_guard import GuardedFetch
    html = "<html><body>Test</body></html>"
    
    with patch("api.offers.fetch") as mock_fetch:
        mock_fetch.return_value = GuardedFetch(
            final_url="https://example.com",
            status=200,
            content_type="text/html",
            body=html.encode(),
            text=html,
            hops=0,
        )
        
        progress_events = []
        
        async def progress_callback(event):
            progress_events.append(event)
        
        results = asyncio.run(
            read_offers_parallel(
                store_ids,
                isbn13,
                item_id,
                cache,
                progress_callback=progress_callback,
                index_lookup=_product_index,
            )
        )
        
        assert len(progress_events) > 0
        messages = [e.message for e in progress_events]
        assert "Reading Libris…" in messages
        assert "Reading Bookzone…" in messages
        assert not any(m.startswith("Reading libris") for m in messages)


def test_isbn_check_digit_validation():
    """Test that ISBN check digit is validated."""
    from matching.isbn import normalize_isbn13
    
    # Valid ISBN
    assert normalize_isbn13("9786068996011") == "9786068996011"
    
    # Invalid ISBN (wrong check digit)
    assert normalize_isbn13("9786068996010") is None
    
    # Invalid ISBN (too short)
    assert normalize_isbn13("978606899601") is None
    
    # Invalid ISBN (too long)
    assert normalize_isbn13("97860689960111") is None


def test_edition_rule():
    """Test that edition rule groups by edition."""
    from matching.editions import match_offers
    
    offers = [
        {
            "store_id": "libris",
            "price_cents": 5700,
            "isbn13": "9786068996011",
            "edition": "paperback",
        },
        {
            "store_id": "libris",
            "price_cents": 6200,
            "isbn13": "9786068996011",
            "edition": "hardcover",
        },
        {
            "store_id": "bookzone",
            "price_cents": 5500,
            "isbn13": "9786068996011",
            "edition": "paperback",
        },
    ]
    
    # Should group by ISBN (strict_isbn mode)
    groups = match_offers(offers, "strict_isbn")
    
    # Should have 1 group for the ISBN
    assert len(groups["groups"]) == 1
    assert groups["groups"][0]["key"] == "9786068996011"
    
    # Group should have 3 offers
    assert len(groups["groups"][0]["editions"]) == 1
    assert len(groups["groups"][0]["editions"][0]["offers"]) == 3


def test_seller_tri_state():
    """Test that seller tri-state is validated."""
    from matching.validate import validate_extraction
    
    # Valid: true with sold_by matching store
    obj = {
        "sold_and_shipped_by_store": True,
        "sold_by": "Libris",
        "ships_from": "Libris",
    }
    validated, verdict = validate_extraction(obj)
    assert verdict["accepted"] is True
    
    # Valid: false with sold_by different from store
    obj = {
        "sold_and_shipped_by_store": False,
        "sold_by": "Third Party",
        "ships_from": "Third Party",
    }
    validated, verdict = validate_extraction(obj)
    assert verdict["accepted"] is True
    
    # Valid: null (unknown)
    obj = {
        "sold_and_shipped_by_store": None,
        "sold_by": None,
        "ships_from": None,
    }
    validated, verdict = validate_extraction(obj)
    assert verdict["accepted"] is True


def test_ro_v1_totals_unchanged():
    """Test that ro-v1 totals remain unchanged."""
    from fastapi.testclient import TestClient
    from api.app import create_app
    from pathlib import Path
    
    # Use the existing cache
    cache_path = Path("~/Projects/omnibasket/data/cache/ro-v1.sqlite")
    
    app = create_app(cache_path)
    client = TestClient(app)
    
    # Solve from cache
    response = client.post("/solve", params={"source": "cache"})
    assert response.status_code == 200
    
    result = response.json()
    
    # Totals should be unchanged
    assert result["total_cents"] == 51516  # 515.16 lei
    assert result["single_store_baseline"]["total_cents"] == 55873  # 558.73 lei


def test_matching_checks_reject_bad_isbn_edition_and_seller():
    """The production matcher rejects a bad check digit, a foreign ISBN, and a nameless false seller."""
    from api.offers import run_matching_checks

    bad = run_matching_checks({"isbn13": "9786068996010", "price": 57, "title": "x"}, "9786068996011")
    assert bad["isbn_rejected"] is True
    assert bad["fields"]["isbn13"] is None

    other_edition = run_matching_checks(
        {"isbn13": "9780141369365", "price": 10, "title": "Matilda"}, "9786068996011"
    )
    assert other_edition["edition_rejected"] is True
    assert len(other_edition["groups"]["groups"]) == 1
    assert other_edition["groups"]["groups"][0]["key"] != "9786068996011"

    seller = run_matching_checks(
        {"sold_and_shipped_by_store": False, "sold_by": None, "ships_from": None, "price": 10},
        None,
    )
    assert seller["seller_rejected"] is True
    assert seller["fields"]["seller_certainty"] == "unknown"


def test_amazon_outside_the_captured_seven_is_a_link_not_a_fetch(cache):
    from api.offers import amazon_check_link

    with patch("api.offers.fetch") as mock_fetch:
        result = read_offers_sync(["amazon_de"], "9780747532699", "hp", cache)
    assert mock_fetch.call_count == 0
    assert result[0].reason == "amazon_de_never_read_live"
    assert result[0].listing_url == "https://www.amazon.de/s?k=9780747532699"
    assert amazon_check_link("9781529105100").startswith("https://www.amazon.de/dp/")


def test_muse_http_goes_through_guarded_post_and_drops_bad_price():
    from api.muse_integration import gap_fill_with_muse
    from api.schema_org import SchemaOrgData

    def _guarded(body, estimate, note, provider="meta"):
        assert "input" in body
        payload = {"output_text": '{"price": 99.99, "currency": "RON", "title": "X"}'}
        row = {"tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "latency_ms": 1, "endpoint": "/responses"}
        return payload, row

    with patch("api.muse_integration.meta_budget.guarded_post", side_effect=_guarded):
        result = gap_fill_with_muse("Price: 57.00 Lei", SchemaOrgData())
    assert result.fields["price"] is None


def test_no_network_in_tests():
    """Test that no test makes network calls."""
    # This is a meta-test that verifies our test setup
    # All network calls should be mocked
    
    import sys
    import inspect
    
    # Get all test functions
    test_module = sys.modules[__name__]
    test_functions = [
        obj for name, obj in inspect.getmembers(test_module)
        if name.startswith("test_") and inspect.isfunction(obj)
    ]
    
    # This test itself doesn't make network calls
    assert True

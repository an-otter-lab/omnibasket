"""Test that non-indexed shops return not_checked instead of skipped."""
import asyncio
from pathlib import Path
from unittest.mock import patch

from api.offers import read_offers_parallel, shop_is_indexed
from api.cache import PageCache


def test_shop_is_indexed(indexed_shops_db):
    """Verify which shops are indexed in the database."""
    assert shop_is_indexed("libris") is True
    assert shop_is_indexed("books_express") is True
    assert shop_is_indexed("bookzone") is False
    assert shop_is_indexed("emag") is False


def test_non_indexed_shops_return_not_checked(tmp_path, indexed_shops_db):
    """Non-indexed shops (bookzone, emag) must return not_checked, not skipped."""
    cache = PageCache(tmp_path / "cache.sqlite")
    
    # Mock fetch to avoid real network calls
    def mock_fetch(url, timeout=None):
        class MockResponse:
            text = '<html><body>No match</body></html>'
            status_code = 200
        return MockResponse()
    
    isbn = "9789735832940"  # Harry Potter RO
    
    with patch('api.offers.fetch', side_effect=mock_fetch):
        offers = asyncio.run(read_offers_parallel(
            ['bookzone', 'emag', 'books_express'],
            isbn,
            f"book-{isbn}",
            cache,
            title="Harry Potter",
            author="J.K. Rowling"
        ))
    
    # Find offers by store_id
    bookzone_offer = next((o for o in offers if o.store_id == 'bookzone'), None)
    emag_offer = next((o for o in offers if o.store_id == 'emag'), None)
    books_express_offer = next((o for o in offers if o.store_id == 'books_express'), None)
    
    # Non-indexed shops must return not_checked
    assert bookzone_offer is not None
    assert bookzone_offer.status == "not_checked"
    assert bookzone_offer.reason == "not_indexed"
    
    assert emag_offer is not None
    assert emag_offer.status == "not_checked"
    assert emag_offer.reason == "not_indexed"
    
    # Indexed shop was actually read (even if no offer found)
    assert books_express_offer is not None
    assert books_express_offer.status != "not_checked"
    # It should be skipped (no match) or failed, but not not_checked


def test_indexed_shop_with_no_match_returns_skipped(tmp_path, indexed_shops_db):
    """Indexed shops that were read but found no match return skipped, not not_checked."""
    cache = PageCache(tmp_path / "cache.sqlite")
    
    def mock_fetch(url, timeout=None):
        class MockResponse:
            text = '<html><body>No match</body></html>'
            status_code = 200
        return MockResponse()
    
    isbn = "9789735832940"
    
    with patch('api.offers.fetch', side_effect=mock_fetch):
        offers = asyncio.run(read_offers_parallel(
            ['books_express'],  # Indexed shop
            isbn,
            f"book-{isbn}",
            cache
        ))
    
    books_express_offer = next((o for o in offers if o.store_id == 'books_express'), None)
    assert books_express_offer is not None
    # Should be skipped (was read, no match), not not_checked
    assert books_express_offer.status == "skipped"
    assert books_express_offer.reason == "no_match_in_index"

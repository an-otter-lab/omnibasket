"""S3: a second read the same day (a cache hit) keeps the shop link, the read time and in-stock."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from api.cache import PageCache
from api.fetch_guard import GuardedFetch
from api.offers import read_offers_sync

ISBN = "9786068996011"
URL = "https://www.libris.ro/carte/ghici/21197307"
PAGE = (
    '<html><head><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Book","name":"Ghici","isbn":"' + ISBN + '",'
    '"offers":{"@type":"Offer","price":"57.00","priceCurrency":"RON",'
    '"availability":"https://schema.org/InStock"}}'
    "</script></head><body>Ghici 57.00 lei</body></html>"
)


@pytest.fixture
def cache(tmp_path):
    return PageCache(tmp_path / "s3_cache.sqlite")


def _index(store_id, isbn):
    return URL if store_id == "libris" else None


def _today():
    return datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d")


def test_second_read_same_day_keeps_link_and_read_time(cache, indexed_shops_db):
    seen = []

    def _fetch(url):
        seen.append(url)
        return GuardedFetch(url, 200, "text/html", PAGE.encode(), PAGE, 0)

    with patch("api.offers.fetch", side_effect=_fetch):
        first = read_offers_sync(["libris"], ISBN, "ghici", cache, index_lookup=_index)[0]
        second = read_offers_sync(["libris"], ISBN, "ghici", cache, index_lookup=_index)[0]

    assert seen == [URL]
    assert first.cache == "live" and first.status == "ok"
    assert second.cache == "hit" and second.status == "ok"
    assert second.listing_url == first.listing_url == URL
    assert second.read_at is not None and second.read_at == first.read_at
    assert second.in_stock is True and second.in_stock == first.in_stock
    assert second.price_cents == first.price_cents == 5700


def test_seed_row_link_comes_from_final_url(cache):
    """Seed rows keep the link under provenance.meta.final_url."""
    cache.put({
        "store_id": "libris", "isbn13": ISBN, "item_id": "ghici", "day": _today(),
        "page_text": PAGE, "screenshot_path": None, "model_json": None,
        "provenance": {"source": "seed", "read_at": "2026-10-31T09:00:00+02:00", "meta": {"final_url": URL}},
    })
    with patch("api.offers.fetch", side_effect=AssertionError("no fetch on a hit")):
        hit = read_offers_sync(["libris"], ISBN, "ghici", cache, index_lookup=_index)[0]
    assert hit.cache == "hit"
    assert hit.listing_url == URL
    assert hit.read_at == "2026-10-31T09:00:00+02:00"
    assert hit.in_stock is True


def test_out_of_stock_page_reads_false_on_a_hit(cache):
    page = PAGE.replace("InStock", "OutOfStock")
    cache.put({
        "store_id": "libris", "isbn13": ISBN, "item_id": "ghici", "day": _today(),
        "page_text": page, "screenshot_path": None, "model_json": None,
        "provenance": {"source": "live_read", "url": URL, "read_at": "2026-10-31T10:00:00+02:00"},
    })
    with patch("api.offers.fetch", side_effect=AssertionError("no fetch on a hit")):
        hit = read_offers_sync(["libris"], ISBN, "ghici", cache, index_lookup=_index)[0]
    assert hit.in_stock is False
    assert hit.listing_url == URL

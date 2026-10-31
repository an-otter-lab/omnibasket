"""S4: a product barcode (642... GS1 code) is never attached as another printing's ISBN."""

import asyncio
import json
from unittest.mock import patch

import pytest

from api.cache import PageCache
from api.fetch_guard import GuardedFetch
from api.offers import _book_isbn, read_offers_parallel

CHOSEN_ISBN = "9789734707751"
BARCODE = "6426092301278"
URL = "https://www.libris.ro/micul-print/12345"
TITLE = "Micul prinț"
AUTHOR = "Antoine de Saint-Exupéry"


def page(**ids):
    item = {"@type": ["Product", "Book"], "name": "Micul print - Antoine de Saint-Exupery",
            "author": [{"@type": "Person", "name": "Antoine de Saint-Exupery"}],
            "offers": {"@type": "Offer", "price": "11.00", "priceCurrency": "RON",
                       "availability": "https://schema.org/InStock"}, **ids}
    html = ('<html><script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": [item]}) + "</script></html>")
    return GuardedFetch(final_url=URL, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)


@pytest.fixture
def cache(tmp_path):
    return PageCache(tmp_path / "c.sqlite")


def run(cache):
    return asyncio.run(read_offers_parallel(
        ["libris"], CHOSEN_ISBN, "micul-print", cache, index_lookup=lambda s, i: None,
        title=TITLE, author=AUTHOR, title_lookup=lambda s, t, a: URL))


@pytest.mark.parametrize("ids", [{"gtin13": BARCODE, "isbn": BARCODE}, {"isbn": BARCODE}, {"gtin13": BARCODE}])
def test_barcode_page_is_not_attached(cache, ids):
    with patch("api.offers.fetch", return_value=page(**ids)) as f:
        first = run(cache)[0]
        second = run(cache)[0]
    # S4b: a barcode is never an ISBN-13, so a page whose "isbn" is a barcode is a page with no isbn,
    # and like the gtin13-only page it is read again rather than remembered (as before S4).
    assert f.call_count == 2
    for got in (first, second):
        assert got.status != "ok"
        assert got.price_cents is None
        assert not got.other_printing
        assert got.isbn13 == CHOSEN_ISBN


def test_old_confirmation_with_a_barcode_is_ignored(cache):
    from api.title_match import MATCHER_VERSION
    key = "|".join(["printing", str(MATCHER_VERSION), "libris", CHOSEN_ISBN, TITLE.lower(), AUTHOR.lower()])
    cache.put_confirmation(key, {"matched": True, "url": URL, "isbn13": BARCODE, "price_cents": 1100,
                                 "currency": "RON", "availability": "InStock", "name": "x", "authors": []})
    with patch("api.offers.fetch", side_effect=AssertionError("no fetch")):
        got = run(cache)[0]
    assert got.status == "skipped" and got.price_cents is None and not got.other_printing


def test_a_real_isbn_still_attaches(cache):
    with patch("api.offers.fetch", return_value=page(isbn="9786063353734")):
        got = run(cache)[0]
    assert got.status == "ok" and got.other_printing and got.isbn13 == "9786063353734" and got.price_cents == 1100


def test_book_isbn():
    assert _book_isbn("978-606-33-5373-4") == "9786063353734"
    assert _book_isbn(BARCODE) is None
    assert _book_isbn("9786063353735") is None
    assert _book_isbn(None) is None

"""A shop page that declares another ISBN of the same work is shown as another printing."""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from api.cache import PageCache
from api.fetch_guard import GuardedFetch
from api.offers import live_offer_row, read_offers_parallel
from api.title_match import strong_match

CHOSEN_ISBN = "9789735832940"
PAGE_ISBN = "9786303218243"
URL = "https://www.libris.ro/carte/harry-potter-si-piatra-filosofala-j-k-rowling/42440447"
TITLE = "Harry Potter și piatra filozofală"
AUTHOR = "J. K. Rowling"


def page(name, isbn, author="J.K. Rowling", price="56.62"):
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": ["Product", "Book"], "name": name, "isbn": isbn,
             "author": [{"@type": "Person", "name": author}],
             "offers": {"@type": "Offer", "price": price, "priceCurrency": "RON",
                        "availability": "https://schema.org/InStock"}},
        ],
    }
    html = '<html><script type="application/ld+json">' + json.dumps(ld) + "</script></html>"
    return GuardedFetch(final_url=URL, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)


@pytest.fixture
def cache(tmp_path):
    return PageCache(tmp_path / "c.sqlite")


def run(cache, isbn, index_lookup, title_lookup):
    return asyncio.run(read_offers_parallel(
        ["libris"], isbn, "book-x", cache, index_lookup=index_lookup,
        title=TITLE, author=AUTHOR, title_lookup=title_lookup))


def test_same_isbn_stays_strict_and_cached(cache):
    with patch("api.offers.fetch", return_value=page("Harry Potter si piatra filosofala - J.K. Rowling", PAGE_ISBN)) as f:
        first = run(cache, PAGE_ISBN, lambda s, i: URL, lambda *a: pytest.fail("title path must not run"))
        second = run(cache, PAGE_ISBN, lambda s, i: URL, lambda *a: pytest.fail("title path must not run"))
    assert f.call_count == 1
    assert first[0].status == "ok" and first[0].price_cents == 5662 and not first[0].other_printing
    assert second[0].cache == "hit" and not second[0].other_printing


def test_different_isbn_same_work_attaches_with_note(cache):
    with patch("api.offers.fetch", return_value=page("Harry Potter si piatra filosofala - J.K. Rowling", PAGE_ISBN)) as f:
        got = run(cache, CHOSEN_ISBN, lambda s, i: None, lambda s, t, a: URL)
    assert f.call_count == 1
    offer = got[0]
    assert offer.status == "ok" and offer.price_cents == 5662 and offer.other_printing
    assert offer.isbn13 == PAGE_ISBN and offer.listing_url == URL
    row = live_offer_row(offer, {"libris"}, set())
    assert row["other_printing"] is True and row["isbn13"] == PAGE_ISBN and row["price_cents"] == 5662


def test_different_book_with_similar_title_does_not_match(cache):
    with patch("api.offers.fetch", return_value=page("Harry Potter si camera secretelor - J.K. Rowling", PAGE_ISBN)):
        got = run(cache, CHOSEN_ISBN, lambda s, i: None, lambda s, t, a: URL)
    assert got[0].status == "skipped" and got[0].price_cents is None and not got[0].other_printing


def test_strong_match_rules():
    ok = ("Harry Potter si piatra filosofala - J.K. Rowling", ["J.K. Rowling"])
    assert strong_match(TITLE, AUTHOR, *ok)
    assert not strong_match(TITLE, AUTHOR, "Harry Potter si piatra filosofala - J.K. Rowling", ["Alt Autor"])
    assert not strong_match(TITLE, AUTHOR, "Harry Potter si camera secretelor", ["J.K. Rowling"])
    assert not strong_match(TITLE, AUTHOR, "Harry Potter si piatra filosofala 2", ["J.K. Rowling"])
    assert not strong_match(TITLE, None, *ok)


def test_note_text_exists_in_ro_and_en():
    src = (Path(__file__).resolve().parents[1] / "ui" / "src" / "app" / "messages.ts").read_text()
    found = dict(re.findall(r"readsOtherPrinting: '([^']+)'", src) and [(("ro" if "tipărire" in m else "en"), m) for m in re.findall(r"readsOtherPrinting: '([^']+)'", src)])
    assert found["en"] == "{shop}: other printing, ISBN {isbn}"
    assert found["ro"] == "{shop}: altă tipărire, ISBN {isbn}"

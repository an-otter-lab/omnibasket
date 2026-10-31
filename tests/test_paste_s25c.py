"""S25c (Adrian, 1 Nov): a pasted page is read only for the shops we read (Books-Express, eMAG,
Bookzone, Libris), exactly once. A link to any other site, foreign ones included, uses the ISBN in
its address and is never fetched. Amazon is never read. Fixture pages only; no sockets."""

import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import input_understanding as iu
from api.app import create_app
from api.fetch_guard import GuardedFetch
from api.rate_limit import DailyPasteLimiter

MUSE = "api.muse_integration.meta_budget.guarded_post"
ISBN = "9780142402535"  # Matilda (Puffin)
UNKNOWN = "9780141365466"  # a valid ISBN-13 that is not in this index

FOREIGN = [
    "https://www.amazon.co.uk/Matilda-Roald-Dahl/dp/0142402532",  # not amazon.de
    "https://www.waterstones.com/book/matilda/roald-dahl/" + ISBN,
    "https://www.goodreads.com/book/isbn/" + ISBN,
    "https://carturesti.ro/carte/matilda-" + ISBN,
    "https://www.thalia.de/shop/home/artikeldetails/" + ISBN,
]


@pytest.fixture
def index_db(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.execute("INSERT INTO books VALUES('libris','https://www.libris.ro/matilda','Matilda','Roald Dahl',?,'2026-10-30')", (ISBN,))
    return path


class Reads:
    def __init__(self):
        self.urls = []

    def __call__(self, url, **k):
        self.urls.append(url)
        ld = {"@context": "https://schema.org", "@type": "Book", "isbn": ISBN, "name": "Matilda",
              "author": {"@type": "Person", "name": "Roald Dahl"},
              "offers": {"@type": "Offer", "price": "39.00", "priceCurrency": "RON"}}
        html = '<html><script type="application/ld+json">' + json.dumps(ld) + "</script></html>"
        return GuardedFetch(final_url=url, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)


def _no_muse(*a, **k):
    raise AssertionError("no model call expected")


@pytest.mark.parametrize("url", FOREIGN)
def test_foreign_or_other_site_link_makes_zero_fetches(url, index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand(url, index_db=index_db)
    assert reads.urls == []
    assert out["status"] == "resolved" and out["isbn13"] == ISBN
    assert out["structured_query"]["title"] == "Matilda"
    assert out["shop_context"] == {"shop_id": None, "product_url": None} and out["paste_offer"] is None


def test_other_site_isbn_not_in_the_index_is_not_found_without_a_read(index_db):
    # The UI then searches the ISBN from the address (the S25b fallback).
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand("https://www.waterstones.com/book/x/" + UNKNOWN, index_db=index_db)
    assert reads.urls == [] and out["status"] == "not_found" and out["isbn13"] is None


def test_other_site_link_without_isbn_is_not_read(index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand("https://blog.example/our-favourite-reads", index_db=index_db)
    assert reads.urls == [] and out["status"] == "not_found" and out["message"] == iu.NO_BOOK_MESSAGE


@pytest.mark.parametrize("url", [
    "https://www.books-express.ro/matilda/p/x," + ISBN,
    "https://www.emag.ro/carte-matilda-" + ISBN + "/pd/ABC/",
    "https://bookzone.ro/produs/matilda",
    "https://www.libris.ro/matilda",
])
def test_the_four_shops_we_read_are_read_exactly_once(url, index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand(url, index_db=index_db)
    assert reads.urls == [url]
    assert out["status"] == "resolved" and out["isbn13"] == ISBN


def test_amazon_de_is_never_read(index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand("https://www.amazon.de/dp/0142402532", index_db=index_db)
    assert reads.urls == [] and out["isbn13"] == ISBN


def test_paste_limit_counts_shop_reads_not_unread_links(tmp_path, index_db):
    app = create_app(tmp_path / "pages.sqlite")
    app.state.index_db_path = index_db
    app.state.paste_limiter = DailyPasteLimiter(pastes_per_day=1, new_domains_per_day=5, today=lambda: 1)
    client = TestClient(app)
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        for url in FOREIGN:  # never read, so never limited
            assert client.post("/input", json={"raw_input": url}).status_code == 200
        assert client.post("/input", json={"raw_input": "https://www.libris.ro/matilda"}).status_code == 200
        tripped = client.post("/input", json={"raw_input": "https://bookzone.ro/produs/matilda"})
    assert tripped.status_code == 429 and tripped.json()["error"] == "paste_limit"
    assert reads.urls == ["https://www.libris.ro/matilda"]

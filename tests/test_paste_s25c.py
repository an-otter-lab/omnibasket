"""S25c (Adrian, 1 Nov): a pasted page is read only for the shops we read (eMAG, Bookzone, Libris,
and Elefant since 3 Nov), exactly once. A link to any other site, foreign ones included, uses the ISBN in
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
    # Not named here: the UI searches the ISBN in the address, exactly as for a typed ISBN.
    assert reads.urls == []
    assert out["status"] == "not_found" and out["isbn13"] is None and out["paste_offer"] is None


def test_other_site_link_without_isbn_is_not_read(index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand("https://blog.example/our-favourite-reads", index_db=index_db)
    assert reads.urls == [] and out["status"] == "not_found" and out["message"] == iu.NO_BOOK_MESSAGE


@pytest.mark.parametrize("url", [
    "https://www.emag.ro/carte-matilda-" + ISBN + "/pd/ABC/",
    "https://bookzone.ro/produs/matilda",
    "https://www.libris.ro/matilda",
])
def test_the_shops_we_read_are_read_exactly_once(url, index_db):
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand(url, index_db=index_db)
    assert reads.urls == [url]
    assert out["status"] == "resolved" and out["isbn13"] == ISBN


def test_retired_books_express_link_is_an_other_site_link(index_db):
    """Books-Express is retired (3 Nov): its link is never fetched and, like any other site's, leaves
    the UI to search the ISBN in its address."""
    reads = Reads()
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", reads):
        out = iu.understand("https://www.books-express.ro/matilda/p/x," + ISBN, index_db=index_db)
    assert reads.urls == [] and out["status"] == "not_found" and out["isbn13"] is None


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

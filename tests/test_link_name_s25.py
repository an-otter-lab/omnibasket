"""S25: a pasted shop link names the book from the page's schema.org name and author,
not from the index's search key. Fixtures and mocks only; no sockets."""

import json
import sqlite3
from unittest.mock import patch

import pytest

from api import input_understanding as iu
from api.fetch_guard import GuardedFetch

MUSE = "api.muse_integration.meta_budget.guarded_post"
URL = "https://www.libris.ro/carte/degetul-magic-roald-dahl/44809023"
ISBN = "9786063330001"


@pytest.fixture
def index_db(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        # As in the real index: Libris rows carry a normalised search key and no ISBN.
        db.execute("INSERT INTO books VALUES('libris',?,'degetul magic roald dahl',NULL,NULL,'2026-10-30')", (URL,))
    return path


def _no_muse(*a, **k):
    raise AssertionError("no model call expected")


def _page(book: dict):
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Libris"},
        {"@type": ["Product", "Book"], "isbn": ISBN, **book,
         "offers": {"@type": "Offer", "price": "29.90", "priceCurrency": "RON"}}]}
    html = '<html><script type="application/ld+json">' + json.dumps(ld) + "</script><body>x</body></html>"
    return lambda url, **k: GuardedFetch(final_url=url, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)


def test_libris_link_named_by_schema_name_and_author(index_db):
    seen = []
    page = _page({"name": "Degetul magic", "author": [{"@type": "Person", "name": "Roald Dahl"}]})

    def one_read(url, **k):
        seen.append(url)
        return page(url)

    with patch(MUSE, _no_muse), patch.object(iu, "fetch", one_read):
        out = iu.understand(URL, index_db=index_db)
    assert seen == [URL]  # still exactly one guarded read
    assert out["status"] == "resolved" and out["isbn13"] == ISBN
    assert out["structured_query"]["title"] == "Degetul magic"
    assert out["structured_query"]["author"] == "Roald Dahl"
    assert out["shop_context"] == {"shop_id": "libris", "product_url": URL}


def test_author_as_plain_string(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _page({"name": "Degetul magic", "author": "Roald Dahl"})):
        q = iu.understand(URL, index_db=index_db)["structured_query"]
    assert (q["title"], q["author"]) == ("Degetul magic", "Roald Dahl")


def test_page_without_a_name_keeps_the_index_title(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _page({})):
        q = iu.understand(URL, index_db=index_db)["structured_query"]
    assert q["title"] == "degetul magic roald dahl" and q["author"] is None

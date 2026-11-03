"""S25b: a pasted shop link (any indexed shop but Amazon) is named from its page's schema.org name
and author, with exactly one page read. Fixture pages only; no sockets. (Books-Express was the example
until it was retired on 3 Nov; eMAG has the same shape.)"""

import json
import sqlite3
from unittest.mock import patch

import pytest

from api import input_understanding as iu
from api.fetch_guard import FetchRefused, GuardedFetch

MUSE = "api.muse_integration.meta_budget.guarded_post"
ISBN = "9780141365466"  # Matilda (Puffin), any valid ISBN-13 works here
OTHER = "9780142410387"
EMAG_URL = "https://www.emag.ro/carte-matilda-" + ISBN + "/pd/ABC/"
EMAG_INDEXED = "https://www.emag.ro/carte-indexed/pd/XYZ/"  # no ISBN in the address: the index has it


@pytest.fixture
def index_db(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        # As in the real index, a shop row's title can be a junk key.
        db.execute("INSERT INTO books VALUES('emag',?,'scjb,',NULL,?,'2026-10-30')", (EMAG_INDEXED, ISBN))
    return path


def _no_muse(*a, **k):
    raise AssertionError("no model call expected")


def _reader(seen, book=None, isbn=ISBN):
    ld = {"@context": "https://schema.org", "@type": ["Product", "Book"], "isbn": isbn,
          "offers": {"@type": "Offer", "price": "39.00", "priceCurrency": "RON"}, **(book or {})}
    html = '<html><script type="application/ld+json">' + json.dumps(ld) + "</script><body>x</body></html>"

    def read(url, **k):
        seen.append(url)
        return GuardedFetch(final_url=url, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)

    return read


DAHL = {"name": "Matilda", "author": {"@type": "Person", "name": "Roald Dahl"}}


@pytest.mark.parametrize("url,shop", [(EMAG_INDEXED, "emag"), (EMAG_URL, "emag")])
def test_shop_link_named_from_its_page_with_one_read(index_db, url, shop):
    seen = []
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _reader(seen, DAHL)):
        out = iu.understand(url, index_db=index_db)
    assert seen == [url]  # exactly one read, the ISBN in the URL or the index does not add a second
    assert out["status"] == "resolved" and out["isbn13"] == ISBN
    assert (out["structured_query"]["title"], out["structured_query"]["author"]) == ("Matilda", "Roald Dahl")
    assert out["shop_context"] == {"shop_id": shop, "product_url": url}


def test_refused_read_with_a_known_isbn_still_resolves(index_db):
    seen = []

    def refused(url, **k):
        seen.append(url)
        raise FetchRefused("blocked")

    with patch(MUSE, _no_muse), patch.object(iu, "fetch", refused):
        out = iu.understand(EMAG_INDEXED, index_db=index_db)
    assert seen == [EMAG_INDEXED]  # one attempt, no retry
    assert out["status"] == "resolved" and out["isbn13"] == ISBN


def test_page_about_another_isbn_does_not_name_the_book(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _reader([], DAHL, isbn=OTHER)):
        out = iu.understand(EMAG_URL, index_db=index_db)
    assert out["isbn13"] == ISBN and out["structured_query"]["title"] != "Matilda"


def test_amazon_is_still_never_read(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_muse):
        out = iu.understand("https://www.amazon.de/Matilda/dp/0141365463/ref=x", index_db=index_db)
    assert out["isbn13"] == ISBN and out["shop_context"]["shop_id"] == "amazon_de"


@pytest.mark.parametrize("book,want", [
    # Libris names its pages "Title - Authors" and lists the illustrator as author (3 Nov walk:
    # the chip read "Gruffalo - Julia Donalson, Axel Scheffler · Axel Scheffler").
    ({"name": "Gruffalo - Julia Donalson, Axel Scheffler", "author": [{"@type": "Person", "name": "Axel Scheffler"}]},
     ("Gruffalo", "Axel Scheffler")),
    ({"name": "Matilda - Roald Dahl", "author": {"@type": "Person", "name": "Roald Dahl"}}, ("Matilda", "Roald Dahl")),
    # A subtitle after a dash is not an author: it stays.
    ({"name": "Matilda - The Musical", "author": "Roald Dahl"}, ("Matilda - The Musical", "Roald Dahl")),
    # No author on the page: the name is left as it is.
    ({"name": "Matilda - Roald Dahl"}, ("Matilda - Roald Dahl", None)),
])
def test_pasted_title_drops_a_trailing_author(index_db, book, want):
    seen = []
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _reader(seen, book)):
        out = iu.understand(EMAG_URL, index_db=index_db)
    assert (out["structured_query"]["title"], out["structured_query"]["author"]) == want

"""S7: the limit never changes which book comes first (rank every doc, then cut)."""
import json
import sqlite3

import pytest

from index import search as search_module
from tests.test_search_ranking import Catalogue, MATILDA, MICUL, HARRY_POTTER


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)


def _no_shop_reads(url, timeout=None):
    raise AssertionError("no shop page is read in this test: " + url)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
                   "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)", ("books-express", "https://www.books-express.ro/-/p/9780142410370",
                   "matilda", "Roald Dahl", "9780142410370", "2026-10-30"))
    return path


class Shuffled:
    """Open Library's order puts four records with no ISBN (nothing to price) before Dahl's Matilda."""

    def __init__(self):
        self.docs = [{"key": f"/works/OL{i}W", "title": t, "author_name": [a]} for i, (t, a) in enumerate([
            ("Matilda", "Betty Neels"), ("Matilda's Secret", "A. Writer"), ("Waltzing Matilda", "B. Writer"),
            ("Matilda Bone", "Karen Cushman")])]
        self.docs.append({"key": "/works/OL45883W", "title": "Matilda", "author_name": ["Roald Dahl"],
                          "isbn": ["9780142410370"], "edition_count": 120})
        self.docs += [{"key": f"/works/OL9{i}W", "title": f"Matilda {i}", "author_name": ["C. Writer"]} for i in range(5)]

    def __call__(self, req, timeout=None):
        body = json.dumps({"docs": self.docs if "/search" in req.full_url else {}}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return body

        return Response()


def _search(db_path, q, limit, opener):
    return search_module.search(q, limit=limit, db_path=db_path, opener=opener, fetcher=_no_shop_reads)


def test_top_result_is_the_same_for_limits_3_5_and_10(db_path):
    tops = {n: _search(db_path, "Matilda", n, Shuffled()) for n in (3, 5, 10)}
    assert [tops[n][0]["isbn"] for n in (3, 5, 10)] == ["9780142410370"] * 3
    assert tops[3][0]["author"] == "Roald Dahl"


def test_a_smaller_limit_is_a_prefix_of_a_larger_one(db_path):
    for q, opener in (("Matilda", Shuffled), (MATILDA, Catalogue), (MICUL, Catalogue), (HARRY_POTTER, Catalogue)):
        full = [(r["title"], r["isbn"]) for r in _search(db_path, q, 10, opener())]
        for n in (3, 5):
            got = [(r["title"], r["isbn"]) for r in _search(db_path, q, n, opener())]
            assert got == full[:n], (q, n)

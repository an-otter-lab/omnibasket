"""Photo lines the local index does not hold resolve through the Open Library search path.

The image read is stubbed; the resolver is the real one with Open Library as a stand-in opener.
"""
import io
import json
import sqlite3

import pytest

from api import photo_read
from index import search as search_module

LINES = [
    {"title": "Harry Potter și piatra filozofală", "author": "J. K. Rowling"},
    {"title": "Micul Prinț", "author": "Antoine de Saint-Exupéry"},
    {"title": "The Clean Coder", "author": "Robert C. Martin"},
]

DOCS = {
    "harry potter si piatra filozofala": [
        {"title": "Harry Potter si piatra filozofala", "author_name": ["J. K. Rowling"],
         "isbn": ["9789735832940"], "cover_i": 1},
        {"title": "Harry Potter si camera secretelor", "author_name": ["J. K. Rowling"],
         "isbn": ["9789735833329"]},
    ],
    "micul print": [
        {"title": "Micul prinț (Cu explicații pentru copii și recenzie pentru adulți)",
         "author_name": ["Antoine de Saint-Exupéry"], "isbn": ["9786060339229"]},
        {"title": "Zborul de noapte", "author_name": ["Antoine de Saint-Exupéry"], "isbn": ["9786060000001"]},
    ],
    "the clean coder": [
        {"title": "The clean coder", "author_name": ["Robert C. Martin"], "isbn": ["9780137081073"]},
        {"title": "Clean Code", "author_name": ["Robert C. Martin"], "isbn": ["9780132350884"]},
    ],
}


class FakeOL:
    def __call__(self, req, timeout=None):
        from urllib.parse import parse_qs, urlparse

        url = urlparse(req.full_url)
        q = parse_qs(url.query).get("q", [""])[0]
        key = " ".join(search_module.normalize(q).split())
        docs = []
        for k, v in DOCS.items():
            if key == k or key.startswith(k + " "):
                docs = v
        body = json.dumps({"docs": docs}).encode()

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(body)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0, raising=False)
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        c.execute("INSERT INTO books VALUES('books-express','https://be/1','The clean coder','Robert C. Martin','9780137081073','2026-10-30')")
    return path


def test_three_fixture_lines_become_pickable_books(db):
    out = [photo_read.match_line(l, db, opener=FakeOL()) for l in LINES]
    assert [o["status"] for o in out] == ["matched", "matched", "matched"]
    assert [o["candidate"]["isbn"] for o in out] == ["9789735832940", "9786060339229", "9780137081073"]
    assert all(o["candidate"]["cover_url"] for o in out)


def test_unrelated_line_stays_not_found(db):
    out = photo_read.match_line({"title": "Cartea inexistenta", "author": None}, db, opener=FakeOL())
    assert out["status"] == "not_found"


def test_unreachable_search_is_honest_not_found(db):
    def down(req, timeout=None):
        raise OSError("offline")
    out = photo_read.match_line(LINES[1], db, opener=down)
    assert out["status"] == "not_found"


def test_wrong_author_is_not_a_candidate(db):
    out = photo_read.match_line({"title": "Zborul de noapte", "author": "Altcineva"}, db, opener=FakeOL())
    assert out["status"] == "not_found"

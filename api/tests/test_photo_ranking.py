"""R13: a photo line matched in the index is shown with the catalogue's title and author.

The index holds Books-Express slugs ("owl babies big book", "matilda", no author). What
the shopper is buying has a real title and an author, so a matched line is labelled from
the same Open Library record and ranking the typed search uses. The edition label stays.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from api import photo_read
from index import search as search_module

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "openlibrary"
DOCS = json.loads((FIXTURES / "isbn-records.json").read_text(encoding="utf-8"))["docs"]
BY_ISBN = {search_module.to_isbn13(i): doc for doc in DOCS for i in doc.get("isbn") or []
           if search_module.to_isbn13(i)}


class Catalogue:
    """The stand-in opener: the captured record for the ISBN the index matched."""

    def __call__(self, req, timeout=None):
        from urllib.parse import parse_qs, urlsplit

        q = " ".join(search_module.normalize(parse_qs(urlsplit(req.full_url).query).get("q", [""])[0]).split())
        doc = BY_ISBN.get(q)
        body = json.dumps({"docs": [doc] if doc else []}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return body

        return Response()


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
                   "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [
            ("books-express", "https://www.books-express.ro/owl-babies-big-book/p/x,9780763612832",
             "owl babies big book", None, "9780763612832", "2026-10-30"),
            ("books-express", "https://www.books-express.ro/-/p/9780142410370",
             "matilda", None, "9780142410370", "2026-10-30"),
        ])
    return path


def test_ranking_photo_matched_line_shows_proper_case_title_and_author(db_path):
    out = photo_read.match_line({"title": "Owl Babies", "author": "Martin Waddell"}, db_path,
                                opener=Catalogue())
    assert out["status"] == "matched"
    cand = out["candidate"]
    assert cand["isbn"] == "9780763612832"
    assert cand["title"] == "Owl Babies"  # not the index slug "owl babies big book"
    assert cand["author"] == "Martin Waddell"
    assert cand["edition"] == "big book"  # the edition is still disclosed


def test_ranking_photo_matched_line_fills_the_author_the_index_does_not_hold(db_path):
    out = photo_read.match_line({"title": "Matilda", "author": "Roald Dahl"}, db_path, opener=Catalogue())
    assert out["status"] == "matched"
    assert out["candidate"]["title"] == "Matilda"
    assert out["candidate"]["author"] == "Roald Dahl"


def test_ranking_photo_line_stays_matched_when_the_catalogue_is_unreachable(db_path):
    def down(req, timeout=None):
        raise OSError("offline")

    out = photo_read.match_line({"title": "Matilda", "author": "Roald Dahl"}, db_path, opener=down)
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] == "9780142410370"
    assert out["candidate"]["title"] == "matilda"  # the index's own label, honestly

"""R13: a photo line matched in the index is shown with the catalogue's title and author.

The index holds Books-Express and Libris slugs ("owl babies big book", "matilda", and the
clipped "the very hungry caterpillar s", no author). What the shopper is buying has a real
title and an author, so a matched line is labelled from the same Open Library record and
ranking the typed search uses. The edition label stays. A shop slug is never shown as a
title, and an ISBN the catalogue does not confirm as the printed work is not matched.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from api import photo_read
from index import search as search_module

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "openlibrary"
DOCS = json.loads((FIXTURES / "isbn-records.json").read_text(encoding="utf-8"))["docs"]
WORK = json.loads((FIXTURES / "very-hungry-caterpillar.json").read_text(encoding="utf-8"))
# The stand-in catalogue answers for these records whichever way it is asked.
BY_ISBN = {search_module.to_isbn13(i): doc for doc in DOCS + WORK["docs"] for i in doc.get("isbn") or []
           if search_module.to_isbn13(i)}
BY_QUERY = {
    " ".join(search_module.normalize(q).split()): WORK["docs"]
    for q in ("The Very Hungry Caterpillar Eric Carle", "The Very Hungry Caterpillar")
}

CATERPILLAR = {"title": "The Very Hungry Caterpillar", "author": "Eric Carle"}
# The 123 board book's row, clipped to the work's words: its title lost the "123".
CATERPILLAR_SLUG = "the very hungry caterpillar s"
CATERPILLAR_SLUG_ISBN = "9780141367941"


class Catalogue:
    """The stand-in opener: a captured record for an ISBN, a captured search for a title."""

    def __call__(self, req, timeout=None):
        from urllib.parse import parse_qs, urlsplit

        q = " ".join(search_module.normalize(parse_qs(urlsplit(req.full_url).query).get("q", [""])[0]).split())
        docs = [BY_ISBN[q]] if q in BY_ISBN else BY_QUERY.get(q, [])
        body = json.dumps({"docs": docs}).encode()

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
            ("books-express", "https://www.books-express.ro/the-very-hungry-caterpillar-s-123/p/yfb,9780141367941",
             CATERPILLAR_SLUG, None, CATERPILLAR_SLUG_ISBN, "2026-10-30"),
            # S18 review: a shop lists the plain printing (a slug title; a row whose title is only a
            # subject code such as "yfb," would not count), so it can be matched.
            ("books-express", "https://www.books-express.ro/the-very-hungry-caterpillar/p/yfb,9780140569322",
             "the very hungry caterpillar", None, "9780140569322", "2026-10-30"),
        ])
    return path


def test_ranking_photo_matched_line_shows_proper_case_title_and_author(db_path):
    out = photo_read.match_line({"title": "Owl Babies", "author": "Martin Waddell"}, db_path,
                                opener=Catalogue())
    # S18: the big book is a special format, offered as a choice rather than matched.
    assert out["status"] == "ambiguous"
    [cand] = out["candidates"]
    assert cand["isbn"] == "9780763612832"
    assert cand["title"] == "Owl Babies"  # not the index slug "owl babies big book"
    assert cand["author"] == "Martin Waddell"
    assert cand["edition"] == "big book"  # the edition is still disclosed


def test_ranking_photo_matched_line_fills_the_author_the_index_does_not_hold(db_path):
    out = photo_read.match_line({"title": "Matilda", "author": "Roald Dahl"}, db_path, opener=Catalogue())
    assert out["status"] == "matched"
    assert out["candidate"]["title"] == "Matilda"
    assert out["candidate"]["author"] == "Roald Dahl"


def test_ranking_photo_reported_lines_each_show_their_own_work(db_path):
    """The two lines R13 was failed on, matched together: no slug, no borrowed ISBN."""
    owl = {"title": "Owl Babies", "author": "Martin Waddell"}
    out = {l["title"]: photo_read.match_line(l, db_path, opener=Catalogue()) for l in (CATERPILLAR, owl)}
    cat, owls = out[CATERPILLAR["title"]], out[owl["title"]]
    # S18: the only Owl Babies printing here is the big book, so it is a choice, not a match.
    assert (cat["status"], owls["status"]) == ("matched", "ambiguous")
    [owl_pick] = owls["candidates"]
    assert (cat["candidate"]["title"], cat["candidate"]["author"]) == ("The Very Hungry Caterpillar", "Eric Carle")
    assert (owl_pick["title"], owl_pick["author"]) == ("Owl Babies", "Martin Waddell")
    assert CATERPILLAR_SLUG_ISBN not in (cat["candidate"]["isbn"], owl_pick["isbn"])
    assert CATERPILLAR_SLUG not in json.dumps(out).lower()


def test_ranking_photo_line_is_not_matched_to_the_clipped_slug_row(db_path):
    """R13 regression: "the very hungry caterpillar s" is the 123 board book, not this work.

    The shop slug lost the "123", so the index sees the plain book's words in it and offers
    the 123's ISBN. The catalogue names that ISBN "The very hungry caterpillar's 123": a
    different work, so the ISBN is rejected and the line resolves from its own title.
    """
    out = photo_read.match_line(CATERPILLAR, db_path, opener=Catalogue())
    assert out["status"] == "matched"
    cand = out["candidate"]
    assert cand["isbn"] != CATERPILLAR_SLUG_ISBN
    assert cand["title"] == "The Very Hungry Caterpillar"
    assert cand["author"] == "Eric Carle"
    assert CATERPILLAR_SLUG not in json.dumps(out).lower()


def test_ranking_photo_line_is_not_matched_to_a_spin_off_by_isbn(db_path):
    """The ABC board book's title is close enough for the similarity gate, not for a match."""
    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM books WHERE isbn = ?", (CATERPILLAR_SLUG_ISBN,))
        db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)",
                   ("books-express", "https://www.books-express.ro/-/p/9780141361673",
                    "the very hungry caterpillar", None, "9780141361673", "2026-10-30"))
    out = photo_read.match_line(CATERPILLAR, db_path, opener=Catalogue())
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] != "9780141361673"
    assert out["candidate"]["title"] == "The Very Hungry Caterpillar"
    assert out["candidate"]["author"] == "Eric Carle"


def test_ranking_photo_slug_is_never_shown_when_the_catalogue_is_unreachable(db_path):
    def down(req, timeout=None):
        raise OSError("offline")

    out = photo_read.match_line(CATERPILLAR, db_path, opener=down)
    assert out["status"] == "not_found"  # not a match with the shop's slug as its title
    assert CATERPILLAR_SLUG not in json.dumps(out).lower()


def test_ranking_photo_ambiguous_picks_never_render_a_slug(db_path):
    """Two shop rows for the same title are a pick list, and a pick list shows books too."""
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)",
                   ("books-express", "https://www.books-express.ro/-/p/9780141370354",
                    "matilda", None, "9780141370354", "2026-10-30"))

    def down(req, timeout=None):
        raise OSError("offline")

    out = photo_read.match_line({"title": "Matilda", "author": "Roald Dahl"}, db_path, opener=down)
    assert out["status"] == "not_found"  # two shop slugs and no catalogue: nothing to show
    assert "matilda" not in json.dumps(out)

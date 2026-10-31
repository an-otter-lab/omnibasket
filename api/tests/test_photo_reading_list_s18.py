"""S18: a plain class reading list never resolves to a special format.

Seen: the basket got Owl Babies as a "Big book", The Very Hungry Caterpillar as a pull-out
pop-up, Guess How Much I Love You as a "blush sweetheart edition", Charlotte's Web "Deluxe"
and Matilda only as "Colour Edition". A special format (big book, pop-up, deluxe, gift,
colour, board book, box set, ...) is only matched when the line asks for it; otherwise it
is offered as a choice and the plain printing is ranked first.

The fixture is recorded: the shop index rows for the six lines and the Open Library answers
the match asked for (openlibrary.org only, Libris refused). No network here.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from api import photo_read
from index import search as search_module
from matching import ranking

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "openlibrary" / "reading-list-s18.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))

READING_LIST = [
    {"title": "Owl Babies", "author": "Martin Waddell"},
    {"title": "The Very Hungry Caterpillar", "author": "Eric Carle"},
    {"title": "Guess How Much I Love You", "author": "Sam McBratney"},
    {"title": "Charlotte's Web", "author": "E. B. White"},
    {"title": "The Boy, the Mole, the Fox and the Horse", "author": "Charlie Mackesy"},
    {"title": "Matilda", "author": "Roald Dahl"},
]
# The special printings the basket was given before S18.
SPECIAL_ISBNS = {
    "9780763612832",  # Owl Babies big book
    "9780141352220",  # The Very Hungry Caterpillar: a pull-out pop-up
    "9781536216806",  # Guess How Much I Love You: blush sweetheart edition
    "9780141368832",  # Charlotte's Web deluxe edition
    "9780141369365",  # Matilda colour edition
    "9780241558317",  # Matilda special edition
}


class Recorded:
    """The stand-in opener: the recorded Open Library answer for each URL, nothing else."""

    def __init__(self):
        self.missed: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        if url not in DATA["openlibrary"] or DATA["openlibrary"][url] is None:
            self.missed.append(url)
            raise OSError("not recorded")
        body = json.dumps(DATA["openlibrary"][url]).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return body

        return Response()


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    from api import fetch_guard

    def refuse(url, timeout=None):
        raise RuntimeError("no Libris reads in tests")

    monkeypatch.setattr(fetch_guard, "fetch", refuse)
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
                   "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [tuple(r) for r in DATA["books"]])
    return path


def _picked(out: dict) -> list[dict]:
    return [out["candidate"]] if out["status"] == "matched" else out.get("candidates", [])


def _is_special(line: dict, cand: dict, db_path) -> bool:
    titles = photo_read._shop_titles(db_path, [cand["isbn"]]).get(cand["isbn"], [])
    return cand["isbn"] in SPECIAL_ISBNS or bool(photo_read._special_label(line["title"], [cand["title"], *titles]))


def test_reading_list_no_line_resolves_to_a_special_format(db_path):
    opener = Recorded()
    out = [photo_read.match_line(line, db_path, opener=opener) for line in READING_LIST]
    for line, res in zip(READING_LIST, out):
        if res["status"] == "matched":
            assert not _is_special(line, res["candidate"], db_path), (line["title"], res["candidate"])
            assert "edition" not in res["candidate"]
        else:
            # A choice list ranks the plain printings first; a special one is labelled.
            flags = [_is_special(line, c, db_path) for c in res.get("candidates", [])]
            assert flags == sorted(flags), (line["title"], res)
            for c, special in zip(res.get("candidates", []), flags):
                assert bool(c.get("edition")) == special or not special
    matched = {r["read_title"]: r["candidate"]["isbn"] for r in out if r["status"] == "matched"}
    assert matched == {
        "Owl Babies": "9780763679613",
        "The Very Hungry Caterpillar": "9780140569322",
        "Guess How Much I Love You": "9781406390742",
        "Charlotte's Web": "9780141354828",
        "Matilda": "9780142402535",
    }
    assert not SPECIAL_ISBNS & {c["isbn"] for r in out for c in _picked(r) if r["status"] == "matched"}
    assert opener.missed == []  # every Open Library answer the match needed is recorded


def test_reading_list_special_format_is_matched_when_the_line_asks_for_it(db_path):
    with sqlite3.connect(db_path) as db:  # a cased record, so no catalogue lookup is needed
        db.execute("DELETE FROM books WHERE isbn = ?", ("9780763612832",))
        db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)", ("libris", "https://libris.ro/p/owl-big",
                   "Owl Babies Big Book", "Martin Waddell", "9780763612832", "2026-10-30"))
    out = photo_read.match_line({"title": "Owl Babies Big Book", "author": "Martin Waddell"}, db_path,
                                opener=Recorded())
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] == "9780763612832"


def test_reading_list_special_is_a_choice_when_no_plain_printing_is_known(db_path):
    """Only the big book is known (catalogue down): offered, labelled, never matched."""
    def down(req, timeout=None):
        raise OSError("offline")

    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM books WHERE isbn != ?", ("9780763612832",))
    out = photo_read.match_line(READING_LIST[0], db_path, opener=down)
    assert out["status"] != "matched"


@pytest.mark.parametrize("title", [
    "the very hungry caterpillar a pull out pop up", "guess how much i love you blush sweetheart edition",
    "owl babies big book", "charlotte s web deluxe edition", "Matilda (Colour Edition)",
    "guess how much i love you padded board book", "the gruffalo box set", "the gruffalo gift edition",
])
def test_reading_list_special_formats_are_marked(title):
    assert ranking.is_edition_variant(title)
    assert photo_read._special_label("Some Book", [title])


def test_reading_list_plain_titles_are_not_special():
    for title in ("The Very Hungry Caterpillar", "Matilda", "matilda puffin modern classics",
                  "The Colour Monster", "Charlotte's Web"):
        assert not photo_read._special_label("x", [title]), title


def test_reading_list_plain_printing_outranks_a_carried_special_one():
    titles = {"9780141352220": "the very hungry caterpillar a pull out pop up"}
    assert ranking.pick_isbn(["9780141352220", "9780140569322"], titles) == "9780140569322"

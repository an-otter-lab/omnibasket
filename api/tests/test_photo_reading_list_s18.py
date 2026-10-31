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
            # S18 answer 2: a choice lists the printings a shop lists first (plain, then special),
            # unlisted ones last (plain, then special); a special one is labelled.
            cands = res.get("candidates", [])
            listed = photo_read._listed(db_path, [c["isbn"] for c in cands])
            flags = [_is_special(line, c, db_path) for c in cands]
            keys = [(c["isbn"] not in listed, special) for c, special in zip(cands, flags)]
            assert keys == sorted(keys), (line["title"], res)
            for c, special in zip(res.get("candidates", []), flags):
                assert bool(c.get("edition")) == special or not special
    matched = {r["read_title"]: r["candidate"]["isbn"] for r in out if r["status"] == "matched"}
    # S18 review: only a plain printing a shop lists is matched. The plain Very Hungry Caterpillar
    # (9780140569322) and Guess How Much I Love You (9781406390742) are in no shop's index rows, and
    # the plain Owl Babies (9780763679613, "ybcs,") and Charlotte's Web (9780141354828, "yfp,") only
    # in rows whose title is a subject code (S18 answer 1), so those four lines are choices.
    # The Boy, the Mole... is matched to the printing Books-Express lists.
    assert matched == {
        "The Boy, the Mole, the Fox and the Horse": "9781786144577",
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


# --- S18 review (Claude): a matched printing no shop lists leaves the whole basket with
# "No ranked answer". Prefer a plain printing a shop lists; with none, the line is a choice.

def _listed(db_path, isbns):
    return photo_read._listed(db_path, list(isbns))


def test_review_unlisted_plain_printing_is_a_choice_with_the_listed_specials(db_path):
    """Guess How Much I Love You: the plain printing is in no shop's rows, so the line is a
    choice: the special printings shops list first, each labelled, the unlisted plain one last."""
    out = photo_read.match_line(READING_LIST[2], db_path, opener=Recorded())
    assert out["status"] == "ambiguous"
    cands = out["candidates"]
    assert cands[-1]["isbn"] == "9781406390742" and "edition" not in cands[-1]
    assert cands[-1]["isbn"] not in _listed(db_path, [cands[-1]["isbn"]])
    rest = cands[:-1]
    assert rest and all(c.get("edition") for c in rest)
    assert {c["isbn"] for c in rest} <= _listed(db_path, [c["isbn"] for c in rest])
    assert all(c["title"] == "Guess How Much I Love You" for c in cands)  # never a shop slug


def test_review_listed_plain_printing_is_preferred_over_an_unlisted_one(db_path):
    """The Boy, the Mole...: two plain printings in the index, one only an Amazon.de capture
    (never read live), one listed by Books-Express. The listed one is the match."""
    out = photo_read.match_line(READING_LIST[4], db_path, opener=Recorded())
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] == "9781786144577"
    assert _listed(db_path, ["9781529105100", "9781786144577"]) == {"9781786144577"}


def test_review_no_listed_printing_at_all_is_still_a_choice(db_path):
    """Only plain printings are known and no shop lists any of them: offered, not matched."""
    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM books WHERE isbn = ?", ("9780763679613",))
        db.execute("DELETE FROM books WHERE isbn = ?", ("9780763612832",))
    out = photo_read.match_line(READING_LIST[0], db_path, opener=Recorded())
    assert out["status"] == "ambiguous"
    isbns = [c["isbn"] for c in out["candidates"]]
    assert isbns and all(c["title"] == "Owl Babies" for c in out["candidates"])
    assert not _listed(db_path, isbns)
    assert not any(c.get("edition") for c in out["candidates"])


def test_review_reading_list_basket_can_rank(db_path):
    """Every line ends on a printing a shop lists: matched lines directly, choice lines with a
    listed printing among the choices. "No ranked answer" comes only from a book no shop lists,
    so a basket of these printings can be ranked (the live price itself is a live read)."""
    out = [photo_read.match_line(line, db_path, opener=Recorded()) for line in READING_LIST]
    basket = []
    for line, res in zip(READING_LIST, out):
        if res["status"] == "matched":
            assert res["candidate"]["isbn"] in _listed(db_path, [res["candidate"]["isbn"]]), line["title"]
            basket.append(res["candidate"]["isbn"])
        else:
            assert res["status"] == "ambiguous", (line["title"], res)
            isbns = [c["isbn"] for c in res["candidates"]]
            listed = [i for i in isbns if i in _listed(db_path, isbns)]
            assert listed, (line["title"], isbns)
            basket.append(listed[0])
    assert len(basket) == 6
    assert set(basket) == _listed(db_path, basket)


# --- S18 answers (Claude): (1) a Books-Express row whose title is only a subject code does not
# count as a shop listing; (2) inside a choice, listed printings first (plain, then special),
# unlisted ones last (plain, then special).

def test_answer1_a_subject_code_row_is_not_a_listing(db_path):
    """The real index holds the plain Owl Babies only as a "ybcs," row: not a listing, so the
    line is a choice with the listed big book first and the plain printing last."""
    assert photo_read._subject_code_only("ybcs,") and photo_read._subject_code_only(" yfp, ")
    assert not photo_read._subject_code_only("owl babies") and not photo_read._subject_code_only(None)
    assert _listed(db_path, ["9780763679613", "9780141354828"]) == set()
    out = photo_read.match_line(READING_LIST[0], db_path, opener=Recorded())
    assert out["status"] == "ambiguous"
    assert [(c["isbn"], c.get("edition")) for c in out["candidates"]] == [
        ("9780763612832", "big book"), ("9780763679613", None)]


def test_answer1_the_same_row_with_a_title_is_a_listing(db_path):
    """The rule is about the title only: the same Books-Express page with a slug title counts, and
    the plain printing is matched again."""
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE books SET title = 'owl babies' WHERE isbn = '9780763679613'")
    assert _listed(db_path, ["9780763679613"]) == {"9780763679613"}
    out = photo_read.match_line(READING_LIST[0], db_path, opener=Recorded())
    assert out["status"] == "matched" and out["candidate"]["isbn"] == "9780763679613"


def _row(db, isbn, title):
    db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)",
               ("books-express", f"https://www.books-express.ro/x/p/{isbn}", title, None, isbn, "2026-10-30"))


def test_answer2_choice_order_listed_plain_listed_special_unlisted_plain_unlisted_special(tmp_path, monkeypatch):
    """All four groups at once: two listed plain printings (so no single match), a listed special,
    an unlisted plain and an unlisted special. Catalogue order is deliberately the reverse."""
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
                   "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        _row(db, "9780000000011", "owl babies")             # listed plain
        _row(db, "9780000000022", "owl babies")             # listed plain
        _row(db, "9780000000033", "owl babies big book")    # listed special
        _row(db, "9780000000044", "ybcs,")                  # code-only row: unlisted plain
    cands = [
        {"isbn": "9780000000055", "title": "Owl Babies Board Book", "author": "Martin Waddell"},  # unlisted special
        {"isbn": "9780000000044", "title": "Owl Babies", "author": "Martin Waddell"},
        {"isbn": "9780000000033", "title": "Owl Babies", "author": "Martin Waddell"},
        {"isbn": "9780000000022", "title": "Owl Babies", "author": "Martin Waddell"},
        {"isbn": "9780000000011", "title": "Owl Babies", "author": "Martin Waddell"},
    ]
    monkeypatch.setattr(photo_read, "online_lookup", lambda line, db_path, opener=None, **k: [dict(c) for c in cands])
    out = photo_read.resolve_online(READING_LIST[0], {"read_title": "Owl Babies"}, path, opener=None)
    assert out["status"] == "ambiguous"
    got = [(c["isbn"], bool(c.get("edition"))) for c in out["candidates"]]
    assert got == [("9780000000022", False), ("9780000000011", False), ("9780000000033", True),
                   ("9780000000044", False), ("9780000000055", True)]

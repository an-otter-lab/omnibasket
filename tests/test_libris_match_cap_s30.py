"""S30: the Libris title match is bounded, so a photo read always answers.

The fixture index is shaped like the real one where it matters: thousands of Libris rows whose
titles hold words starting with "i", "you", "love" and "how", the prefixes "Guess How Much I Love
You" turns into. With the old JOIN, SQLite ran the full-text MATCH once per Libris row (minutes on
the real index). Now the MATCH is the outer loop, and a time cap backs it up.
"""
import sqlite3
import time

import pytest

from index import search as search_module
from index.search import ensure_books_search

GUESS_URL = "https://www.libris.ro/carte/guess-how-much-i-love-you-sam-mcbratney/1"
MATILDA_URL = "https://www.libris.ro/carte/matilda-roald-dahl/2"
WORDS = ["iubire", "insula", "ioana", "istorie", "you", "young", "love", "lovely", "how", "however",
         "much", "guest", "carte", "poveste"]


@pytest.fixture
def db(tmp_path):
    db = sqlite3.connect(tmp_path / "books.sqlite3")
    db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
               "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
    rows = []
    for n in range(12000):
        title = " ".join(WORDS[(n * k) % len(WORDS)] for k in (1, 3, 5, 7))  # never all six words
        rows.append(("libris", f"https://www.libris.ro/carte/x-{n}", title, None, None, "2026-10-30"))
    for n in range(6000):
        rows.append(("books-express", f"https://www.books-express.ro/p/{n}", "i you love how much", None,
                     None, "2026-10-30"))
    rows += [("libris", GUESS_URL, "guess how much i love you sam mcbratney", None, None, "2026-10-30"),
             ("libris", MATILDA_URL, "matilda roald dahl", None, None, "2026-10-30")]
    db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", rows)
    ensure_books_search(db)
    db.commit()
    yield db
    db.close()


def test_guess_how_much_i_love_you_answers_in_bounded_time(db):
    started = time.monotonic()
    url = search_module._libris_candidate(db, ["Guess How Much I Love You"])
    took = time.monotonic() - started
    assert url == GUESS_URL
    assert took < search_module.LIBRIS_MATCH_SECONDS


def test_matilda_still_found(db):
    assert search_module._libris_candidate(db, ["Matilda roald dahl"]) == MATILDA_URL


def test_the_full_text_match_drives_the_query(db):
    """The plan's outer loop is the MATCH, and books is looked up by rowid (not scanned by shop)."""
    import inspect
    src = inspect.getsource(search_module._libris_candidate)
    sql = src[src.index('"""SELECT') + 3: src.index('LIMIT 200') + 9]
    plan = [r[-1] for r in db.execute("EXPLAIN QUERY PLAN " + sql, ('"guess"*',)).fetchall()]
    assert plan[0].startswith("SCAN s VIRTUAL TABLE"), plan
    assert any("rowid=?" in p for p in plan), plan


def test_a_match_over_the_cap_gives_up_without_raising(db, monkeypatch):
    """Over the cap the line gets no Libris link, the read still answers, and the connection is usable."""
    monkeypatch.setattr(search_module, "LIBRIS_MATCH_SECONDS", -1.0)  # already past the cap
    monkeypatch.setattr(search_module, "LIBRIS_MATCH_CHECK_EVERY", 1)  # look at the clock on every step
    errors_before = len(search_module.MATCH_ERRORS)
    started = time.monotonic()
    assert search_module._libris_candidate(db, ["Guess How Much I Love You"]) is None
    assert time.monotonic() - started < 1.0
    assert search_module.MATCH_ERRORS[errors_before:] == [{"query": "Guess How Much I Love You", "error": "time cap"}]
    assert db.execute("SELECT count(*) FROM books").fetchone()[0] == 18002  # the handler was removed

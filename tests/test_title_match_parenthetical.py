"""Title matching ignores trailing parentheticals and subtitles."""

from api.title_match import strong_match

OL_TITLE = "Micul prinț (Cu explicații pentru copii și recenzie pentru adulți)"
AUTHOR = "Antoine de Saint-Exupéry"
PAGE = "Micul print Antoine de Saint-Exupery editie bilingva"
PAGE_AUTHORS = ["Antoine de Saint-Exupery"]


def test_real_pair_with_parenthetical_matches():
    assert strong_match(OL_TITLE, AUTHOR, PAGE, PAGE_AUTHORS)


def test_plain_title_still_matches():
    assert strong_match("Micul prinț", AUTHOR, PAGE, PAGE_AUTHORS)


def test_subtitle_after_dash_is_ignored():
    assert strong_match("Micul prinț - editie ilustrata", AUTHOR, PAGE, PAGE_AUTHORS)


def test_other_book_with_parenthetical_rejected():
    assert not strong_match("Omul in cautarea sensului (Un psiholog in lagar)", AUTHOR,
                            PAGE, PAGE_AUTHORS)
    assert not strong_match("Micul print (Editie speciala)", AUTHOR,
                            "Zborul de noapte Antoine de Saint-Exupery", PAGE_AUTHORS)


def test_index_lookup_uses_core_title(tmp_path):
    import sqlite3

    from api.offers import lookup_title_url

    db = tmp_path / "b.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE books(shop TEXT, url TEXT, title TEXT, author_hint TEXT, isbn TEXT, last_seen TEXT)")
        c.execute("INSERT INTO books VALUES('libris','https://www.libris.ro/carte/micul-print/1',?,NULL,NULL,'2026-10-30')",
                  (PAGE,))
    assert lookup_title_url("libris", OL_TITLE, AUTHOR, db_path=db) == "https://www.libris.ro/carte/micul-print/1"


def test_author_gate_kept():
    assert not strong_match(OL_TITLE, AUTHOR, PAGE, ["Alt Autor"])


def test_numbers_gate_kept():
    assert not strong_match("Harry Potter (Vol. 1)", "J. K. Rowling",
                            "Harry Potter 2 J.K. Rowling", ["J.K. Rowling"])

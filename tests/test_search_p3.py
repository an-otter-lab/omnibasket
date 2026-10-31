"""P3: a children's-books demo hides titles with strong profanity, unless the shopper typed the word.

Open Library is a stand-in opener (the suite blocks sockets); no Libris page is read.
"""

import pytest

from tests.test_index_search import SAPIENS, FakeOL, make_db, run

search_module = __import__("index.search", fromlist=["search"])

RUDE = {"title": "Resumen de el Sutil Arte de Que Te Importe un Carajo (the Subtle Art of Not Giving a Fuck) - de Marc Manson",
        "author_name": ["Mark Manson"], "isbn": ["9780062457714"]}
AGENDA = {"title": "Simon vs. the Homo Sapiens Agenda", "author_name": ["Becky Albertalli"], "isbn": ["9780062348678"]}
SUBTITLED = {"title": "Field Notes", "subtitle": "a shitty first draft", "author_name": ["A. Writer"], "isbn": ["9780000000002"]}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "books.sqlite3"
    make_db(p, [])
    return p


def _titles(results):
    return [r["title"] for r in results]


def test_sapiens_no_longer_lists_the_profane_title(db_path):
    ol = FakeOL({"sapiens": [SAPIENS, AGENDA, RUDE, SUBTITLED]})
    titles = _titles(run(db_path, "sapiens", ol))
    assert "Sapiens" in titles and "Simon vs. the Homo Sapiens Agenda" in titles
    assert not any("Fuck" in t for t in titles)
    assert "Field Notes" not in titles  # the subtitle counts too


def test_a_shopper_who_types_the_word_still_finds_the_book(db_path):
    ol = FakeOL({"subtle art of not giving a fuck": [RUDE]})
    assert _titles(run(db_path, "subtle art of not giving a fuck", ol)) == [RUDE["title"]]


def test_an_isbn_search_is_never_filtered(db_path):
    ol = FakeOL({"9780062457714": [RUDE]})
    assert _titles(run(db_path, "9780062457714", ol)) == [RUDE["title"]]


@pytest.mark.parametrize("title", ["Shiitake Mushrooms", "Scunthorpe United", "Shitsuke and the Japanese Garden", "Matilda"])
def test_ordinary_words_are_not_caught(title):
    assert not search_module._profane(title)

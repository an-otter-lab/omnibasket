"""Search ranking on real Open Library captures (R2, R13).

Fixtures under tests/fixtures/openlibrary/ are the live search.json payloads and one
edition record, trimmed to the fields the app asks for. The shop index is a small
table with the rows that matter: the Scots printing of Matilda is in it, as the
catalogue's own ISBN list says nothing about a printing being a translation.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from index import search as search_module

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "openlibrary"
MATILDA = "Matilda Roald Dahl"
HARRY_POTTER = "Harry Potter and the Philosopher's Stone"
MICUL = "Micul prinț"

MATILDA_RO, MATILDA_EN = "9789735832940", "9780747532699"
HP_RO = "9789735832940"
SCOTS = "9781785302350"

SEARCHES = {
    search_module.normalize(MATILDA): "matilda-roald-dahl.json",
    search_module.normalize(HARRY_POTTER): "harry-potter-philosophers-stone.json",
    search_module.normalize(MICUL): "micul-print.json",
}


class Catalogue:
    """The stand-in opener: the captured payload for the query, the captured edition by ISBN."""

    def __init__(self):
        self.docs = {key: json.loads((FIXTURES / name).read_text(encoding="utf-8"))["docs"]
                     for key, name in SEARCHES.items()}
        self.editions = {HP_RO: json.loads((FIXTURES / "isbn-9789735832940.json").read_text(encoding="utf-8"))}
        self.calls = []

    def __call__(self, req, timeout=None):
        from urllib.parse import parse_qs, urlsplit

        self.calls.append(req.full_url)
        url = urlsplit(req.full_url)
        if "/isbn/" in url.path:
            payload = self.editions.get(url.path.rsplit("/", 1)[1][: -len(".json")], {})
        else:
            key = " ".join(search_module.normalize(parse_qs(url.query)["q"][0]).split())
            payload = {"docs": self.docs.get(key, [])}
        body = json.dumps(payload).encode()

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
    """The shop index rows that decide a printing: Books-Express' own titles."""
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,"
                   "isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [
            # The Scots translation of Matilda: the catalogue lists its ISBN under "Matilda".
            ("books-express", "https://www.books-express.ro/matilda-in-scots/p/yf,9781785302350",
             "matilda in scots", None, SCOTS, "2026-10-30"),
            ("books-express", "https://www.books-express.ro/-/p/9780142410370",
             "matilda", "Roald Dahl", "9780142410370", "2026-10-30"),
            ("libris", "https://www.libris.ro/harry-potter-si-piatra-filosofala-j-k-rowling",
             "harry potter si piatra filozofala j k rowling", None, None, "2026-10-30"),
        ])
    return path


def run(db_path, q, **kwargs):
    return search_module.search(q, db_path=db_path, opener=kwargs.pop("opener", Catalogue()), **kwargs)


def test_ranking_matilda_puts_the_english_puffin_or_penguin_edition_first(db_path):
    res = run(db_path, MATILDA)
    assert res[0]["title"] == "Matilda"
    assert res[0]["author"] == "Roald Dahl"
    # 978-0-14 is Puffin, 978-0-241 Penguin: the shelf edition, not a library binding.
    assert res[0]["isbn"].startswith(("978014", "978024", "978067")), res[0]["isbn"]
    # The Scots translation is never the book: not first, not anywhere.
    assert SCOTS not in [r["isbn"] for r in res]
    assert all("scots" not in (r["title"] or "").lower() for r in res)


def test_ranking_matilda_is_not_displaced_by_a_workbook_or_a_bundle(db_path):
    res = run(db_path, MATILDA)
    titles = [r["title"] for r in res]
    assert titles.index("Matilda") == 0
    for other in titles[1:]:
        assert other != "Matilda"  # one row per printing of the book, not per catalogue record


def test_ranking_harry_potter_returns_the_romanian_edition_then_the_english_one(db_path):
    res = run(db_path, HARRY_POTTER)
    assert res[0]["isbn"] == HP_RO
    assert res[0]["title"] == "Harry Potter si piatra filozofala"  # the edition record's own title
    assert res[1]["title"] == "Harry Potter and the Philosopher's Stone"
    assert res[1]["isbn"].startswith(("9780", "9781")), res[1]["isbn"]
    assert res[1]["isbn"] != HP_RO


def test_ranking_harry_potter_has_no_other_volume_and_no_foreign_printing_in_the_top_two(db_path):
    res = run(db_path, HARRY_POTTER)
    assert not any("Azkaban" in (r["title"] or "") for r in res[:2])
    assert not any("weinstein" in (r["author"] or "") for r in res[:3])
    shown = [r["isbn"] for r in res if r["isbn"]]
    assert not [i for i in shown if i.startswith(("97889", "9787"))], shown


def test_ranking_keeps_the_romanian_diacritics_the_record_has(db_path):
    res = run(db_path, MICUL)
    first = res[0]
    assert first["isbn"] == "9786060339229"
    assert first["title"] == "Micul prinț (Cu explicații pentru copii și recenzie pentru adulți)"
    assert first["title"] != search_module.normalize(first["title"])  # folding is for comparison only


def test_ranking_is_the_same_with_or_without_diacritics(db_path):
    with_d = run(db_path, "Micul prinț")
    without = run(db_path, "Micul print")
    assert [r["isbn"] for r in with_d] == [r["isbn"] for r in without]
    assert with_d[0]["title"] == without[0]["title"]


def test_ranking_ignores_a_foreign_printing_when_an_english_one_exists(db_path):
    """The Harry Potter work lists 978-89, 978-7 and 978-84 printings; none is offered here."""
    res = run(db_path, HARRY_POTTER)
    assert res and all(not (r["isbn"] or "").startswith(("97889", "9787", "97884")) for r in res)

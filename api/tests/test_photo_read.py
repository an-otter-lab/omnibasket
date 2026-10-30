"""Feature 2 backend tests: mocked model, fixture image, fixture index, no network."""
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from api import photo_read
from api.app import create_app

meta_budget = photo_read.meta_budget

PNG = b"\x89PNG\r\n\x1a\n" + b"fixture-image-bytes" * 4

BOOKS = [
    ("libris", "https://libris.ro/p/1", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
    ("libris", "https://libris.ro/p/2", "Matilda", "Roald Dahl", "9780142410370"),
    ("libris", "https://libris.ro/p/3", "The Gruffalo", "Julia Donaldson", "9781509804757"),
    ("libris", "https://libris.ro/p/4", "Charlotte's Web", "E. B. White", "9780064400558"),
    ("libris", "https://libris.ro/p/5", "Where the Wild Things Are", "Maurice Sendak", "9780060254926"),
    ("libris", "https://libris.ro/p/6", "The Little Prince", "Antoine de Saint-Exupery", "9780156012195"),
    ("emag", "https://emag.ro/p/7", "Dune", "Frank Herbert", "9780441172719"),
    ("emag", "https://emag.ro/p/8", "Dune", "Brian Herbert", "9780765312891"),
]
LIST6 = [
    {"title": "The Very Hungry Caterpillar", "author": "Eric Carle"},
    {"title": "Matilda", "author": "Roald Dahl"},
    {"title": "The Gruffalo", "author": "Julia Donaldson"},
    {"title": "Charlotte's Web", "author": "E. B. White"},
    {"title": "Where the Wild Things Are", "author": "Maurice Sendak"},
    {"title": "The Little Prince", "author": "Antoine de Saint-Exupery"},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "books.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        c.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [(*r, "2026-10-30") for r in BOOKS])
    app = create_app()
    app.state.index_db_path = db
    return TestClient(app)


def mock_model(monkeypatch, text=None, exc=None, calls=None):
    def fake(body, estimate, note, provider="meta"):
        if calls is not None:
            calls.append(body)
        if exc:
            raise exc
        return {"output_text": text}, {}
    monkeypatch.setattr(meta_budget, "guarded_post", fake)


def post(client, data=PNG, ctype="image/png"):
    return client.post("/photo", content=data, headers={"content-type": ctype})


def test_six_clean_lines_matched(client, monkeypatch):
    calls = []
    mock_model(monkeypatch, json.dumps({"lines": LIST6}), calls=calls)
    r = post(client)
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert [l["status"] for l in lines] == ["matched"] * 6
    assert lines[0]["candidate"]["isbn"] == "9780141367941"
    assert lines[0]["candidate"]["cover_url"] == "https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg"
    body = calls[0]
    assert body["model"] == "muse-spark-1.3" and body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] >= 1200
    assert "isbn" in body["input"][0]["content"][0]["text"].lower()


def test_isbn_never_comes_from_model(client, monkeypatch):
    lines = [dict(LIST6[0], isbn="9999999999999")]
    mock_model(monkeypatch, json.dumps({"lines": lines}))
    out = post(client).json()["lines"][0]
    assert out["candidate"]["isbn"] == "9780141367941"
    assert "9999999999999" not in json.dumps(out)


def test_unmatched_and_ambiguous(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [
        {"title": "Zzyzx Unknown Tome", "author": "Nobody"},
        {"title": "Dune", "author": None},
        LIST6[1],
    ]}))
    lines = post(client).json()["lines"]
    assert lines[0]["status"] == "not_found" and "candidate" not in lines[0]
    assert lines[1]["status"] == "ambiguous"
    assert {c["isbn"] for c in lines[1]["candidates"]} == {"9780441172719", "9780765312891"}
    assert all("edition" not in c for c in lines[1]["candidates"])
    assert lines[2]["status"] == "matched"
    assert "edition" not in lines[2]["candidate"]


def test_edition_variant_is_labelled(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [
        {"title": "Owl Babies", "author": "Martin Waddell"},
    ]}))
    with sqlite3.connect(client.app.state.index_db_path) as c:
        c.execute(
            "INSERT INTO books VALUES(?,?,?,?,?,?)",
            ("libris", "https://libris.ro/p/owl", "Owl Babies Big Book", "Martin Waddell", "9780763612832", "2026-10-30"),
        )
    # The fixture index is rebuilt inside the request; drop the stale FTS so the new row is visible.
    with sqlite3.connect(client.app.state.index_db_path) as c:
        c.execute("DROP TABLE IF EXISTS books_search")
    out = post(client).json()["lines"][0]
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] == "9780763612832"
    assert out["candidate"]["edition"] == "big book"


def test_spinoff_is_not_a_candidate(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [
        {"title": "The Very Hungry Caterpillar", "author": "Eric Carle"},
    ]}))
    with sqlite3.connect(client.app.state.index_db_path) as c:
        c.execute("DELETE FROM books WHERE isbn = ?", ("9780141367941",))
        c.execute(
            "INSERT INTO books VALUES(?,?,?,?,?,?)",
            ("libris", "https://libris.ro/p/abc", "The Very Hungry Caterpillar's ABC", "", "9780141361673", "2026-10-30"),
        )
        c.execute("DROP TABLE IF EXISTS books_search")
    out = post(client).json()["lines"][0]
    assert out["status"] == "not_found"


def test_non_format_qualifier_is_ambiguous_and_labeled(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [{"title": "Guess How Much I Love You", "author": None}]}))
    with sqlite3.connect(client.app.state.index_db_path) as c:
        c.execute("INSERT INTO books VALUES(?,?,?,?,?,?)",
                  ("libris", "https://libris.ro/p/guess", "Guess How Much I Love You Padded Board Book", "", "9780000000100", "2026-10-30"))
        c.execute("DROP TABLE IF EXISTS books_search")
    out = post(client).json()["lines"][0]
    assert out["status"] == "ambiguous"
    assert out["candidates"][0]["edition"] == "padded"


def test_qualifier_tier_caps_and_orders_candidates(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [{"title": "Guess How Much I Love You", "author": None}]}))
    with sqlite3.connect(client.app.state.index_db_path) as c:
        rows = [("libris", "https://libris.ro/p/q%d" % i, "Guess How Much I Love You" + suffix, "", "97800000001%02d" % i, "2026-10-30")
                for i, suffix in enumerate([" Gift Set", " Sticker Book", " Deluxe", " Padded Board Book", " Anniversary Edition", " Big Book"], 0)]
        c.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", rows)
        c.execute("DROP TABLE IF EXISTS books_search")
    out = post(client).json()["lines"][0]
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) <= 5
    assert [len(c["edition"].split()) for c in out["candidates"]] == sorted(len(c["edition"].split()) for c in out["candidates"])


def test_common_word_title_stays_fast(tmp_path):
    """A title made of common words must not scan the table: one AND query, well under a second."""
    db = tmp_path / "books.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        rows = [
            ("s", "https://ex/%d" % i, "web of the white sea %d" % i, "", "9780000000%04d" % i, "2026-10-30")
            for i in range(3000)
        ]
        rows.append(("s", "https://ex/hit", "Charlotte's Web Deluxe Edition", "", "9780141368832", "2026-10-30"))
        c.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", rows)
    started = time.perf_counter()
    out = photo_read.match_line({"title": "Charlotte's Web", "author": "E. B. White"}, db)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, elapsed
    assert out["status"] == "matched"
    assert out["candidate"]["isbn"] == "9780141368832"
    assert out["candidate"]["edition"] == "deluxe edition"
    assert photo_read.fts_and_query(photo_read.title_words("Charlotte's Web")) == '"charlotte" "web"'


@pytest.mark.parametrize("text", ["", "   ", "sorry, I cannot read this", '{"lines": []}', '{"lines": [{"title": 5}]}', "[1, 2]"])
def test_empty_or_unparseable_is_read_failed(client, monkeypatch, text):
    mock_model(monkeypatch, text)
    r = post(client)
    assert r.status_code == 200 and r.json() == {"error": "read_failed"}


def test_one_bad_line_drops_everything(client, monkeypatch):
    mock_model(monkeypatch, json.dumps({"lines": [LIST6[0], {"author": "x"}]}))
    assert post(client).json() == {"error": "read_failed"}


def test_budget_refusal_is_read_failed(client, monkeypatch):
    mock_model(monkeypatch, exc=meta_budget.CapExceeded(9.99, 0.05))
    assert post(client).json() == {"error": "read_failed"}


def test_oversize_is_413_and_model_not_called(client, monkeypatch):
    calls = []
    mock_model(monkeypatch, "{}", calls=calls)
    r = post(client, PNG + b"0" * photo_read.MAX_IMAGE_BYTES)
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert calls == []


def test_wrong_type_is_415(client, monkeypatch):
    calls = []
    mock_model(monkeypatch, "{}", calls=calls)
    assert post(client, b"%PDF-1.4", "application/pdf").status_code == 415
    assert post(client, b"not really a png", "image/png").status_code == 415
    assert post(client, b"", "image/png").status_code in (400, 415)
    assert calls == []


def test_nothing_stored_or_logged(client, monkeypatch, tmp_path, caplog):
    mock_model(monkeypatch, json.dumps({"lines": LIST6[:1]}))
    import os
    before = set(os.listdir(tmp_path))
    with caplog.at_level("DEBUG"):
        post(client)
    assert set(os.listdir(tmp_path)) == before
    assert "fixture-image-bytes" not in caplog.text


def test_per_ip_limit_applies(client, monkeypatch):
    mock_model(monkeypatch, "")
    codes = {post(client).status_code for _ in range(70)}
    assert 429 in codes

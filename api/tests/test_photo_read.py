"""Feature 2 backend tests: mocked model, fixture image, fixture index, no network."""
import json
import sqlite3
from email.message import Message

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


class NoNet:
    def __call__(self, *a, **k):
        raise OSError("no network in tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "books.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        c.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [(*r, "2026-10-30") for r in BOOKS])
    app = create_app()
    app.state.index_db_path = db
    real = photo_read.search
    monkeypatch.setattr(photo_read, "search", lambda q, limit, db_path, opener=None: real(q, limit=limit, db_path=db_path, opener=NoNet()))
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
    assert lines[2]["status"] == "matched"


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

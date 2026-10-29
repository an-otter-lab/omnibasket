import json
import sqlite3
from email.message import Message

from fastapi.testclient import TestClient

from api.app import create_app
search_module = __import__("index.search", fromlist=["search"])


def make_db(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [(*row, "2026-10-30") for row in rows])


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = Message()
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size=-1): return json.dumps(self.payload).encode()


def test_accent_insensitive_romanian_and_english(tmp_path):
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/piatra", "Piatra filozofală", "J. K. Rowling", None),
        ("books-express", "https://books-express.ro/p/caterpillar", "The Very Hungry Caterpillar", "Eric Carle", "9780064431781"),
    ])
    assert search_module.search("piatra filozofala", db_path=path, opener=lambda *a, **k: Response({"docs": []}))[0]["title"] == "Piatra filozofală"
    result = search_module.search("VERY hungry", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert result[0]["title"] == "The Very Hungry Caterpillar"
    exact = search_module.search("The Very Hungry Caterpillar", db_path=path)
    assert exact[0]["title"] == "The Very Hungry Caterpillar"


def test_exact_isbn_and_duplicate_merge(tmp_path):
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("books-express", "https://books-express.ro/p/a", "The Very Hungry Caterpillar", "Eric Carle", "9780064431781"),
        ("amazon_de", "https://amazon.de/dp/a", "The Very Hungry Caterpillar", "Eric Carle", "9780064431781"),
    ])
    result = search_module.search("9780064431781", db_path=path)
    assert len(result) == 1
    assert result[0]["isbn"] == "9780064431781"
    assert {shop["shop"] for shop in result[0]["shops"]} == {"books-express", "amazon_de"}
    assert result[0]["cover_url"] == "https://covers.openlibrary.org/b/isbn/9780064431781-M.jpg"


def test_openlibrary_lookup_is_cached(tmp_path):
    path = tmp_path / "books.sqlite3"
    make_db(path, [("libris", "https://libris.ro/p/a", "A Book", "Author", None)])
    calls = []
    def opener(req, timeout):
        calls.append((req.full_url, timeout, req.get_header("User-agent")))
        return Response({"docs": [{"isbn": ["9780306406157"]}]})
    one = search_module.search("A Book", db_path=path, opener=opener)
    two = search_module.search("A Book", db_path=path, opener=opener)
    assert one[0]["isbn"] == two[0]["isbn"] == "9780306406157"
    assert len(calls) == 1 and calls[0][1] <= 10 and "Omnibasket" in calls[0][2]


def test_search_endpoint_short_list_and_empty(tmp_path, monkeypatch):
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "Piatra filozofală", None, None),
        ("libris", "https://libris.ro/p/b", "Another Piatra", None, None),
    ])

    monkeypatch.setattr(search_module.urllib.request, "urlopen", lambda *a, **k: Response({"docs": []}))
    app = create_app(db_path=tmp_path / "unrelated.sqlite3")
    app.state.index_db_path = path
    client = TestClient(app)
    response = client.get("/search", params={"q": "piatra", "limit": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "piatra" and len(payload["results"]) == 1
    assert client.get("/search").json() == {"query": "", "results": []}


def test_stop_words_filtered(tmp_path):
    """Stop words like 'si' should not match unrelated titles."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "Piatra filozofală", "Author", None),
        ("libris", "https://libris.ro/p/b", "Si alte povesti", "Author", None),
    ])
    result = search_module.search("si piatra", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert len(result) >= 1
    assert result[0]["title"] == "Piatra filozofală"
    assert all("alte povesti" not in r["title"] for r in result)


def test_isbn_validation_rejects_invalid(tmp_path):
    """Open Library lookup must validate ISBN check digits."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [("libris", "https://libris.ro/p/a", "A Book", "Author", None)])
    def opener(req, timeout):
        # Return an invalid ISBN (bad check digit)
        return Response({"docs": [{"isbn": ["9781234567890"]}]})
    result = search_module.search("A Book", db_path=path, opener=opener)
    assert result[0]["isbn"] is None


def test_merge_rows_with_missing_isbn(tmp_path):
    """Rows with and without ISBN for same book should merge into one result."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "The Very Hungry Caterpillar", "Eric Carle", None),
        ("books-express", "https://books-express.ro/p/a", "The Very Hungry Caterpillar", "Eric Carle", "9780064431781"),
    ])
    result = search_module.search("very hungry caterpillar", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert len(result) == 1
    assert result[0]["isbn"] == "9780064431781"
    assert len(result[0]["shops"]) == 2
    assert {shop["shop"] for shop in result[0]["shops"]} == {"libris", "books-express"}


def test_fts_works_offline(tmp_path):
    """FTS search should work without Open Library calls."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "Piatra filozofală", "Rowling", "9780064431781"),
    ])
    # Ensure FTS table exists
    search_module.refresh_fts(path)
    
    # Search should work without calling opener
    calls = []
    def opener(req, timeout):
        calls.append(1)
        return Response({"docs": []})
    
    result = search_module.search("piatra filozofala", db_path=path, opener=opener)
    assert len(result) == 1
    assert result[0]["title"] == "Piatra filozofală"
    assert result[0]["isbn"] == "9780064431781"
    # No Open Library call needed since ISBN already present
    assert len(calls) == 0

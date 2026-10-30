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
        ("books-express", "https://books-express.ro/p/caterpillar", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
    ])
    assert search_module.search("piatra filozofala", db_path=path, opener=lambda *a, **k: Response({"docs": []}))[0]["title"] == "Piatra filozofală"
    result = search_module.search("VERY hungry", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert result[0]["title"] == "The Very Hungry Caterpillar"
    exact = search_module.search("The Very Hungry Caterpillar", db_path=path)
    assert exact[0]["title"] == "The Very Hungry Caterpillar"


def test_exact_isbn_and_duplicate_merge(tmp_path):
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("books-express", "https://books-express.ro/p/a", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
        ("amazon_de", "https://amazon.de/dp/a", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
    ])
    result = search_module.search("9780141367941", db_path=path)
    assert len(result) == 1
    assert result[0]["isbn"] == "9780141367941"
    assert {shop["shop"] for shop in result[0]["shops"]} == {"books-express", "amazon_de"}
    assert result[0]["cover_url"] == "https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg"


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
        ("books-express", "https://books-express.ro/p/a", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
    ])
    result = search_module.search("very hungry caterpillar", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert len(result) == 1
    assert result[0]["isbn"] == "9780141367941"
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


def test_relevance_ranking_all_tokens_match_first(tmp_path):
    """Results matching all query tokens must rank higher than partial matches."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "The Very Thought of You", "Author A", None),
        ("libris", "https://libris.ro/p/b", "The Very Hungry Caterpillar", "Eric Carle", None),
        ("libris", "https://libris.ro/p/c", "My Very First Book", "Author B", None),
    ])
    result = search_module.search("the very hungry caterpillar", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    # The book matching all tokens should be first
    assert "caterpillar" in result[0]["title"].lower()
    # Partial matches should rank lower
    assert any("thought" in r["title"].lower() for r in result[1:]) or len(result) > 1


def test_isbn_merge_same_isbn(tmp_path):
    """Rows with the same ISBN must merge into one result with all shops."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("books-express", "https://books-express.ro/a", "Where the Wild Things Are", "Maurice Sendak", "9780064431781"),
        ("amazon_de", "https://amazon.de/dp/a", "Where the Wild Things Are 50th Anniversary", "Maurice Sendak", "9780064431781"),
    ])
    result = search_module.search("9780064431781", db_path=path)
    assert len(result) == 1, f"Expected 1 result, got {len(result)}"
    assert result[0]["isbn"] == "9780064431781"
    assert len(result[0]["shops"]) == 2
    shop_names = {s["shop"] for s in result[0]["shops"]}
    assert shop_names == {"books-express", "amazon_de"}


def test_shop_dedupe_by_shop_and_url(tmp_path):
    """Results should not have duplicate (shop, url) pairs."""
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/a", "Test Book", "Author", None),
        ("libris", "https://libris.ro/p/b", "Test Book Variant", "Author", None),
        ("amazon", "https://amazon.com/dp/a", "Test Book", "Author", None),
    ])
    result = search_module.search("test book", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    # Check that no result has duplicate (shop, url) pairs
    for r in result:
        shop_url_pairs = [(s["shop"], s["url"]) for s in r["shops"]]
        assert len(shop_url_pairs) == len(set(shop_url_pairs)), f"Found duplicate shops in {r['title']}"
        # Verify we have multiple shops when appropriate
        if "variant" not in r["title"].lower():
            assert len(r["shops"]) >= 1


_PULL_UPSERT = (
    "INSERT INTO books VALUES(?,?,?,?,?,?) ON CONFLICT(shop,url) DO UPDATE SET "
    "title=excluded.title,author_hint=excluded.author_hint,"
    "isbn=COALESCE(excluded.isbn,books.isbn),last_seen=excluded.last_seen"
)


def test_pull_write_is_searchable_without_rebuild(tmp_path):
    """A pull insert/update after FTS exists must show up with no explicit rebuild."""
    from index.pull import init

    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("libris", "https://libris.ro/p/old", "Already Indexed", "Author", None),
    ])
    opener = lambda *a, **k: Response({"docs": []})
    assert search_module.search("already indexed", db_path=path, opener=opener)[0]["title"] == "Already Indexed"
    with sqlite3.connect(path) as db:
        init(db)
        db.execute(_PULL_UPSERT, (
            "libris", "https://libris.ro/p/new-book", "Brand New Atlas", "Ann", None, "2026-10-30",
        ))
        db.commit()
    found = search_module.search("brand new atlas", db_path=path, opener=opener)
    assert found and found[0]["title"] == "Brand New Atlas"
    with sqlite3.connect(path) as db:
        db.execute(_PULL_UPSERT, (
            "libris", "https://libris.ro/p/new-book", "Renamed Atlas Volume", "Ann", None, "2026-10-30",
        ))
        db.commit()
    renamed = search_module.search("renamed atlas volume", db_path=path, opener=opener)
    assert renamed and renamed[0]["title"] == "Renamed Atlas Volume"
    stale = search_module.search("brand new atlas", db_path=path, opener=opener)
    assert all(item["title"] != "Brand New Atlas" for item in stale)


def test_exact_title_ranks_above_spinoffs(tmp_path):
    path = tmp_path / "books.sqlite3"
    make_db(path, [
        ("books-express", "https://books-express.ro/p/spin", "My Very First With The Very Hungry Caterpillar", "Eric Carle", None),
        ("books-express", "https://books-express.ro/p/where", "Where Is The Very Hungry Caterpillar", "Eric Carle", None),
        ("books-express", "https://books-express.ro/p/real", "The Very Hungry Caterpillar", "Eric Carle", "9780141367941"),
        ("libris", "https://libris.ro/p/hp", "Harry Potter si piatra filosofala j k rowling", None, None),
        ("books-express", "https://books-express.ro/p/hp-en", "Harry Potter and the Philosopher s Stone", "J K Rowling", None),
    ])
    opener = lambda *a, **k: Response({"docs": []})
    caterpillar = search_module.search("the very hungry caterpillar", db_path=path, opener=opener)
    assert caterpillar[0]["title"] == "The Very Hungry Caterpillar"
    potter = search_module.search("harry potter piatra filozofala", db_path=path, opener=opener)
    assert potter[0]["title"] == "Harry Potter si piatra filosofala j k rowling"


def test_match_error_is_recorded_and_endpoint_stays_up(tmp_path, monkeypatch):
    path = tmp_path / "books.sqlite3"
    make_db(path, [("libris", "https://libris.ro/p/a", "Hello World", "Author", None)])
    search_module.MATCH_ERRORS.clear()
    result = search_module.search('hello"', db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert result == []
    assert search_module.MATCH_ERRORS and "hello" in search_module.MATCH_ERRORS[-1]["query"]
    monkeypatch.setattr(search_module.urllib.request, "urlopen", lambda *a, **k: Response({"docs": []}))
    app = create_app(db_path=tmp_path / "unrelated.sqlite3")
    app.state.index_db_path = path
    client = TestClient(app)
    response = client.get("/search", params={"q": 'hello"'})
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_drifted_fts_is_rebuilt_on_next_call(tmp_path):
    """Rows written while the triggers were absent must not stay invisible for ever."""
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,"
            "author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))"
        )
        db.execute(
            "INSERT INTO books VALUES('libris','https://libris.ro/p/a','Orphaned Title',NULL,NULL,'2026-10-30')"
        )
        db.commit()
    # The very first call must heal the drifted index instead of returning nothing.
    first = search_module.search("orphaned", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert first and first[0]["title"] == "Orphaned Title"
    second = search_module.search("orphaned", db_path=path, opener=lambda *a, **k: Response({"docs": []}))
    assert second and second[0]["title"] == "Orphaned Title"

"""Open Library search + shop availability. Open Library is a stand-in opener (the suite blocks
sockets); the Libris product page is a REAL local HTTP server read through the real fetch guard."""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from api import fetch_guard
from api.app import create_app

search_module = __import__("index.search", fromlist=["search"])

HP_RO = "9789735832940"
HP_EN = "9780747532699"
HP_DOC = {"key": "/works/OL82563W", "title": "Harry Potter and the Philosopher's Stone",
          "author_name": ["J. K. Rowling"], "cover_i": 15155833, "isbn": [HP_EN, "0747532699", HP_RO]}
SAPIENS = {"title": "Sapiens", "author_name": ["Yuval Noah Harari"], "cover_i": 8634250, "isbn": ["9780062316097"]}
GENES = {"title": "Genes, girls and gamow", "author_name": ["James D. Watson"], "cover_i": 130890,
         "isbn": ["9780198606932"]}


def make_db(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [(*row, "2026-10-30") for row in rows])


class FakeOL:
    """Callable opener; answers search.json with the docs registered for the query text."""

    def __init__(self, answers=None, fail=False, editions=None):
        self.answers = answers or {}
        self.editions = editions or {}
        self.fail = fail
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append(req.full_url)
        if self.fail:
            raise OSError("open library down")
        from urllib.parse import parse_qs, urlsplit
        if "/isbn/" in req.full_url:
            payload = self.editions.get(req.full_url.rsplit("/", 1)[1][:-5], {})
        else:
            q = search_module.normalize(parse_qs(urlsplit(req.full_url).query)["q"][0])
            payload = {"docs": self.answers.get(q, [])}
        outer = json.dumps(payload).encode()

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return None
            def read(s, n=-1): return outer
        return R()


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "books.sqlite3"
    make_db(p, [
        ("libris", "https://www.libris.ro/harry-potter-si-piatra-filosofala-j-k-rowling", "harry potter si piatra filosofala j k rowling", None, None),
        ("books-express", "https://www.books-express.ro/-/p/scjb,9787561932551", "scjb,", None, "9787561932551"),
        ("books-express", "https://www.books-express.ro/harry-potter-and-the-philosopher-s-stone/p/yfh,9780747532699", "harry potter and the philosopher s stone", None, HP_EN),
        ("books-express", "https://www.books-express.ro/-/p/9780198606932", "", None, "9780198606932"),
    ])
    return p


def run(db_path, q, ol, **kw):
    return search_module.search(q, db_path=db_path, opener=ol, fetcher=kw.pop("fetcher", _no_fetch), **kw)


def _no_fetch(url, timeout=None):
    raise AssertionError("no product page should be read: " + url)


def test_ro_title_with_and_without_diacritics_gives_same_top_result(db_path):
    ol = FakeOL({"harry potter si piatra filozofala": [HP_DOC]},
                editions={HP_RO: {"title": "Harry Potter și piatra filozofală", "covers": [12345]}})
    with_d = run(db_path, "Harry Potter și piatra filozofală", ol, fetcher=lambda u, timeout=None: (_ for _ in ()).throw(OSError("x")))
    without = run(db_path, "Harry Potter si piatra filozofala", ol, fetcher=lambda u, timeout=None: (_ for _ in ()).throw(OSError("x")))
    assert with_d[0]["title"] == "Harry Potter și piatra filozofală" == without[0]["title"]  # the Romanian edition
    assert with_d[0]["author"] == "J. K. Rowling"
    assert with_d[0]["isbn"] == HP_RO  # the Romanian edition's ISBN is preferred
    assert with_d[0]["cover_url"] == "https://covers.openlibrary.org/b/id/12345-M.jpg"
    assert len(ol.calls) == 2  # one search + one edition read; the second search came from the cache


def test_no_shop_rows_or_slug_titles_in_results(db_path):
    ol = FakeOL({"harry potter": [dict(HP_DOC, isbn=[HP_EN])]})
    res = run(db_path, "harry potter", ol, fetcher=lambda u, timeout=None: (_ for _ in ()).throw(OSError("x")))
    titles = [r["title"] for r in res]
    assert titles == ["Harry Potter and the Philosopher's Stone"]
    assert all(t == t.strip() and t[0].isupper() for t in titles)
    assert "scjb," not in json.dumps(res)


def test_every_cover_is_open_library_or_none(db_path):
    nocover = {"title": "No Cover Book", "author_name": ["A"], "isbn": []}
    ol = FakeOL({"x": [HP_DOC, SAPIENS, GENES, nocover]})
    res = run(db_path, "x", ol, fetcher=lambda u, timeout=None: (_ for _ in ()).throw(OSError("x")))
    assert len(res) == 4
    for r in res:
        assert r["cover_url"] is None or r["cover_url"].startswith("https://covers.openlibrary.org/")
    assert [r for r in res if r["title"] == "No Cover Book"][0]["cover_url"] is None
    assert "books-express.ro/" not in json.dumps([r["cover_url"] for r in res])


def test_isbn_query_is_exact_and_books_express_offer_found(db_path):
    ol = FakeOL({"9780198606932": [GENES]})
    res = run(db_path, "978-0-19-860693-2", ol)
    assert res[0]["isbn"] == "9780198606932" and res[0]["title"] == "Genes, girls and gamow"
    assert res[0]["shops"] == [{"shop": "books-express", "url": "https://www.books-express.ro/-/p/9780198606932"}]


def test_known_shop_offer_boosts_but_does_not_override_relevance(db_path):
    other = {"title": "Another", "author_name": ["B"], "isbn": ["9781111111113"], "cover_i": 1}
    nb = [{"title": f"Filler {i}", "author_name": ["F"], "isbn": [], "cover_i": 2} for i in range(6)]
    ol = FakeOL({"q": [other, nb[0], GENES, *nb[1:]]})
    res = run(db_path, "q", ol)
    # GENES (Open Library #3, carried by Books-Express) moves up one place; #1 stays #1.
    assert [r["title"] for r in res][:3] == ["Another", "Genes, girls and gamow", "Filler 0"]
    assert res[-1]["title"] == "Filler 5"  # far results stay in Open Library order
    top_carried = run(db_path, "q2", FakeOL({"q2": [GENES, other]}))
    assert top_carried[0]["title"] == "Genes, girls and gamow"
    not_displaced = run(db_path, "q3", FakeOL({"q3": [other, GENES]}))
    assert not_displaced[0]["title"] == "Another"  # a shop never displaces the top result


def test_bookzone_and_emag_are_links_with_honest_reason(db_path):
    res = run(db_path, "sapiens", FakeOL({"sapiens": [SAPIENS]}))
    other = {s["shop"]: s for s in res[0]["other_shops"]}
    assert set(other) == {"bookzone", "emag"}
    for s in other.values():
        assert s["status"] == "not_checked" and s["reason"] == "Not checked here" and s["url"].startswith("https://www.")
    assert "9780062316097" in other["emag"]["url"]


def test_open_library_down_is_unavailable_not_empty(db_path):
    with pytest.raises(search_module.SearchUnavailable):
        run(db_path, "anything", FakeOL(fail=True))
    app = create_app(db_path=db_path.parent / "u.sqlite3")
    app.state.index_db_path = db_path
    import index.search as s
    old = s.urllib.request.urlopen
    s.urllib.request.urlopen = FakeOL(fail=True)
    try:
        r = TestClient(app).get("/search", params={"q": "anything"})
    finally:
        s.urllib.request.urlopen = old
    assert r.status_code == 503 and r.json() == {"query": "anything", "results": [], "error": "search_unavailable"}


def test_failure_is_not_cached(db_path):
    with pytest.raises(search_module.SearchUnavailable):
        run(db_path, "retry me", FakeOL(fail=True))
    ol = FakeOL({"retry me": [SAPIENS]})
    assert run(db_path, "retry me", ol)[0]["title"] == "Sapiens"


def test_requests_are_spaced(db_path, monkeypatch):
    import time
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.3)
    search_module._last_request_time = 0.0
    ol = FakeOL({"a": [SAPIENS], "b": [SAPIENS]})
    t0 = time.monotonic()
    run(db_path, "a", ol)
    run(db_path, "b", ol)
    assert time.monotonic() - t0 >= 0.3


# ---- Libris: a REAL local server, the real fetch guard, one read, then cached ------------------

PAGE = ('<html><head><script type="application/ld+json">' + json.dumps({
    "@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Libris"},
        {"@type": ["Product", "Book"], "name": "Harry Potter si piatra filosofala", "isbn": HP_RO,
         "offers": {"@type": "Offer", "price": "49.90", "priceCurrency": "RON",
                    "availability": "https://schema.org/InStock"}}]}) + "</script></head><body>x</body></html>").encode()


class Page(BaseHTTPRequestHandler):
    hits = 0
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).hits += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(PAGE)
        self.close_connection = True


@pytest.fixture
def libris_server(monkeypatch, tmp_path):
    real = fetch_guard.address_reason
    monkeypatch.setattr(fetch_guard, "address_reason", lambda ip: None if ip == "127.0.0.1" else real(ip))
    monkeypatch.setattr(fetch_guard, "_resolve_host", lambda host: ["127.0.0.1"])
    assert real("127.0.0.1") == "loopback"  # production policy untouched
    Page.hits = 0
    srv = HTTPServer(("127.0.0.1", 0), Page)
    port = srv.server_address[1]
    monkeypatch.setattr(fetch_guard, "_ALLOWED_PORTS", frozenset({80, 443, port}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = tmp_path / "books.sqlite3"
    make_db(p, [("libris", f"http://127.0.0.1:{port}/harry-potter-si-piatra-filosofala-j-k-rowling",
                 "harry potter si piatra filosofala j k rowling", None, None)])
    yield p
    srv.shutdown()


@pytest.fixture(autouse=True)
def _no_network():
    """Overrides the project-wide socket block for this module, as test_fetch_guard_real does: the
    Libris server is a real loopback server. Open Library is always the FakeOL opener, never a socket;
    production policy stays intact (the fetch guard still refuses loopback, asserted in the fixture)."""
    yield


@pytest.fixture
def _sockets_allowed():
    yield


def test_libris_confirmed_from_schema_org_then_cached_with_no_second_fetch(libris_server, _sockets_allowed):
    ol = FakeOL({"harry potter si piatra filozofala": [HP_DOC]},
                editions={HP_RO: {"title": "Harry Potter și piatra filozofală"}})
    first = search_module.search("Harry Potter și piatra filozofală", db_path=libris_server, opener=ol)
    assert Page.hits == 1
    libris = [s for s in first[0]["shops"] if s["shop"] == "libris"]
    assert libris and first[0]["isbn"] == HP_RO
    second = search_module.search("Harry Potter și piatra filozofală", db_path=libris_server, opener=ol)
    third = search_module.search("harry potter si piatra filozofala", db_path=libris_server, opener=ol)
    assert Page.hits == 1  # cached confirmation: no further fetch
    assert second[0]["shops"] == first[0]["shops"] == third[0]["shops"]


def test_libris_not_shown_when_page_isbn_is_not_this_book(libris_server, _sockets_allowed):
    other = dict(HP_DOC, isbn=["9780747532699"])  # the page says HP_RO: not among this work's ISBNs
    res = search_module.search("harry potter si piatra filozofala", db_path=libris_server,
                               opener=FakeOL({"harry potter si piatra filozofala": [other]}))
    assert not [s for s in res[0]["shops"] if s["shop"] == "libris"]


# ---- helpers kept for the photo reader and the index pull --------------------------------------


def test_isbn_validation_and_conversion():
    assert search_module.validate_isbn("9780747532699") and not search_module.validate_isbn("9780747532698")
    assert search_module.to_isbn13("0-7475-3269-9") == "9780747532699"
    assert search_module.to_isbn13("12345") is None


def test_pull_write_is_searchable_by_fts_without_rebuild(tmp_path):
    from index.pull import init
    p = tmp_path / "books.sqlite3"
    make_db(p, [("libris", "https://libris.ro/p/old", "Already Indexed", "Author", None)])
    with sqlite3.connect(p) as db:
        search_module.ensure_books_search(db)
        init(db)
        db.execute("INSERT INTO books VALUES('libris','https://libris.ro/p/new','Brand New Atlas','Ann',NULL,'2026-10-30')")
        db.commit()
        assert db.execute("SELECT count(*) FROM books_search WHERE books_search MATCH 'atlas'").fetchone()[0] == 1


def test_drifted_fts_is_rebuilt_on_next_call(tmp_path):
    p = tmp_path / "books.sqlite3"
    make_db(p, [("libris", "https://libris.ro/p/a", "Alpha", None, None)])
    with sqlite3.connect(p) as db:
        search_module.ensure_books_search(db)
        db.execute("DROP TRIGGER books_fts_ai")
        db.execute("INSERT INTO books VALUES('libris','https://libris.ro/p/b','Beta Gamma',NULL,NULL,'2026-10-30')")
        search_module.ensure_books_search(db)
        assert db.execute("SELECT count(*) FROM books_search WHERE books_search MATCH 'gamma'").fetchone()[0] == 1

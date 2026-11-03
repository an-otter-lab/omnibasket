"""Search when Open Library is down or slow (3 Nov): the shop index answers instead of a 503, and
the network waits run together behind one deadline. Open Library and Libris are stand-ins; no socket."""
import json
import sqlite3
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

search_module = __import__("index.search", fromlist=["search"])

SAPIENS_EN = "9780099590088"
SAPIENS_GRAPHIC = "9780063212237"
HP_RO = "9789735832940"
HP_EN = "9780747532699"
MATILDA = {"key": "/works/OL45883W", "title": "Matilda", "author_name": ["Roald Dahl"], "cover_i": 1,
           "isbn": ["9780142410370"]}


def make_db(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES(?,?,?,?,?,?)", [(*row, "2026-11-03") for row in rows])


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "books.sqlite3"
    make_db(p, [
        ("books-express", "https://www.books-express.ro/a/p/1", "sapiens a brief history of humankind", "Yuval Noah Harari", SAPIENS_EN),
        ("books-express", "https://www.books-express.ro/a/p/1b", "sapiens a brief history of humankind", None, "9781846558238"),
        ("books-express", "https://www.books-express.ro/a/p/1c", "sapiens a brief history of humankind", None, "9780771038518"),
        ("books-express", "https://www.books-express.ro/b/p/2", "sapiens a graphic history volume", None, SAPIENS_GRAPHIC),
        ("books-express", "https://www.books-express.ro/c/p/3", "sapiens reinvented", None, "9781944927134"),
        ("books-express", "https://www.books-express.ro/d/p/4", "the subtle art of not giving a f ck sapiens", None, "9780062457714"),
        ("books-express", "https://www.books-express.ro/e/p/5", "sapiens in chinese", None, "9787508647357"),
        ("books-express", "https://www.books-express.ro/f/p/6", "harry potter and the philosopher s stone", None, HP_EN),
        ("elefant", "https://www.elefant.ro/micul-print", "micul print", None, None),
        ("libris", "https://www.libris.ro/harry-potter-si-piatra-filosofala-j-k-rowling", "harry potter si piatra filosofala j k rowling", None, None),
    ])
    return p


def settle():
    """Wait for the requests a search stopped waiting for (they still run and cache their answer)."""
    for fut in list(search_module._inflight.values()):
        try:
            fut.result(timeout=5)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.0)
    yield
    settle()  # nothing of this test runs on after it


class OL:
    """Open Library stand-in: search answers per query, editions per ISBN, an optional delay or failure."""

    def __init__(self, answers=None, editions=None, fail=False, delay=0.0, edition_delay=0.0):
        self.answers, self.editions = answers or {}, editions or {}
        self.fail, self.delay, self.edition_delay = fail, delay, edition_delay
        self.calls, self.started = [], []
        self.lock = threading.Lock()

    def __call__(self, req, timeout=None):
        with self.lock:
            self.calls.append(req.full_url)
            self.started.append(time.monotonic())
        edition = "/isbn/" in req.full_url
        time.sleep(self.edition_delay if edition else self.delay)
        if self.fail:
            raise OSError("open library down")
        if edition:
            payload = self.editions.get(req.full_url.rsplit("/", 1)[1][:-5], {})
        else:
            q = search_module.normalize(parse_qs(urlsplit(req.full_url).query)["q"][0])
            payload = {"docs": self.answers.get(q, [])}
        body = json.dumps(payload).encode()

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return None
            def read(s, n=-1): return body
        return R()


def no_fetch(url, timeout=None):
    raise AssertionError("no Libris read expected")


def run(db_path, q, ol, fetcher=no_fetch, **kw):
    return search_module.search(q, db_path=db_path, opener=ol, fetcher=fetcher, **kw)


# ---- fallback ------------------------------------------------------------------------------------

def test_open_library_down_answers_from_the_shop_index_with_the_same_shape(db_path):
    res = run(db_path, "sapiens", OL(fail=True), fallback=True)
    # One row per title (the best-scored printing); a title listed in several printings comes first.
    assert [r["isbn"] for r in res] == [SAPIENS_EN, "9781944927134", SAPIENS_GRAPHIC]
    top = res[0]
    assert set(top) == {"title", "author", "isbn", "cover_url", "shops", "other_shops", "source"}
    assert top["title"] == "Sapiens a brief history of humankind" and top["author"] == "Yuval Noah Harari"
    assert top["source"] == "shop_listings" and top["shops"] == []  # Books-Express rows are no "found at"
    assert top["cover_url"] == f"https://covers.openlibrary.org/b/isbn/{SAPIENS_EN}-M.jpg"
    assert {s["shop"] for s in top["other_shops"]} == {"bookzone", "emag"}


def test_fallback_keeps_the_search_rules(db_path):
    isbns = [r["isbn"] for r in run(db_path, "sapiens", OL(fail=True), fallback=True)]
    assert "9780062457714" not in isbns  # profanity hidden, as for catalogue results
    assert "9787508647357" not in isbns  # a printing not sold here (978-7)
    assert run(db_path, "harry potter philosopher", OL(fail=True), fallback=True)[0]["title"] == \
        "Harry potter and the philosopher's stone"


def test_open_library_too_slow_answers_from_the_index_by_the_deadline_and_caches_the_late_answer(db_path, monkeypatch):
    monkeypatch.setattr(search_module, "OL_SEARCH_SECONDS", 0.2)
    ol = OL({"matilda": [MATILDA]}, delay=0.6)
    t0 = time.monotonic()
    with pytest.raises(search_module.SearchUnavailable):
        run(db_path, "matilda", ol, fallback=True)  # the index has no Matilda with an ISBN
    assert time.monotonic() - t0 < 0.5
    settle()
    res = run(db_path, "matilda", ol, fallback=True)
    assert res[0]["isbn"] == "9780142410370" and "source" not in res[0]
    assert len(ol.calls) == 1  # the late answer served the second search


def test_earlier_open_library_answers_come_before_the_shop_rows(db_path):
    ol = OL({"sapiens yuval noah harari": [{"key": "/works/OL1W", "title": "Sapiens", "author_name": ["Yuval Noah Harari"],
                                              "cover_i": 7, "isbn": ["9780062316097"]}]})
    run(db_path, "sapiens yuval noah harari", ol)
    res = run(db_path, "sapiens", OL(fail=True), fallback=True)
    assert res[0]["isbn"] == "9780062316097" and res[0]["title"] == "Sapiens" and "source" not in res[0]
    assert res[0]["cover_url"] == "https://covers.openlibrary.org/b/id/7-M.jpg"


def test_earlier_answers_that_are_all_filtered_out_leave_it_to_the_index(db_path):
    run(db_path, "harari", OL({"harari": [{"key": "/works/OL2W", "title": "The Subtle Art of Not Giving a F*ck",
                                           "author_name": ["Mark Manson"], "isbn": ["9780062457714"]}]}))
    # The cached work is hidden (profanity) and so is the shop row: a 503, never an empty 200.
    with pytest.raises(search_module.SearchUnavailable):
        run(db_path, "subtle art", OL(fail=True), fallback=True)


def test_a_stale_answer_beats_the_index(db_path):
    ol = OL({"sapiens": [{"key": "/works/OL1W", "title": "Sapiens", "author_name": ["Yuval Noah Harari"], "isbn": ["9780062316097"]}]})
    run(db_path, "sapiens", ol)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE ol_search_cache SET cached_at = cached_at - 2 * 86400")
    down = OL(fail=True)
    assert run(db_path, "sapiens", down)[0]["isbn"] == "9780062316097"  # even without the fallback flag
    assert len(down.calls) == 1  # asked first: a stale answer is not fresh


def test_isbn_query_falls_back_to_the_index_row_or_an_empty_list(db_path):
    res = run(db_path, SAPIENS_EN, OL(fail=True), fallback=True)
    assert [(r["isbn"], r["source"]) for r in res] == [(SAPIENS_EN, "shop_listings")]
    assert run(db_path, "9780141365466", OL(fail=True), fallback=True) == []  # the box keeps the ISBN itself


def test_without_the_flag_the_other_callers_still_see_unavailable(db_path):
    with pytest.raises(search_module.SearchUnavailable):
        run(db_path, "sapiens", OL(fail=True))


def test_route_answers_200_from_the_index_and_503_only_when_it_has_nothing(db_path, monkeypatch):
    app = create_app(db_path=db_path.parent / "u.sqlite3")
    app.state.index_db_path = db_path
    monkeypatch.setattr(search_module, "_ol_open", OL(fail=True))
    monkeypatch.setattr(search_module, "LIBRIS_READS", 0)
    client = TestClient(app)
    r = client.get("/search", params={"q": "sapiens"})
    assert r.status_code == 200 and r.json()["results"][0]["source"] == "shop_listings"
    r = client.get("/search", params={"q": "micul print"})  # only ISBN-less Elefant rows
    assert r.status_code == 503 and r.json()["error"] == "search_unavailable"


# ---- one deadline, concurrent waits ---------------------------------------------------------------

def _ro_isbn(i):
    body = f"978973{i:06d}"
    check = (10 - sum(int(c) * (1 if k % 2 == 0 else 3) for k, c in enumerate(body)) % 10) % 10
    return body + str(check)


def test_editions_are_asked_together_and_waited_for_until_the_deadline(db_path, monkeypatch):
    docs = [{"key": f"/works/OL{i}W", "title": f"Book {i}", "author_name": ["A"], "isbn": [_ro_isbn(i)]} for i in range(3)]
    editions = {_ro_isbn(i): {"title": f"Cartea {i}"} for i in range(3)}
    ol = OL({"book": docs}, editions=editions, edition_delay=0.3)
    t0 = time.monotonic()
    res = run(db_path, "book", ol)
    assert time.monotonic() - t0 < 0.8  # three 0.3 s lookups, together
    assert {r["title"] for r in res} == {"Cartea 0", "Cartea 1", "Cartea 2"}

    monkeypatch.setattr(search_module, "SEARCH_SECONDS", 0.1)
    nine = {"key": "/works/OL9W", "title": "Book Nine", "author_name": ["A"], "isbn": [_ro_isbn(9)]}
    slow = OL({"book two": [nine]}, editions={_ro_isbn(9): {"title": "Late"}}, edition_delay=0.6)
    t0 = time.monotonic()
    res = run(db_path, "book two", slow)
    assert time.monotonic() - t0 < 0.45
    assert res[0]["title"] == "Book Nine"  # the edition came too late for this search
    settle()
    assert run(db_path, "book two", slow)[0]["title"] == "Late"  # cached for the next one
    assert sum("/isbn/" in c for c in slow.calls) == 1


def test_parallel_requests_still_keep_the_polite_interval(db_path, monkeypatch):
    monkeypatch.setattr(search_module, "MIN_REQUEST_INTERVAL", 0.15)
    docs = [{"key": f"/works/OL{i}W", "title": f"Book {i}", "author_name": ["A"], "isbn": [_ro_isbn(i)]} for i in range(3)]
    ol = OL({"book": docs}, editions={_ro_isbn(i): {"title": f"Cartea {i}"} for i in range(3)})
    run(db_path, "book", ol)
    gaps = [b - a for a, b in zip(sorted(ol.started), sorted(ol.started)[1:])]
    assert len(ol.started) == 4 and min(gaps) >= 0.14


class Page:
    def __init__(self, isbn):
        self.status = 200
        self.text = ('<script type="application/ld+json">' + json.dumps({"@type": "Book", "isbn": isbn}) + "</script>")


def test_a_late_libris_read_is_cached_and_never_read_twice(db_path, monkeypatch):
    monkeypatch.setattr(search_module, "SEARCH_SECONDS", 0.2)
    doc = {"key": "/works/OL82563W", "title": "Harry Potter si piatra filosofala", "author_name": ["J. K. Rowling"],
           "isbn": [HP_RO]}
    ol = OL({"harry potter": [doc]})
    reads = []

    def slow_fetch(url, timeout=None):
        reads.append(url)
        time.sleep(0.5)
        return Page(HP_RO)

    t0 = time.monotonic()
    first = run(db_path, "harry potter", ol, fetcher=slow_fetch)
    assert time.monotonic() - t0 < 0.45 and first[0]["shops"] == []  # not back by the deadline
    second = run(db_path, "harry potter", ol, fetcher=slow_fetch)  # while the read is in flight
    assert second[0]["shops"] == []
    settle()
    third = run(db_path, "harry potter", ol, fetcher=slow_fetch)
    assert [s["shop"] for s in third[0]["shops"]] == ["libris"]
    assert len(reads) == 1  # one attempt per page, shared and then cached


# ---- the kept-alive Open Library connection ------------------------------------------------------

class FakeConn:
    made = []

    def __init__(self, host, timeout=None):
        self.host, self.sock, self.requests, self.closed = host, None, [], False
        self.script = list(FakeConn.next_script)
        FakeConn.made.append(self)

    def request(self, method, path, headers=None):
        self.requests.append((method, path, headers))

    def getresponse(self):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        status, location, body = step

        class Res:
            will_close = False
            def __init__(s): s.status = status
            def read(s, n=-1): return body
            def getheader(s, name): return location if name == "Location" else None
        return Res()

    def close(self):
        self.closed = True


@pytest.fixture
def fake_conn(monkeypatch):
    FakeConn.made = []
    monkeypatch.setattr(search_module.http.client, "HTTPSConnection", FakeConn)
    monkeypatch.setattr(search_module, "_idle", [])
    return FakeConn


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": search_module.UA})
    with search_module._ol_open(req, timeout=1) as r:
        return r.read()


def test_one_connection_serves_requests_and_redirects(fake_conn):
    fake_conn.next_script = [(302, "/books/OL1M.json", b""), (200, None, b'{"title": "x"}'), (200, None, b"{}")]
    assert _get("https://openlibrary.org/isbn/9789735832940.json") == b'{"title": "x"}'
    assert _get("https://openlibrary.org/search.json?q=a") == b"{}"
    assert len(fake_conn.made) == 1
    paths = [p for _m, p, _h in fake_conn.made[0].requests]
    assert paths == ["/isbn/9789735832940.json", "/books/OL1M.json", "/search.json?q=a"]
    assert fake_conn.made[0].requests[0][2]["User-agent"] == search_module.UA


def test_a_stale_kept_connection_is_replaced_once_and_errors_raise(fake_conn):
    import http.client

    fake_conn.next_script = [(200, None, b"{}"), http.client.RemoteDisconnected("gone")]
    _get("https://openlibrary.org/search.json?q=a")
    fake_conn.next_script = [(503, None, b"busy")]
    with pytest.raises(OSError):
        _get("https://openlibrary.org/search.json?q=b")  # stale socket, then a fresh one that answers 503
    assert len(fake_conn.made) == 2 and fake_conn.made[0].closed
    with pytest.raises(OSError):
        _get("https://example.org/search.json")  # never anything but Open Library

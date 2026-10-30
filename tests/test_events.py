"""GET /events?source=live: query params, store set, payload shape, solve join.

Fixtures and mocks only. No test opens a socket.
"""

import json
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.cache import PageCache
from api.fetch_guard import GuardedFetch
from api.offers import default_live_stores

GHICI = "9786068996011"
HARRY = "9780747532699"  # valid check digit, not in the basket


def _html(isbn, price):
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps({"@type": "Product", "isbn": isbn, "offers": {"price": price, "priceCurrency": "RON"}})
        + "</script></head><body>" + price + " lei</body></html>"
    )


def _index(store_id, isbn):
    return {
        "libris": "https://www.libris.ro/carte/x/1",
        "bookzone": "https://bookzone.ro/produs/x",
        "emag": "https://www.emag.ro/x/pd/ABC/",
        "books_express": "https://www.books-express.ro/x/p/y,%s" % isbn,
    }.get(store_id)


def _client(tmp_path):
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _parse(body):
    out = []
    for block in body.strip().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            out.append((name, data))
    return out


def _live(client, **params):
    def fetch(url):
        html = _html(params["isbn13"], "40.00")
        return GuardedFetch(url, 200, "text/html", html.encode(), html, 0)

    with patch("api.offers.fetch", side_effect=fetch), patch("api.offers.lookup_product_url", side_effect=_index):
        return client.get("/events", params={"source": "live", **params})


def test_non_ghici_isbn_is_read_joined_and_solved(tmp_path):
    """Fails if the route still reads the hard-wired Ghici book."""
    res = _live(_client(tmp_path), isbn13=HARRY, item_id="hp", title="Harry Potter")
    assert res.status_code == 200
    events = _parse(res.text)
    assert events[-1][0] == "solution"
    sol = events[-1][1]
    assert sol["joined_item_id"] == "hp"
    assert sol["joined_title"] == "Harry Potter"
    assert sol["joined_isbn13"] == HARRY
    assert any(row["item_id"] == "hp" for row in sol["assignment"])
    assert sol["total_cents"] != 51516  # the basket grew
    assert all(r["isbn13"] == HARRY for n, r in events if n == "read_progress")
    assert GHICI not in res.text


def test_read_progress_payload_shape_and_labels(tmp_path):
    res = _live(_client(tmp_path), isbn13=HARRY)
    progress = [d for n, d in _parse(res.text) if n == "read_progress"]
    assert progress
    for row in progress:
        assert set(row) == {"store_id", "isbn13", "status", "message"}
    messages = {row["message"] for row in progress}
    assert "Reading Libris\u2026" in messages
    assert "Reading Books-Express\u2026" in messages
    assert "Amazon.de: not read live" in messages


def test_invalid_isbn_is_rejected_before_any_read(tmp_path):
    client = _client(tmp_path)
    with patch("api.offers.fetch") as fetch:
        bad = client.get("/events", params={"source": "live", "isbn13": "9786068996010"})
        missing = client.get("/events", params={"source": "live"})
    assert bad.status_code == 400 and missing.status_code == 400
    assert fetch.call_count == 0


def test_unknown_store_is_rejected(tmp_path):
    res = _client(tmp_path).get("/events", params={"source": "live", "isbn13": HARRY, "stores": "libris,nope"})
    assert res.status_code == 400
    assert "nope" in res.json()["error"]


def test_stores_param_limits_the_read(tmp_path):
    res = _live(_client(tmp_path), isbn13=HARRY, stores="libris")
    stores = {d["store_id"] for n, d in _parse(res.text) if n == "read_progress"}
    assert stores == {"libris"}


def test_default_store_set_comes_from_data_shops_and_has_books_express():
    """Fails if the default is a literal list that omits Books-Express."""
    stores = default_live_stores()
    assert "books_express" in stores
    assert {"libris", "bookzone", "emag", "amazon_de"} <= set(stores)
    assert "paste_only" not in stores


def test_post_solve_live_says_where_live_solving_happens(tmp_path):
    res = _client(tmp_path).post("/solve", params={"source": "live"})
    assert res.status_code == 400
    assert "/events" in res.json()["error"]


def test_muse_read_runs_off_the_event_loop_thread(tmp_path):
    """Fails if gap_fill_with_muse is called synchronously inside the async path."""
    from api.muse_integration import MuseResult

    seen = {}
    loop_thread = {}

    def slow_muse(text, schema):
        seen["thread"] = threading.current_thread().name
        return MuseResult()

    page = "<html><body>no structured data 40.00 lei</body></html>"

    def fetch(url):
        loop_thread["fetch"] = threading.current_thread().name
        return GuardedFetch(url, 200, "text/html", page.encode(), page, 0)

    cache = PageCache(tmp_path / "c.sqlite")
    from api.offers import read_offers_sync

    with patch("api.offers.fetch", side_effect=fetch), patch("api.offers.gap_fill_with_muse", side_effect=slow_muse):
        read_offers_sync(["libris"], HARRY, "hp", cache, index_lookup=_index)
    assert seen["thread"] != threading.main_thread().name

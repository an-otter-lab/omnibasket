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


ELEFANT_URL = "https://www.elefant.ro/harry-potter-paperback_0f0f0f0f-1111-4222-8333-444455556666"


def _page(url, isbn, price):
    """A schema.org page, or for Elefant (no JSON-LD) its own markup, at this price."""
    if "elefant.ro" in url:
        from tests.test_elefant import html as elefant_html

        lei, cents = price.split(".")
        text = elefant_html(barcode=isbn, price=f"{lei},{cents}&nbsp;lei", declared=price)
    else:
        text = _html(isbn, price)
    return GuardedFetch(url, 200, "text/html", text.encode(), text, 0)


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
        return _page(url, params["isbn13"], "40.00")

    with patch("api.offers.fetch", side_effect=fetch), patch("api.offers.lookup_product_url", side_effect=_index), patch(
        "api.offers.lookup_elefant_urls", return_value=[ELEFANT_URL]
    ):
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
    assert all(GHICI not in json.dumps(d) for n, d in events if n == "read_progress")
    assert sol["joined_isbn13"] != GHICI


def test_read_progress_payload_shape_and_labels(tmp_path):
    res = _live(_client(tmp_path), isbn13=HARRY)
    progress = [d for n, d in _parse(res.text) if n == "read_progress"]
    assert progress
    for row in progress:
        assert set(row) == {"store_id", "isbn13", "status", "message"}
    messages = {row["message"] for row in progress}
    assert "Reading Libris\u2026" in messages
    assert "Reading Elefant\u2026" in messages
    assert "Reading Books-Express\u2026" not in messages
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


def test_default_store_set_comes_from_data_shops_and_has_elefant():
    """Fails if the default is a literal list: Elefant is in it, Books-Express is retired (3 Nov)."""
    stores = default_live_stores()
    assert "elefant" in stores and "books_express" not in stores
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


def _priced_fetch(prices):
    def fetch(url):
        price = next(p for host, p in prices.items() if host in url)
        return _page(url, HARRY, price)

    return fetch


def _live_priced(client, prices, **params):
    with patch("api.offers.fetch", side_effect=_priced_fetch(prices)), patch(
        "api.offers.lookup_product_url", side_effect=_index
    ), patch("api.offers.lookup_elefant_urls", return_value=[ELEFANT_URL]):
        return client.get("/events", params={"source": "live", "isbn13": HARRY, **params})


def test_elefant_wins_when_it_is_cheaper_for_the_joined_book(tmp_path):
    """Fails if offers from shops outside the locked store list are still dropped."""
    prices = {"libris": "80.00", "bookzone": "90.00", "elefant": "30.00", "emag": "25.00"}
    res = _live_priced(_client(tmp_path), prices, item_id="hp", title="Harry Potter", stores="libris,bookzone,elefant,emag")
    sol = _parse(res.text)[-1][1]
    row = next(r for r in sol["assignment"] if r["item_id"] == "hp")
    assert row["store_id"] == "elefant"
    assert row["price_cents"] == 3000
    assert any(s["store_id"] == "elefant" for s in sol["stores"])
    # eMAG's fees are unprinted, so it is listed as excluded rather than priced.
    assert any(e["id"] == "emag" for e in sol["excluded_stores"])
    assert all(r["store_id"] != "emag" for r in sol["assignment"])


def test_joined_book_row_carries_title_and_isbn(tmp_path):
    """Fails if books[] shows the raw item id and a null ISBN."""
    res = _live(_client(tmp_path), isbn13=HARRY, item_id="hp", title="Harry Potter")
    sol = _parse(res.text)[-1][1]
    row = next(b for b in sol["books"] if b["item_id"] == "hp")
    assert row["title"] == "Harry Potter"
    assert row["isbn13"] == HARRY
    assert sol["joined_title"] == "Harry Potter" and sol["joined_isbn13"] == HARRY


def test_progress_labels_use_display_names(tmp_path):
    from api.offers import read_offers_parallel
    import asyncio

    messages = []

    async def cb(p):
        messages.append(p.message)

    cache = PageCache(tmp_path / "l.sqlite")

    def refuse(url):
        from api.fetch_guard import FetchRefused

        raise FetchRefused("read")

    page = _html(HARRY, "40.00")
    with patch("api.offers.fetch", side_effect=lambda url: GuardedFetch(url, 200, "text/html", page.encode(), page, 0)):
        asyncio.run(read_offers_parallel(["emag", "amazon_de"], HARRY, "hp", cache, cb, index_lookup=_index))
    with patch("api.offers.fetch", side_effect=refuse):
        asyncio.run(read_offers_parallel(["libris"], HARRY, "hp2", cache, cb, index_lookup=_index))
    # second pass on the first book is served from the page cache
    with patch("api.offers.fetch") as fetch:
        asyncio.run(read_offers_parallel(["libris"], HARRY, "hp", cache, cb, index_lookup=_index))
    assert "eMAG: read" in messages  # S9: "ok" is said in words, not as the raw status
    assert "Libris: read failed" in messages
    assert "Amazon.de: not read live" in messages
    assert "Reading Amazon.de\u2026" not in messages
    assert not any(m.startswith(("emag", "libris", "bookzone")) for m in messages)


def test_cache_hit_label(tmp_path):
    from api.offers import read_offers_sync
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cache = PageCache(tmp_path / "h.sqlite")
    day = datetime.now(ZoneInfo("Europe/Bucharest")).strftime("%Y-%m-%d")
    cache.put({"store_id": "libris", "isbn13": HARRY, "item_id": "hp", "day": day,
               "facts": {"title": "Harry", "isbn13": HARRY, "price_cents": 4000, "currency": "RON"},
               "model_json": None, "provenance": {}})
    import asyncio
    from api.offers import read_offers_parallel

    messages = []

    async def cb(p):
        messages.append(p.message)

    with patch("api.offers.fetch") as fetch:
        asyncio.run(read_offers_parallel(["libris"], HARRY, "hp", cache, cb, index_lookup=_index))
    assert messages == ["Libris: read from cache"]
    assert fetch.call_count == 0


def test_post_solve_live_with_a_body_gets_the_same_refusal(tmp_path):
    client = _client(tmp_path)
    plain = client.post("/solve", params={"source": "live"})
    body = client.post(
        "/solve",
        json={
            "source": "live",
            "stores": [{"id": "a", "currency": "RON", "free_shipping_threshold_cents": 100,
                        "shipping_fee_cents": 10, "per_order_fee_cents": 0}],
            "items": [{"id": "b", "offers": [{"store_id": "a", "price_cents": 100, "seller_certainty": "direct"}]}],
        },
    )
    assert plain.status_code == body.status_code == 400
    assert plain.json()["error"] == body.json()["error"]
    assert "GET /events?source=live&isbn13=" in body.json()["error"]


def test_ro_v1_locked_solve_is_untouched(tmp_path):
    """The sample basket stays 51516 / 55873 and is not changed by the live join code."""
    sol = _client(tmp_path).post("/solve", params={"source": "cache"}).json()
    assert sol["total_cents"] == 51516
    assert sol["single_store_baseline"]["total_cents"] == 55873
    from api.offers import solve_with_live_offers

    unchanged = solve_with_live_offers([], "none", None, None)
    assert unchanged["total_cents"] == 51516


def test_live_offers_expose_ranked_state_as_data(tmp_path):
    """eMAG is read but unranked with a stable reason; a priced Elefant offer is ranked."""
    prices = {"libris": "80.00", "bookzone": "90.00", "elefant": "30.00", "emag": "25.00"}
    res = _live_priced(
        _client(tmp_path), prices, item_id="hp", stores="libris,elefant,emag,amazon_de"
    )
    sol = _parse(res.text)[-1][1]
    rows = {r["store_id"]: r for r in sol["live_offers"]}

    emag = rows["emag"]
    assert emag["ranked"] is False
    assert emag["not_ranked_reason"] == "delivery_rules_not_read"
    assert emag["price_cents"] == 2500  # read and shown, just not priced
    assert emag["free_shipping_threshold_cents"] is None
    assert emag["shipping_fee_cents"] is None
    assert emag["per_order_fee_cents"] is None

    el = rows["elefant"]
    assert el["ranked"] is True
    assert "not_ranked_reason" not in el

    assert rows["amazon_de"]["ranked"] is False
    assert rows["amazon_de"]["not_ranked_reason"] == "not_read_live"
    assert "not ranked" not in res.text.lower().replace("not_ranked_reason", "")


def test_not_ranked_reasons_cover_the_honest_cases():
    from api.offers import OfferRead, not_ranked_reason

    priced = {"libris"}

    def row(**kw):
        return OfferRead(store_id=kw.pop("store_id", "libris"), isbn13=None, item_id="x", **kw)

    assert not_ranked_reason(row(status="ok", price_cents=100), priced, set()) is None
    assert not_ranked_reason(row(status="skipped", reason="no_match_in_index"), priced, set()) == "no_offer"
    assert not_ranked_reason(row(status="failed", reason="fetch_refused: timeout"), priced, set()) == "fetch_refused"
    assert not_ranked_reason(row(status="failed", reason="no_price_extracted"), priced, set()) == "no_price_extracted"
    assert not_ranked_reason(row(store_id="emag", status="ok", price_cents=100), priced, {"emag"}) == "delivery_rules_not_read"


MATILDA_RO = "9786303684956"
MATILDA_PAGE = "https://www.libris.ro/carte/matilda-roald-dahl/48068482"


def test_a_pasted_shop_page_is_read_as_that_shops_listing(tmp_path):
    """R3: the index has no entry for this ISBN, but the pasted Libris page is the listing."""
    fetched = []

    def fetch(url):
        fetched.append(url)
        html = _html(MATILDA_RO, "84.18")
        return GuardedFetch(url, 200, "text/html", html.encode(), html, 0)

    with patch("api.offers.fetch", side_effect=fetch), patch("api.offers.lookup_product_url", side_effect=lambda *_: None):
        res = _client(tmp_path).get(
            "/events",
            params={
                "source": "live",
                "isbn13": MATILDA_RO,
                "item_id": "matilda",
                "title": "Matilda",
                "listing": MATILDA_PAGE,
            },
        )

    assert res.status_code == 200
    assert fetched == [MATILDA_PAGE]
    sol = _parse(res.text)[-1][1]
    libris = next(r for r in sol["live_offers"] if r["store_id"] == "libris")
    assert (libris["status"], libris["price_cents"], libris["ranked"]) == ("ok", 8418, True)
    assert libris["listing_url"] == MATILDA_PAGE


def test_a_listing_that_is_not_a_shop_page_is_refused(tmp_path):
    res = _client(tmp_path).get(
        "/events",
        params={"source": "live", "isbn13": MATILDA_RO, "item_id": "m", "listing": "https://www.example.com/a-book"},
    )
    assert res.status_code == 400
    assert "not a shop page" in res.json()["error"]

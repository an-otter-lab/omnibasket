"""POST /input and api.input_understanding. Fixtures and mocks only; the autouse
conftest guard fails any test that opens a socket."""

import json
import sqlite3
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import input_understanding as iu
from api.app import create_app
from api.fetch_guard import GuardedFetch
from api.rate_limit import DailyPasteLimiter
from matching.fx import BnrRate, RateTable

HUNGRY = "9780141367941"
HUNGRY_10 = "0141367946"
MUSE = "api.muse_integration.meta_budget.guarded_post"
TODAY = date(2026, 10, 30)


class _OL:
    """Open Library stand-in handed to the search as its opener (the guard blocks real sockets)."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def read(self, n=-1):
        return json.dumps({"docs": [{"title": "The Very Hungry Caterpillar", "author_name": ["Eric Carle"],
                                     "cover_i": 1, "isbn": [HUNGRY]}]}).encode()


def ol_opener(*_a, **_k):
    return _OL()


@pytest.fixture
def index_db(tmp_path):
    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany(
            "INSERT INTO books VALUES(?,?,?,?,?,?)",
            [
                ("libris", "https://www.libris.ro/carte/hungry-caterpillar", "The Very Hungry Caterpillar", "Eric Carle", HUNGRY, "2026-10-30"),
                ("books-express", "https://www.books-express.ro/x/p/y," + HUNGRY, "The Very Hungry Caterpillar", "Eric Carle", HUNGRY, "2026-10-30"),
            ],
        )
    return path


def _payload(text):
    return {"output_text": text, "usage": {"input_tokens": 50, "output_tokens": 40}}


def _muse(reply):
    calls = []

    def fake(body, estimate, note, provider="meta", accept=None):
        calls.append({"body": body, "note": note})
        return _payload(reply), {"tokens_in": 50, "tokens_out": 40}

    return fake, calls


def _no_muse(*a, **k):
    raise AssertionError("no model call expected")


def _page(html, url="https://shop.example/p/1"):
    return GuardedFetch(final_url=url, status=200, content_type="text/html", body=html.encode(), text=html, hops=0)


def _product_html(isbn=HUNGRY, price="12.50", cur="EUR"):
    ld = {"@type": "Product", "name": "Some Book", "isbn": isbn, "offers": {"price": price, "priceCurrency": cur}}
    return '<html><script type="application/ld+json">' + json.dumps(ld) + "</script><body>buy</body></html>"


def _rates(cur="EUR", rate="5.0000"):
    return RateTable(rates=(BnrRate(cur, Decimal(rate), 1, TODAY),), publishing_date=TODAY)


def _count(db):
    with sqlite3.connect(db) as con:
        return con.execute("SELECT count(*) FROM books").fetchone()[0]


# ---- ISBN short-circuit

@pytest.mark.parametrize("raw", [HUNGRY, "978-0-14-136794-1", "ISBN " + HUNGRY_10, HUNGRY_10])
def test_isbn10_and_13_short_circuit_without_model(raw, index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_muse):
        out = iu.understand(raw, index_db=index_db)
    assert out["type"] == "isbn" and out["status"] == "resolved"
    assert out["isbn13"] == HUNGRY
    assert out["structured_query"]["title"] == "The Very Hungry Caterpillar"
    assert out["events_url"].startswith("/events?source=live&isbn13=" + HUNGRY)


def test_bad_check_digit_is_not_an_isbn(index_db):
    assert iu.to_isbn13("9780141367942") is None
    assert iu.to_isbn13("0141367947") is None


# ---- indexed-shop links

def _one_plain_read(seen):
    # S25b: every pasted shop link (not Amazon) gets exactly one page read, for the name; this page has none.
    def read(url, **k):
        seen.append(url)
        return _page("<html><body>no schema here</body></html>", url)

    return read


def test_indexed_shop_link_resolves_to_its_product_page_from_index(index_db):
    url = "https://www.libris.ro/carte/hungry-caterpillar"
    seen = []
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _one_plain_read(seen)):
        out = iu.understand(url, index_db=index_db)
    assert seen == [url]
    assert out["structured_query"]["title"] == "The Very Hungry Caterpillar"
    assert out["type"] == "link"
    assert out["isbn13"] == HUNGRY
    assert out["shop_context"] == {"shop_id": "libris", "product_url": url}
    assert out["paste_offer"] is None


def test_indexed_shop_link_with_isbn_in_url_reads_the_page_once(index_db):
    url = "https://www.emag.ro/carte-z-" + HUNGRY + "/pd/ABC/?x=1"
    seen = []
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _one_plain_read(seen)):
        out = iu.understand(url, index_db=index_db)
    assert seen == [url]
    assert out["shop_context"]["shop_id"] == "emag"
    assert out["isbn13"] == HUNGRY


def test_amazon_link_uses_asin_and_is_never_fetched(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_muse):
        out = iu.understand("https://www.amazon.de/Some-Title/dp/" + HUNGRY_10 + "/ref=x", index_db=index_db)
    assert out["isbn13"] == HUNGRY and out["shop_context"]["shop_id"] == "amazon_de"
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_muse):
        out = iu.understand("https://www.amazon.de/gp/help", index_db=index_db)
    assert out["status"] == "not_found"


def test_indexed_shop_page_read_once_when_url_has_no_isbn(index_db):
    seen = []

    def one_read(url, **k):
        seen.append(url)
        return _page(_product_html(price="30.00", cur="RON"), url)

    with patch(MUSE, _no_muse), patch.object(iu, "fetch", one_read):
        out = iu.understand("https://bookzone.ro/produs/abc", index_db=index_db)
    assert seen == ["https://bookzone.ro/produs/abc"]
    assert out["isbn13"] == HUNGRY and out["shop_context"]["shop_id"] == "bookzone"


# ---- foreign links (S25c: never fetched; the ISBN in the address names the book)

def _no_fetch(url, **k):
    raise AssertionError("no page read expected: " + url)


def test_loopback_link_is_never_fetched(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_fetch):
        out = iu.understand("http://127.0.0.1/secret", index_db=index_db)
    assert out["status"] == "not_found" and out["isbn13"] is None


def test_foreign_link_with_isbn_is_not_read_and_left_to_the_isbn_search(index_db):
    # The UI searches the ISBN in the address, as for a typed ISBN.
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_fetch):
        out = iu.understand("https://other-shop.example/p/" + HUNGRY, index_db=index_db, rates_loader=lambda d: _rates(), today=TODAY)
    assert out["status"] == "not_found" and out["isbn13"] is None and out["paste_offer"] is None


def test_page_without_isbn_is_not_read_and_makes_no_model_call(index_db):
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_fetch):
        out = iu.understand("https://blog.example/post", index_db=index_db, opener=ol_opener)
    assert out["status"] == "not_found" and out["message"] == iu.NO_BOOK_MESSAGE
    assert out["paste_offer"] is None


# ---- free text

def test_free_text_uses_identifying_prompt_and_spike_settings(index_db):
    fake, calls = _muse('{"title": "The Very Hungry Caterpillar", "author": "Eric Carle", "language": "en"}')
    with patch(MUSE, fake):
        out = iu.understand("the caterpillar book", index_db=index_db, opener=ol_opener)
    body = calls[0]["body"]
    assert "real title of the book you think they mean" in json.dumps(body)
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] >= 1200
    assert out["type"] == "free_text"
    assert out["structured_query"] == {"title": "The Very Hungry Caterpillar", "author": "Eric Carle", "language": "en"}
    assert out["isbn13"] == HUNGRY  # single candidate in the index


@pytest.mark.parametrize("reply", ["", "   ", "not json at all", '{"title": "", "author": null}'])
def test_empty_or_unusable_model_reply_is_a_failed_parse(reply, index_db):
    fake, calls = _muse(reply)
    with patch(MUSE, fake):
        out = iu.understand("the caterpillar book", index_db=index_db)
    assert out["status"] == "parse_failed"
    assert out["structured_query"] is None and out["candidates"] == []
    assert len(calls) == 1


def test_muse_isbn_is_ignored(index_db):
    fake, _ = _muse('{"title": "Zzyzx Unknown Tome", "author": null, "language": "en", "isbn13": "9780747532699", "isbn": "9780747532699"}')
    with patch(MUSE, fake):
        out = iu.understand("zzyzx tome", index_db=index_db)
    assert out["isbn13"] is None
    assert "9780747532699" not in json.dumps(out)
    assert set(out["structured_query"]) == {"title", "author", "language"}


def test_muse_numbers_not_on_the_page_are_dropped():
    parsed = {"title": "X", "price": 99.99, "isbn13": "9780747532699"}
    q = iu._clean_query(parsed, "page says nothing numeric")
    assert q == {"title": "X", "author": None, "language": None}


# ---- paste-only offers: paste_offer() is kept, though a foreign page is no longer read (S25c)

def _offer(cur, price="12.50", loader=None):
    schema = iu.extract_schema_org(_product_html(price=price, cur=cur))
    return iu.paste_offer("https://other-shop.example/p/1", schema, TODAY, loader)


def test_paste_only_non_ron_price_converts_at_bnr_rate():
    offer = _offer("EUR", loader=lambda d: _rates("EUR", "5.0000"))
    assert offer["badge"] == "new shop, not checked"
    assert offer["store_id"] == "paste:other-shop.example"
    assert offer["ron_cents"] == 6250  # 12.50 EUR x 5.0000
    assert offer["rate"]["date"] == "2026-10-30"
    # Delivery was not read, so the order is not ranked.
    assert offer["ranked"] is False and offer["not_ranked_reason"] == "delivery_rules_not_read"
    assert offer["shipping_fee_cents"] is None and offer["free_shipping_threshold_cents"] is None


def test_paste_only_non_ron_without_rate_is_not_ranked():
    for loader in (lambda d: None, lambda d: _rates("USD")):
        offer = _offer("EUR", loader=loader)
        assert offer["ron_cents"] is None and offer["ranked"] is False
        assert offer["not_ranked_reason"] == "no_bnr_rate"


def test_foreign_link_is_never_added_to_the_index(index_db):
    before = _count(index_db)
    with patch(MUSE, _no_muse), patch.object(iu, "fetch", _no_fetch):
        iu.understand("https://other-shop.example/p/" + HUNGRY, index_db=index_db, today=TODAY)
    assert _count(index_db) == before


# ---- limits

def test_daily_paste_limit_trips():
    lim = DailyPasteLimiter(pastes_per_day=2, new_domains_per_day=10, today=lambda: 1)
    assert lim.check("1.1.1.1", "a.example") is None
    assert lim.check("1.1.1.1", "a.example") is None
    assert lim.check("1.1.1.1", "a.example") == "paste_limit"
    assert lim.check("2.2.2.2", "a.example") is None  # per IP


def test_new_domain_limit_trips_but_known_domain_still_passes():
    day = [1]
    lim = DailyPasteLimiter(pastes_per_day=50, new_domains_per_day=2, today=lambda: day[0])
    assert lim.check("ip", "a.example") is None
    assert lim.check("ip", "b.example") is None
    assert lim.check("ip", "c.example") == "new_domain_limit"
    assert lim.check("ip", "a.example") is None
    day[0] = 2
    assert lim.check("ip", "c.example") is None  # new day


def test_post_input_endpoint_shape_and_limits(tmp_path, index_db):
    app = create_app(tmp_path / "pages.sqlite")
    app.state.index_db_path = index_db
    app.state.paste_limiter = DailyPasteLimiter(pastes_per_day=1, new_domains_per_day=5, today=lambda: 1)
    client = TestClient(app)
    with patch(MUSE, _no_muse):
        r = client.post("/input", json={"raw_input": HUNGRY})
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"type", "isbn13", "structured_query", "shop_context", "status", "candidates", "paste_offer", "events_url", "message"}
        assert body["type"] == "isbn" and body["shop_context"] == {"shop_id": None, "product_url": None}
        # S25c: the one page read of a known shop's link counts toward the paste limit.
        with patch.object(iu, "fetch", lambda url, **k: _page(_product_html(cur="RON"), url)):
            assert client.post("/input", json={"raw_input": "https://bookzone.ro/produs/a"}).status_code == 200
            tripped = client.post("/input", json={"raw_input": "https://bookzone.ro/produs/b"})
        assert tripped.status_code == 429 and tripped.json()["error"] == "paste_limit"
        # The sample basket and plain searches are not touched by the paste limit.
        assert client.post("/input", json={"raw_input": HUNGRY}).status_code == 200
        assert client.post("/solve").status_code == 200


def test_ro_v1_totals_unchanged(tmp_path):
    client = TestClient(create_app(tmp_path / "pages.sqlite"))
    text = json.dumps(client.post("/solve").json())
    assert "51516" in text and "55873" in text

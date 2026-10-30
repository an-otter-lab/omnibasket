"""Cache hit, failed load, cache-only solve, and the SSE sequence."""

from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.cache import PageCache, load_seed
from api.live import FetchResult, read_page
from api.solve_service import solution_payload
from solver.types import Item, Offer, Store

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "cache" / "ro-v1-seed.json"


@pytest.fixture()
def cache(tmp_path: Path) -> PageCache:
    page_cache = PageCache(tmp_path / "pages.sqlite")
    load_seed(page_cache, SEED)
    return page_cache


def test_cache_hit_by_store_isbn_and_day(cache: PageCache) -> None:
    hit = cache.get("amazon_de", "9781529105100", "mole", "2026-10-28")
    assert hit is not None
    assert "116,53" in hit["page_text"] or "116.53" in hit["page_text"]
    assert hit["provenance"]["capture"].endswith("9781529105100/text.txt")
    assert cache.get("amazon_de", "9781529105100", "mole", "2026-10-27") is None


def test_failed_load_is_a_cache_miss_without_a_second_attempt() -> None:
    calls = {"n": 0}

    def fetch_410():
        calls["n"] += 1
        return FetchResult(http_status=410, text="gone", title="", challenge_overlay=False)

    report = read_page(
        store_id="emag",
        isbn13="9786068996011",
        item_id="ghici",
        headless=False,
        fetcher=fetch_410,
    )
    assert report.status == "failed"
    assert report.cache == "miss"
    assert report.reason == "http_410"
    assert report.attempts == 1
    assert calls["n"] == 1

    calls["n"] = 0

    def fetch_challenge():
        calls["n"] += 1
        return FetchResult(
            http_status=200,
            text="Just a moment while we verify you are human " + ("x" * 600),
            title="Challenge",
            challenge_overlay=True,
        )

    blocked = read_page(
        store_id="libris",
        isbn13="",
        item_id="owl",
        headless=True,
        fetcher=fetch_challenge,
    )
    assert blocked.status == "failed"
    assert blocked.cache == "miss"
    assert blocked.reason == "challenge_overlay"
    assert calls["n"] == 1

    def fetch_should_not_run():
        calls["n"] += 1
        return FetchResult(http_status=200, text="price 10 lei " * 80, title="ok", challenge_overlay=False)

    refused = read_page(
        store_id="emag",
        isbn13="9786068996011",
        item_id="ghici",
        headless=True,
        fetcher=fetch_should_not_run,
    )
    assert refused.status == "failed"
    assert refused.reason == "emag_requires_visible_browser"
    assert refused.attempts == 0
    assert calls["n"] == 1


def test_cache_only_solve_returns_locked_total_without_network(tmp_path: Path, monkeypatch) -> None:
    def _refuse(*_args, **_kwargs):
        raise AssertionError("network use is disabled for a cache-only solve")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)

    app = create_app(tmp_path / "pages.sqlite")
    client = TestClient(app)
    response = client.post("/solve", params={"source": "cache"})
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "RON"
    assert body["total_cents"] == 51516
    assert body["source"] == "cache"
    assert [(row["item_id"], row["store_id"], row["price_cents"]) for row in body["assignment"]] == [
        ("ghici", "libris", 5700),
        ("vhc", "libris", 6133),
        ("owl", "libris", 5178),
        ("mole", "amazon_de", 11653),
        ("wild", "amazon_de", 3986),
        ("matilda", "amazon_de", 9433),
        ("charlie", "amazon_de", 9433),
    ]
    assert body["cheapest_per_item"]["total_cents"] is None
    baseline_stores = {row["store_id"]: row for row in body["cheapest_per_item"]["stores"]}
    assert baseline_stores["amazon_de"]["shipping_cents"] is None
    assert baseline_stores["bookzone"]["shipping_cents"] == 1090
    assert baseline_stores["bookzone"]["per_order_fee_cents"] == 199
    assert body["optimum"]["total_cents"] == 51516
    assert body["single_store_baseline"]["best_store_id"] == "libris"
    assert body["single_store_baseline"]["total_cents"] == 55873
    assert body["romanian_inclusive"]["total_cents"] == 53045
    assert body["romanian_inclusive"]["romanian_stores"] == ["bookzone"]
    assert [
        (row["item_id"], row["store_id"], row["price_cents"])
        for row in body["romanian_inclusive"]["assignment"]
    ] == [
        ("ghici", "bookzone", 4650),
        ("vhc", "libris", 6133),
        ("owl", "libris", 5178),
        ("mole", "amazon_de", 11653),
        ("wild", "amazon_de", 3986),
        ("matilda", "amazon_de", 9433),
        ("charlie", "amazon_de", 9433),
    ]
    assert body["excluded_stores"] == [
        {
            "id": "emag",
            "reason": "unresolved fee",
            "free_shipping_threshold_cents": None,
            "shipping_fee_cents": None,
            "per_order_fee_cents": None,
        }
    ]
    assert body["membership"] == []
    assert all(page["cache"] == "hit" and page["status"] == "ok" for page in body["pages"])
    by_store = {row["store_id"]: row for row in body["stores"]}
    assert by_store["amazon_de"]["items_cents"] == 34505
    assert by_store["amazon_de"]["shipping_cents"] == 0
    assert by_store["libris"]["items_cents"] == 17011
    assert by_store["libris"]["shipping_cents"] == 0


def test_sse_one_event_per_page_then_solution(tmp_path: Path) -> None:
    app = create_app(tmp_path / "pages.sqlite")
    client = TestClient(app)
    response = client.get("/events", params={"source": "cache"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    pages = [event for event in events if event[0] == "page"]
    solutions = [event for event in events if event[0] == "solution"]
    assert len(pages) == 15
    assert len(solutions) == 1
    assert events[-1][0] == "solution"
    assert solutions[0][1]["total_cents"] == 51516
    assert {page[1]["store_id"] for page in pages} == {"libris", "emag", "bookzone", "amazon_de"}
    assert all("isbn13" in page[1] for page in pages)


def test_mixed_currency_returns_the_solver_error() -> None:
    stores = [
        Store("a", "RON", 100, 10, 0),
        Store("b", "EUR", 100, 10, 0),
    ]
    items = [Item("book", (Offer("a", 100, "direct"), Offer("b", 90, "direct")))]
    with pytest.raises(Exception) as caught:
        solution_payload(stores, items)
    assert "mixed currencies are not converted" in str(caught.value)

    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/solve",
        json={
            "source": "given",
            "stores": [
                {
                    "id": "a",
                    "currency": "RON",
                    "free_shipping_threshold_cents": 100,
                    "shipping_fee_cents": 10,
                    "per_order_fee_cents": 0,
                },
                {
                    "id": "b",
                    "currency": "EUR",
                    "free_shipping_threshold_cents": 100,
                    "shipping_fee_cents": 10,
                    "per_order_fee_cents": 0,
                },
            ],
            "items": [
                {
                    "id": "book",
                    "offers": [
                        {"store_id": "a", "price_cents": 100, "seller_certainty": "direct"},
                        {"store_id": "b", "price_cents": 90, "seller_certainty": "direct"},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 400
    assert "mixed currencies are not converted" in response.json()["error"]
    assert "converted at" not in response.json()["error"]


def test_health() -> None:
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_built_ui_is_served_at_root() -> None:
    index = ROOT / "ui" / "dist" / "ui" / "browser" / "index.html"
    if not index.is_file():
        pytest.skip("UI dist is produced by ng build")
    client = TestClient(create_app())
    page = client.get("/")
    assert page.status_code == 200
    assert "Omnibasket" in page.text
    assert client.get("/health").json() == {"status": "ok"}


SEVEN_BOOKS = [
    ("ghici", "libris", 5700),
    ("vhc", "libris", 6133),
    ("owl", "libris", 5178),
    ("mole", "amazon_de", 11653),
    ("wild", "amazon_de", 3986),
    ("matilda", "amazon_de", 9433),
    ("charlie", "amazon_de", 9433),
]


def _assert_locked_split(body: dict) -> None:
    assert body["total_cents"] == 51516
    assert [(row["item_id"], row["store_id"], row["price_cents"]) for row in body["assignment"]] == SEVEN_BOOKS


def test_repeated_solves_share_no_sqlite_connection(tmp_path: Path) -> None:
    """One long-lived app: three solves, a solve during an open /events stream, two in parallel.

    The old PageCache kept one connection created on the first thread. A later
    solve from the worker pool raised sqlite3.ProgrammingError.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    app = create_app(tmp_path / "pages.sqlite")
    client = TestClient(app)

    for _ in range(3):
        response = client.post("/solve", params={"source": "cache"})
        assert response.status_code == 200, response.text
        _assert_locked_split(response.json())

    started = threading.Event()
    release = threading.Event()
    stream_error: list[BaseException] = []

    def hold_stream() -> None:
        stream_client = TestClient(app)
        try:
            with stream_client.stream("GET", "/events", params={"source": "cache"}) as streamed:
                assert streamed.status_code == 200
                chunks = streamed.iter_text()
                first = next(chunks)
                assert first
                started.set()
                assert release.wait(timeout=10)
                rest = first + "".join(chunks)
                assert "51516" in rest
        except BaseException as exc:  # pragma: no cover - surfaced below
            stream_error.append(exc)
            started.set()
        finally:
            stream_client.close()

    holder = threading.Thread(target=hold_stream)
    holder.start()
    assert started.wait(timeout=10)
    during = client.post("/solve", params={"source": "cache"})
    release.set()
    holder.join(timeout=10)
    assert not stream_error, stream_error
    assert during.status_code == 200, during.text
    _assert_locked_split(during.json())

    def solve_once() -> dict:
        peer = TestClient(app)
        try:
            response = peer.post("/solve", params={"source": "cache"})
            assert response.status_code == 200, response.text
            body = response.json()
            _assert_locked_split(body)
            return body
        finally:
            peer.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        parallel = [future.result(timeout=15) for future in (pool.submit(solve_once), pool.submit(solve_once))]
    assert len(parallel) == 2


def test_given_demo_basket_returns_both_answers_and_excludes_emag() -> None:
    """Edition re-solve posts the books on screen. One call still has both answers."""

    from api.basket import load_locked

    _day, currency, stores, items, _pages = load_locked()
    client = TestClient(create_app())
    response = client.post(
        "/solve",
        json={
            "source": "given",
            "stores": [
                {
                    "id": store.id,
                    "currency": store.currency,
                    "free_shipping_threshold_cents": store.free_shipping_threshold_cents,
                    "shipping_fee_cents": store.shipping_fee_cents if store.shipping_fee_known else None,
                    "per_order_fee_cents": store.per_order_fee_cents,
                }
                for store in stores
            ],
            "items": [
                {
                    "id": item.id,
                    "offers": [
                        {
                            "store_id": offer.store_id,
                            "price_cents": offer.price_cents,
                            "seller_certainty": offer.seller_certainty,
                        }
                        for offer in item.offers
                    ],
                }
                for item in items
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert currency == "RON"
    assert body["optimum"]["total_cents"] == 51516
    assert body["romanian_inclusive"]["total_cents"] == 53045
    assert body["romanian_inclusive"]["romanian_stores"] == ["bookzone"]
    assert body["excluded_stores"][0]["id"] == "emag"
    assert body["excluded_stores"][0]["per_order_fee_cents"] is None
    assert body["excluded_stores"][0]["shipping_fee_cents"] is None
    assert "1.49" not in response.text
    assert all(row["store_id"] != "emag" for row in body["optimum"]["assignment"])
    assert all(row["store_id"] != "emag" for row in body["romanian_inclusive"]["assignment"])


def test_one_book_basket_is_5539_at_bookzone() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/solve",
        json={
            "source": "given",
            "stores": [
                {
                    "id": "bookzone",
                    "currency": "RON",
                    "free_shipping_threshold_cents": 20000,
                    "shipping_fee_cents": 690,
                    "per_order_fee_cents": 199,
                }
            ],
            "items": [
                {
                    "id": "ghici",
                    "offers": [
                        {"store_id": "bookzone", "price_cents": 4650, "seller_certainty": "direct"}
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_cents"] == 5539
    assert body["assignment"] == [
        {
            "item_id": "ghici",
            "store_id": "bookzone",
            "price_cents": 4650,
            "seller_certainty": "direct",
        }
    ]
    assert body["stores"][0]["store_total_cents"] == 5539
    assert body["stores"][0]["shipping_cents"] == 690
    assert body["stores"][0]["per_order_fee_cents"] == 199


def test_cache_miss_names_the_book_and_store(tmp_path: Path) -> None:
    app = create_app(tmp_path / "pages.sqlite")
    client = TestClient(app)
    client.get("/events", params={"source": "cache"})
    db = tmp_path / "pages.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM pages WHERE item_id = ?", ("ghici",))
    response = client.get("/events", params={"source": "cache"})
    events = _parse_sse(response.text)
    assert [name for name, _data in events] == ["error"]
    body = events[0][1]
    assert body["error"] == "cache miss for items: ghici"
    assert {row["title"] for row in body["misses"]} == {"Ghici cât de mult te iubesc"}
    assert {row["store_id"] for row in body["misses"]} == {"bookzone", "emag", "libris"}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name and data is not None:
            events.append((name, data))
    return events

"""S12: the "Prices read" range covers book prices only, not the shops' delivery-rule capture dates."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _store(sid, read_at):
    return {"id": sid, "currency": "RON", "free_shipping_threshold_cents": 15000, "shipping_fee_cents": 1500,
            "per_order_fee_cents": 0, "read_at": read_at}


def _post(client, stores, items):
    r = client.post("/solve", json={"source": "given", "stores": stores, "items": items})
    assert r.status_code == 200, r.text
    return r.json()


def _offer(store_id, price, read_at):
    return {"store_id": store_id, "price_cents": price, "seller_certainty": "direct", "read_at": read_at}


def test_books_read_today_with_rules_from_days_ago_give_one_day(client):
    body = _post(
        client,
        [_store("libris", "2026-10-28T09:00:00+02:00"), _store("books_express", "2026-10-29T09:00:00+02:00")],
        [
            {"id": "a", "title": "A", "isbn13": "9780142402535", "offers": [_offer("libris", 3000, "2026-10-31T21:00:00+02:00"), _offer("books_express", 3250, "2026-10-31T21:01:00+02:00")]},
            {"id": "b", "title": "B", "isbn13": "9786060339229", "offers": [_offer("libris", 3100, "2026-10-31T21:02:00+02:00")]},
        ],
    )
    r = body["read_at_range"]
    assert r["oldest"].startswith("2026-10-31") and r["newest"].startswith("2026-10-31")


def test_no_book_read_time_means_no_stamp(client):
    body = _post(
        client,
        [_store("libris", "2026-10-28T09:00:00+02:00")],
        [{"id": "a", "title": "A", "isbn13": "9780142402535", "offers": [{"store_id": "libris", "price_cents": 3000, "seller_certainty": "direct"}]}],
    )
    assert body["read_at_range"] == {"oldest": None, "newest": None}

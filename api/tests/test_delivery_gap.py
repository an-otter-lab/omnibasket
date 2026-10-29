"""Feature 4: the free-delivery gap on every order.

Every threshold here is the solver's own store data: data/stores/ro.yaml for the
ro-v1 basket, or the store row posted in the test. Nothing is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.plan import delivery_gap


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _all_orders(body: dict) -> list[dict]:
    orders = list(body["cheapest"]["orders"])
    if body["one_parcel"]["answer"]:
        orders += body["one_parcel"]["answer"]["orders"]
    if body["custom"]:
        orders += body["custom"]["orders"]
    return orders


# ------------------------------------------------------------ the helper


def test_gap_is_threshold_minus_qualifying_when_short() -> None:
    assert delivery_gap(20000, 4650, 1090) == {
        "status": "short",
        "short_cents": 15350,
        "threshold_cents": 20000,
    }


def test_gap_is_reached_at_and_over_the_bar_when_delivery_is_zero() -> None:
    assert delivery_gap(13500, 13500, 0) == {"status": "reached", "short_cents": 0, "threshold_cents": 13500}
    assert delivery_gap(13500, 17011, 0)["status"] == "reached"


def test_unknown_threshold_hides_the_line() -> None:
    assert delivery_gap(None, 4650, 1090) is None
    assert delivery_gap(None, 99999, 0) is None


def test_over_the_bar_with_unproven_delivery_is_not_called_reached() -> None:
    # Bookzone's unprinted charge at the 200 lei bar: no "reached" claim.
    assert delivery_gap(20000, 20000, None) is None


# ------------------------------------------------------------ ro-v1 basket


def test_ro_v1_totals_unchanged_and_every_order_reached(client: TestClient) -> None:
    body = client.post("/solve").json()
    assert body["cheapest"]["total_cents"] == 51516  # 515,16 lei
    assert body["one_parcel"]["answer"]["total_cents"] == 55873  # 558,73 lei
    by_store = {o["store_id"]: o for o in body["cheapest"]["orders"]}
    assert by_store["amazon_de"]["delivery_gap"] == {
        "status": "reached",
        "short_cents": 0,
        "threshold_cents": 26217,
    }
    assert by_store["libris"]["delivery_gap"] == {
        "status": "reached",
        "short_cents": 0,
        "threshold_cents": 13500,
    }
    libris_one = body["one_parcel"]["answer"]["orders"][0]
    assert libris_one["store_id"] == "libris"
    assert libris_one["delivery_gap"]["status"] == "reached"


def test_ro_v1_custom_bookzone_order_is_short_by_153_50(client: TestClient) -> None:
    body = client.post("/solve", json={"selected_store_ids": ["amazon_de", "libris", "bookzone"]}).json()
    assert body["cheapest"]["total_cents"] == 51516
    assert body["custom"]["total_cents"] == 53045
    bookzone = next(o for o in body["custom"]["orders"] if o["store_id"] == "bookzone")
    # Ghici 46,50 lei against Bookzone's 200 lei bar (data/stores/ro.yaml).
    assert bookzone["delivery_gap"] == {"status": "short", "short_cents": 15350, "threshold_cents": 20000}
    assert bookzone["delivery_gap"]["short_cents"] == bookzone["short_of_threshold_cents"]


def test_every_order_carries_the_field(client: TestClient) -> None:
    body = client.post("/solve", json={"selected_store_ids": ["amazon_de", "libris", "bookzone"]}).json()
    for order in _all_orders(body):
        assert "delivery_gap" in order
        gap = order["delivery_gap"]
        if gap is not None:
            assert gap["threshold_cents"] == order["free_delivery_threshold_cents"]
            assert gap["status"] in {"short", "reached"}


# ------------------------------------------------------------ posted basket


def test_posted_bookzone_at_the_bar_without_printed_fee_hides_the_line(client: TestClient) -> None:
    stores = [
        {
            "id": "bookzone",
            "currency": "RON",
            "free_shipping_threshold_cents": 20000,
            "shipping_fee_cents": None,
            "per_order_fee_cents": 199,
        }
    ]
    items = [{"id": "x", "offers": [{"store_id": "bookzone", "price_cents": 20000, "seller_certainty": "direct"}]}]
    body = client.post(
        "/solve", json={"source": "given", "stores": stores, "items": items, "selected_store_ids": ["bookzone"]}
    ).json()
    order = body["custom"]["orders"][0]
    assert order["delivery_known"] is False
    assert order["delivery_gap"] is None

"""Muse Spark reads: every saved page, checked against the capture, never written into it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from api.cache import PageCache, load_seed
from matching.validate import compare_read_to_capture

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "cache" / "ro-v1-seed.json"
BASKET = ROOT / "data" / "baskets" / "ro-v1.yaml"

MODEL = "muse-spark-1.3"
READ_KEYS = {"status", "model", "read_at", "mismatch_fields"}


def _captured() -> dict:
    basket = yaml.safe_load(BASKET.read_text())
    rows = {}
    for book in basket["books"]:
        for offer in book["offers"]:
            rows[(offer["store_id"], book["id"])] = {
                "price_cents": int(offer["price_cents"]),
                "isbn13": book.get("isbn13") or None,
            }
    return rows


def _client(tmp_path: Path, mutate=None) -> TestClient:
    cache = PageCache(tmp_path / "pages.sqlite")
    load_seed(cache, SEED)
    if mutate is not None:
        hit = cache.get(*mutate["key"])
        row = dict(hit)
        row["model_json"] = mutate["model_json"](hit["model_json"])
        cache.put(row)
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _offer(body: dict, item_id: str, store_id: str) -> dict:
    book = next(b for b in body["books"] if b["item_id"] == item_id)
    return next(s for s in book["shops"] if s["store_id"] == store_id)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path)


# ---------------------------------------------------------------- the seed


def test_every_saved_page_carries_a_muse_spark_read() -> None:
    seed = json.loads(SEED.read_text())
    assert len(seed["pages"]) == 15
    captured = _captured()
    for page in seed["pages"]:
        read = page.get("model_json")
        assert read, "page %s/%s has no read" % (page["store_id"], page["item_id"])
        assert read["model"] == MODEL
        assert read["read_at"]
        assert read["replay"] is True and read["browser_launched"] is False
        assert read["check"]["status"] in {"match", "mismatch", "not_read"}
        if read["check"]["status"] == "not_read":
            assert read["check"]["reason"], "a not_read page says why"


def test_seed_checks_agree_with_the_validator() -> None:
    seed = json.loads(SEED.read_text())
    captured = _captured()
    for page in seed["pages"]:
        expected = compare_read_to_capture(
            page["model_json"],
            price_cents=captured[(page["store_id"], page["item_id"])]["price_cents"],
            isbn13=captured[(page["store_id"], page["item_id"])]["isbn13"],
        )
        assert page["model_json"]["check"] == expected


def test_a_match_carries_its_read_on_the_offer(client: TestClient) -> None:
    body = client.post("/solve").json()
    bookzone = _offer(body, "ghici", "bookzone")
    assert bookzone["price_cents"] == 4650
    assert set(bookzone["model_read"]) == READ_KEYS
    assert bookzone["model_read"]["status"] == "match"
    assert bookzone["model_read"]["model"] == MODEL
    assert bookzone["model_read"]["read_at"]
    assert bookzone["model_read"]["mismatch_fields"] == []
    assert sum(
        1
        for book in body["books"]
        for shop in book["shops"]
        if shop["price_cents"] is not None and shop["model_read"]["status"] == "match"
    ) == 15


# ---------------------------------------------------------- mismatch and gaps


def _wrong_price(model_json):
    read = json.loads(json.dumps(model_json))
    read["fields"]["price"] = float(read["fields"]["price"]) + 1.25
    read["check"] = {"status": "mismatch", "mismatch_fields": ["price"], "reason": None}
    return read


def test_a_mismatch_is_named_and_the_price_is_unchanged(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        mutate={"key": ("bookzone", "9786068996011", "ghici", "2026-10-28"), "model_json": _wrong_price},
    )
    body = client.post("/solve").json()
    bookzone = _offer(body, "ghici", "bookzone")
    # The capture keeps its price; the read is only reported against it.
    assert bookzone["price_cents"] == 4650
    assert bookzone["model_read"]["status"] == "mismatch"
    assert bookzone["model_read"]["mismatch_fields"] == ["price"]
    # Totals are arithmetic on the capture, so they do not move.
    assert body["cheapest"]["total_cents"] == 51516
    assert body["one_parcel"]["answer"]["total_cents"] == 55873


def _drop_read(model_json):
    return None


def test_a_page_without_a_read_is_not_read_and_names_no_field(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        mutate={"key": ("bookzone", "9786068996011", "ghici", "2026-10-28"), "model_json": _drop_read},
    )
    body = client.post("/solve").json()
    bookzone = _offer(body, "ghici", "bookzone")
    assert bookzone["price_cents"] == 4650
    assert bookzone["model_read"] == {
        "status": "not_read",
        "model": None,
        "read_at": None,
        "mismatch_fields": [],
    }
    # An offer with no read still sells, and the totals are untouched.
    assert body["cheapest"]["total_cents"] == 51516


def test_every_offer_carries_the_shape_even_when_unread(tmp_path: Path) -> None:
    posted = {
        "source": "given",
        "stores": [
            {
                "id": "libris",
                "currency": "RON",
                "free_shipping_threshold_cents": 10000,
                "shipping_fee_cents": 500,
                "per_order_fee_cents": 0,
            }
        ],
        "items": [{"id": "x", "offers": [{"store_id": "libris", "price_cents": 1000, "seller_certainty": "direct"}]}],
    }
    body = TestClient(create_app()).post("/solve", json=posted).json()
    assert body["books"][0]["shops"][0]["model_read"] == {
        "status": "not_read",
        "model": None,
        "read_at": None,
        "mismatch_fields": [],
    }

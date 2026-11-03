"""The /solve payload for the three tabs, custom shops, pins and degraded cases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _store(sid, threshold=10000, shipping=500, fee=0):
    return {
        "id": sid,
        "currency": "RON",
        "free_shipping_threshold_cents": threshold,
        "shipping_fee_cents": shipping,
        "per_order_fee_cents": fee,
    }


def _item(iid, offers, **extra):
    return {
        "id": iid,
        "offers": [
            {"store_id": s, "price_cents": p, "seller_certainty": "direct", **more}
            for s, p, *rest in offers
            for more in [rest[0] if rest else {}]
        ],
        **extra,
    }


def _post(client, stores, items, **extra):
    response = client.post("/solve", json={"source": "given", "stores": stores, "items": items, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------ real basket


def test_cheapest_is_51516_in_two_parcels(client: TestClient) -> None:
    body = client.post("/solve").json()
    cheapest = body["cheapest"]
    assert cheapest["status"] == "ranked"
    assert cheapest["total_cents"] == 51516
    assert cheapest["order_count"] == len({o["store_id"] for o in cheapest["orders"]}) == 2
    by_store = {o["store_id"]: o for o in cheapest["orders"]}
    assert len(by_store["amazon_de"]["books"]) == 4
    assert len(by_store["libris"]["books"]) == 3
    amazon = by_store["amazon_de"]
    assert amazon["threshold_crossed"] is True
    assert amazon["free_delivery_threshold_cents"] == 26217
    assert amazon["over_under_threshold_cents"] == amazon["qualifying_cents"] - 26217
    assert amazon["delivery_known"] is True and amazon["delivery_cents"] == 0
    assert amazon["order_total_cents"] == amazon["books_subtotal_cents"] + 0 + amazon["order_fee_cents"]
    book = amazon["books"][0]
    assert set(book) >= {"title", "isbn13", "edition", "price_cents", "currency", "listing_url", "read_at"}
    assert body["cached"] is True and body["source"] == "cache"
    assert body["degraded"] is None


def test_one_parcel_is_libris_55873_with_reasons_for_the_rest(client: TestClient) -> None:
    one = client.post("/solve").json()["one_parcel"]
    assert one["status"] == "ranked"
    assert one["best_store_id"] == "libris"
    assert one["answer"]["total_cents"] == 55873
    assert one["answer"]["order_count"] == 1
    assert one["answer"]["delta_vs_cheapest_cents"] == 55873 - 51516
    deltas = {row["item_id"]: row["delta_cents"] for row in one["per_book_delta"]}
    assert deltas["mole"] > 0 and deltas["wild"] > 0 and deltas["ghici"] == 0
    assert all(row["cheapest_store_id"] for row in one["per_book_delta"])
    others = {row["store_id"]: row for row in one["shops"] if row["store_id"] != "libris"}
    assert others["amazon_de"]["status"] == "not_possible"
    assert others["amazon_de"]["total_cents"] is None
    assert {r["code"] for r in others["amazon_de"]["reasons"]} == {"not_listed"}
    assert "fees_not_printed" in {r["code"] for r in others["emag"]["reasons"]}
    assert others["bookzone"]["reasons"][0]["item_ids"]


def test_custom_amazon_libris_bookzone_is_53045_with_ghici_at_bookzone(client: TestClient) -> None:
    response = client.post(
        "/solve", json={"selected_store_ids": ["amazon_de", "libris", "bookzone"]}
    )
    custom = response.json()["custom"]
    assert custom["status"] == "ranked"
    assert custom["total_cents"] == 53045
    assert custom["delta_vs_cheapest_cents"] == 53045 - 51516
    assert custom["order_count"] == 3
    assert {o["store_id"] for o in custom["orders"]} == {"amazon_de", "libris", "bookzone"}
    assert [(m["item_id"], m["from_store_id"], m["to_store_id"]) for m in custom["moves"]] == [
        ("ghici", "libris", "bookzone")
    ]
    ghici = custom["moves"][0]
    assert ghici["from_price_cents"] == 5700 and ghici["to_price_cents"] == 4650
    bookzone = next(o for o in custom["orders"] if o["store_id"] == "bookzone")
    assert [b["item_id"] for b in bookzone["books"]] == ["ghici"]
    assert bookzone["delivery_cents"] == 1090 and bookzone["order_fee_cents"] == 199


def test_custom_ranked_responses_use_each_selected_shop_and_no_others(client: TestClient) -> None:
    selections = [["amazon_de", "libris", "bookzone"], ["libris", "bookzone"], ["amazon_de", "libris"]]
    for selected in selections:
        custom = client.post("/solve", json={"selected_store_ids": selected}).json()["custom"]
        assert custom["status"] == "ranked"
        books_by_store = {o["store_id"]: o["books"] for o in custom["orders"]}
        assert set(books_by_store) == set(selected)
        assert all(books_by_store[sid] for sid in selected)
        assert all(o["store_id"] in selected and o["books"] for o in custom["orders"])

def test_custom_bookzone_at_200_lei_is_not_ranked_without_printed_fee(client: TestClient) -> None:
    stores = [_store("bookzone", threshold=20000, shipping=None, fee=199)]
    items = [_item("x", [("bookzone", 20000)])]
    custom = _post(client, stores, items, selected_store_ids=["bookzone"])["custom"]
    assert custom["status"] == "not_ranked"
    assert custom["total_cents"] is None
    assert custom["missing_fees"] == [{"store_id": "bookzone", "field": "shipping_fee_cents", "books_subtotal_cents": 20000}]

def test_custom_is_absent_without_a_selection(client: TestClient) -> None:
    assert client.post("/solve").json()["custom"] is None


def test_custom_refuses_emag_and_names_the_reason_without_a_total(client: TestClient) -> None:
    custom = client.post("/solve", json={"selected_store_ids": ["emag", "libris"]}).json()["custom"]
    assert custom["status"] == "not_possible"
    assert custom["total_cents"] is None
    assert custom["unselectable"][0]["store_id"] == "emag"
    assert custom["unselectable"][0]["code"] == "fees_not_printed"
    shops = {s["store_id"]: s for s in client.post("/solve").json()["shops"]}
    assert shops["emag"]["selectable"] is False and shops["emag"]["excluded"] is True
    assert shops["libris"]["selectable"] is True


def test_custom_with_no_feasible_split_gives_a_reason_and_no_total(client: TestClient) -> None:
    custom = client.post("/solve", json={"selected_store_ids": ["amazon_de"]}).json()["custom"]
    assert custom["status"] == "not_possible"
    assert custom["total_cents"] is None and custom["orders"] == []
    assert "Ghici" in custom["reason"]


def test_ask_leave_out_amazon_is_the_cheapest_over_the_rest_not_each_shop(client: TestClient) -> None:
    # Ask "no Amazon" (Adrian, 3 Nov): the cheapest plan over the other shops, 558,73 at Libris alone,
    # not the Custom rule where Libris and Bookzone must each take a book (561,12).
    rest = ["libris", "bookzone"]
    each = client.post("/solve", json={"selected_store_ids": rest}).json()["custom"]
    within = client.post("/solve", json={"selected_store_ids": rest, "selected_within": True}).json()["custom"]
    assert each["total_cents"] == 56112
    assert within["status"] == "ranked" and within["total_cents"] == 55873
    assert within["selected_store_ids"] == ["libris"]
    assert {o["store_id"] for o in within["orders"]} == {"libris"}


def test_selected_within_names_only_the_shops_it_uses(client: TestClient) -> None:
    stores = [_store("a"), _store("b"), _store("c")]
    items = [_item("x", [("a", 3000), ("c", 2500)]), _item("y", [("b", 2000), ("c", 1000)]), _item("z", [("a", 1500), ("c", 1400)])]
    each = _post(client, stores, items, selected_store_ids=["a", "b", "c"])["custom"]
    within = _post(client, stores, items, selected_store_ids=["a", "b", "c"], selected_within=True)["custom"]
    assert {o["store_id"] for o in each["orders"]} == {"a", "b", "c"}
    assert within["selected_store_ids"] == ["c"] and within["total_cents"] == 4900 + 500
    assert within["total_cents"] < each["total_cents"]


def test_selected_within_a_shop_missing_a_book_has_no_total(client: TestClient) -> None:
    custom = client.post("/solve", json={"selected_store_ids": ["amazon_de"], "selected_within": True}).json()["custom"]
    assert custom["status"] == "not_possible"
    assert custom["total_cents"] is None and custom["orders"] == []


def test_failed_read_shop_is_not_selectable_and_cached_is_said(tmp_path: Path) -> None:
    app = create_app(tmp_path / "pages.sqlite")
    client = TestClient(app)
    client.post("/solve")
    with sqlite3.connect(tmp_path / "pages.sqlite") as conn:
        conn.execute("DELETE FROM pages WHERE store_id = ?", ("bookzone",))
    body = client.post("/solve", json={"selected_store_ids": ["bookzone", "libris"]}).json()
    shop = next(s for s in body["shops"] if s["store_id"] == "bookzone")
    assert shop["selectable"] is False
    assert shop["not_selectable_code"] == "couldnt_read"
    assert shop["failed_reads"][0]["reason"] == "cache_miss"
    assert shop["failed_reads"][0]["attempts"] == 0
    assert body["failed_reads"] and body["cached"] is True
    assert body["custom"]["status"] == "not_possible" and body["custom"]["total_cents"] is None
    ghici = next(b for b in body["books"] if b["item_id"] == "ghici")
    assert next(s for s in ghici["shops"] if s["store_id"] == "bookzone")["status"] == "couldnt_read"


def test_every_book_lists_every_shop_with_a_status(client: TestClient) -> None:
    body = client.post("/solve").json()
    allowed = {"in_plan", "compared", "fees_not_printed", "not_listed", "out_of_stock", "couldnt_read", "other_edition"}
    assert len(body["books"]) == 7
    for book in body["books"]:
        assert [s["store_id"] for s in book["shops"]] == [s["store_id"] for s in body["shops"]]
        assert {s["status"] for s in book["shops"]} <= allowed
        assert sum(1 for s in book["shops"] if s["status"] == "in_plan") == 1
    mole = next(b for b in body["books"] if b["item_id"] == "mole")
    assert next(s for s in mole["shops"] if s["store_id"] == "bookzone")["status"] == "not_listed"
    assert all(s["read_at"] for s in body["shops"])
    assert body["read_at_range"]["newest"]


def test_the_endpoint_list() -> None:
    app = create_app()
    paths = {(m, r.path) for r in app.routes for m in getattr(r, "methods", ()) if r.path in {"/health", "/solve", "/events"}}
    assert paths >= {("GET", "/health"), ("POST", "/solve"), ("GET", "/events")}


# --------------------------------------------------------- unknown fees


def _unknown_fee_basket():
    stores = [
        _store("a", threshold=20000, shipping=None, fee=0),
        _store("b", threshold=20000, shipping=1000, fee=0),
    ]
    items = [
        _item("x", [("a", 3000), ("b", 5000)]),
        _item("y", [("a", 3000), ("b", 5000)]),
    ]
    return stores, items


def test_unknown_fee_split_is_not_ranked_and_never_summed_as_zero(client: TestClient) -> None:
    stores, items = _unknown_fee_basket()
    body = _post(client, stores, items)
    cheapest = body["cheapest"]
    # a + a is 6000 by books but a's delivery is not printed: it is not the answer.
    assert cheapest["status"] == "ranked" and cheapest["total_cents"] == 11000
    alt = cheapest["not_ranked"][0]
    assert alt["total_cents"] is None
    assert alt["books_subtotal_cents"] == 6000
    assert alt["missing_fees"] == [
        {"store_id": "a", "field": "shipping_fee_cents", "books_subtotal_cents": 6000}
    ]
    order = alt["orders"][0]
    assert order["delivery_known"] is False
    assert order["delivery_cents"] is None and order["order_total_cents"] is None
    shops = {s["store_id"]: s for s in body["one_parcel"]["shops"]}
    assert shops["a"]["status"] == "not_ranked"
    assert shops["a"]["total_cents"] is None
    assert shops["a"]["books_subtotal_cents"] == 6000
    assert shops["a"]["missing_fees"][0]["store_id"] == "a"
    assert body["one_parcel"]["best_store_id"] == "b"
    assert body["one_parcel"]["shops"][-1]["status"] != "ranked"


def test_custom_for_an_unknown_fee_shop_is_not_ranked_with_its_subtotal(client: TestClient) -> None:
    stores, items = _unknown_fee_basket()
    body = _post(client, stores, items, selected_store_ids=["a"])
    custom = body["custom"]
    assert custom["status"] == "not_ranked"
    assert custom["total_cents"] is None
    assert custom["books_subtotal_cents"] == 6000
    assert custom["missing_fees"][0]["store_id"] == "a"
    assert custom["delta_vs_cheapest_cents"] is None


# ------------------------------------------------------------- editions


def test_edition_pin_uses_only_that_edition_and_reports_the_delta(client: TestClient) -> None:
    stores = [_store("a", threshold=0), _store("b", threshold=0)]
    items = [
        _item(
            "x",
            [("a", 3000, {"edition": "paperback"}), ("b", 4500, {"edition": "hardcover"})],
            title="X",
        ),
        _item("y", [("a", 1000, {"edition": "paperback"}), ("b", 1200)], title="Y"),
    ]
    free = _post(client, stores, items)
    assert free["cheapest"]["total_cents"] == 4000
    pinned = _post(client, stores, items, edition_pins={"x": "hardcover"})
    assert pinned["cheapest"]["total_cents"] == 4500 + 1000
    assert pinned["edition"]["pins"] == {"x": "hardcover"}
    assert pinned["edition"]["unpinned_total_cents"] == 4000
    assert pinned["edition"]["delta_cents"] == 1500
    x = next(b for b in pinned["books"] if b["item_id"] == "x")
    assert x["edition_pin"] == "hardcover"
    assert {e["edition"] for e in x["editions"]} == {"paperback", "hardcover"}
    assert next(s for s in x["shops"] if s["store_id"] == "a")["status"] == "other_edition"
    assert next(s for s in x["shops"] if s["store_id"] == "b")["status"] == "in_plan"
    assert pinned["total_cents"] == 5500


def test_pin_nobody_sells_is_not_possible(client: TestClient) -> None:
    stores = [_store("a", threshold=0)]
    items = [_item("x", [("a", 3000, {"edition": "paperback"})], title="X")]
    body = _post(client, stores, items, edition_pins={"x": "board_book"})
    assert body["cheapest"]["status"] == "not_possible"
    assert body["cheapest"]["total_cents"] is None
    assert "board_book" in body["cheapest"]["reason"]
    assert body["one_parcel"]["status"] == "not_possible"


def test_real_basket_pin_follows_the_edition(client: TestClient) -> None:
    body = client.post("/solve", json={"edition_pins": {"mole": "hardcover"}}).json()
    assert body["edition"]["status"] == "ranked"
    assert body["edition"]["total_cents"] == 51516 and body["edition"]["delta_cents"] == 0
    body = client.post("/solve", json={"edition_pins": {"wild": "hardcover"}}).json()
    assert body["edition"]["status"] == "not_possible"
    assert body["cheapest"]["total_cents"] is None


# ------------------------------------------------------------ degraded


def test_one_book_ranks_shops_and_lists_unknown_fee_shops_unranked(client: TestClient) -> None:
    stores = [_store("a", shipping=500), _store("b", shipping=300), _store("c", shipping=None)]
    items = [_item("x", [("a", 1000), ("b", 1100), ("c", 900)], title="X")]
    body = _post(client, stores, items)
    assert body["degraded"]["kind"] == "one_book"
    shops = body["one_parcel"]["shops"]
    assert [(s["store_id"], s["status"]) for s in shops] == [
        ("b", "ranked"),
        ("a", "ranked"),
        ("c", "not_ranked"),
    ]
    assert shops[0]["total_cents"] == 1400 and shops[1]["total_cents"] == 1500
    assert shops[2]["total_cents"] is None and shops[2]["books_subtotal_cents"] == 900
    assert body["cheapest"]["total_cents"] == 1400


def test_only_one_shop_with_every_book_is_the_cheapest_answer_too(client: TestClient) -> None:
    # Adrian, 3 Nov: Libris prices Matilda and Gruffalo, Books-Express failed to read. The one Libris
    # order is the cheapest answer (126,51), the same as the one-order tab; "only one shop" is a note.
    stores = [_store("libris", threshold=20000, shipping=1290)]
    items = [_item("matilda", [("libris", 5661)], title="Matilda"), _item("gruffalo", [("libris", 5700)], title="Gruffalo")]
    body = _post(client, stores, items, selected_store_ids=["libris"])
    assert body["degraded"]["kind"] == "one_shop" and body["degraded"]["reason_code"] == "one_shop"
    assert body["cheapest"]["status"] == "ranked" and body["cheapest"]["total_cents"] == 12651
    assert [o["store_id"] for o in body["cheapest"]["orders"]] == ["libris"]
    assert body["cheapest"]["order_count"] == 1 and "degraded" not in body["cheapest"]
    assert body["one_parcel"]["status"] == "ranked"
    assert body["one_parcel"]["answer"]["total_cents"] == 12651
    assert body["one_parcel"]["answer"]["delta_vs_cheapest_cents"] == 0
    assert body["custom"]["status"] == "not_possible" and body["custom"]["total_cents"] is None


def test_s23_not_possible_answers_carry_a_reason_code(client: TestClient) -> None:
    """S23: the UI renders reason_code/reason_args in the shopper's language; reason stays English."""
    body = client.post("/solve", json={"selected_store_ids": ["amazon_de"]}).json()
    custom = body["custom"]
    assert custom["reason_code"] == "no_chosen_shop_lists"
    assert custom["reason_args"]["title"] in custom["reason"]
    one = body["one_parcel"]
    if one["status"] != "ranked":
        assert one["reason_code"] in {"no_single_shop_lists_all", "no_single_shop_fees", "no_shop_lists"}
    else:
        assert one["reason_code"] is None
    assert client.post("/solve", json={"selected_store_ids": []}).json()["custom"]["reason_code"] == "choose_a_shop"


def test_s23_pin_nobody_sells_names_the_edition_by_code(client: TestClient) -> None:
    stores = [_store("a", threshold=0)]
    items = [_item("x", [("a", 3000, {"edition": "paperback"})], title="X")]
    body = _post(client, stores, items, edition_pins={"x": "board_book"})
    for key in ("cheapest", "one_parcel", "edition"):
        assert body[key]["reason_code"] == "no_shop_prints_as", key
        assert body[key]["reason_args"] == {"title": "X", "edition": "board_book"}, key

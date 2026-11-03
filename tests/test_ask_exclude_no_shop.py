"""Ask: leaving a shop out when another book is sold only there (3 Nov walk, Gruffalo at Elefant only).

The Custom answer keeps the remaining shops chosen, names every book no remaining shop lists, and an
exclude that would leave no shop at all says so instead of "can't do that yet", on the fast path and
the model path alike.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import ask
from api.app import create_app

NAMES = {"stores": {"libris": "Libris", "elefant": "Elefant"}, "memberships": {}}
# The walk basket: The Gruffalo at Elefant only, Matilda at both, the Libris Gruffalo at Libris only.
ITEMS = [
    {"item_id": "gruffalo", "editions": [], "store_ids": ["elefant"]},
    {"item_id": "matilda", "editions": [], "store_ids": ["libris", "elefant"]},
    {"item_id": "gruffalo-ro", "editions": [], "store_ids": ["libris"]},
]


def state(selected):
    return {"tab": "cheapest", "selected_store_ids": selected, "memberships": [], "edition_pins": {},
            "store_ids": ["libris", "elefant"], "membership_ids": [], "items": ITEMS}


def model_says(*actions):
    def muse(*a, **k):
        return {"actions": list(actions)}
    return muse


def exclude(sid):
    return {"name": "exclude_store", "args": {"store_id": sid}}


@pytest.mark.parametrize("sid", ["libris", "elefant"])
def test_fast_path_and_model_path_agree_on_an_impossible_exclude(sid):
    fast = ask.answer("no " + NAMES["stores"][sid], "en", state(["libris", "elefant"]), muse=model_says(), names=NAMES)
    muse = ask.answer("I'd rather not buy anything from " + NAMES["stores"][sid], "en", state(["libris", "elefant"]),
                      muse=model_says(exclude(sid)), names=NAMES)
    assert (fast.via, muse.via) == ("fast", "muse")
    assert fast.as_response() == muse.as_response() == {
        "status": "ok", "actions": [exclude(sid)], "reply_key": "askDoneExclude",
        "reply_args": {"shop": NAMES["stores"][sid]},
    }


def test_an_exclude_that_leaves_no_shop_says_so_on_both_paths():
    # The pool is already down to Elefant: leaving it out too leaves nothing to buy from.
    fast = ask.answer("no Elefant", "en", state(["elefant"]), muse=model_says(), names=NAMES).as_response()
    muse = ask.answer("leave out Elefant", "en", state(["elefant"]), muse=model_says(exclude("elefant")),
                      names=NAMES).as_response()
    assert fast == muse == {"status": "unsupported", "actions": [], "reply_key": "askNoShopLeft", "reply_args": {}}


def test_both_shops_out_in_one_sentence_leaves_no_shop():
    r = ask.answer("no Libris and no Elefant", "en", state(["libris", "elefant"]), muse=model_says(), names=NAMES)
    assert r.as_response()["reply_key"] == "askNoShopLeft"


# ------------------------------------------------------------ the Custom answer on /solve


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _store(sid):
    return {"id": sid, "currency": "RON", "free_shipping_threshold_cents": 13500, "shipping_fee_cents": 1290,
            "per_order_fee_cents": 0}


def _item(iid, title, *offers):
    return {"id": iid, "title": title,
            "offers": [{"store_id": s, "price_cents": p, "seller_certainty": "direct"} for s, p in offers]}


def _solve(client, selected, items):
    body = {"source": "given", "stores": [_store("libris"), _store("elefant")], "items": items,
            "selected_store_ids": selected, "selected_within": True}
    res = client.post("/solve", json=body)
    assert res.status_code == 200, res.text
    return res.json()["custom"]


def test_leaving_out_the_only_shop_of_a_book_keeps_the_rest_chosen_and_names_the_book(client):
    items = [_item("gruffalo", "The Gruffalo", ("elefant", 13499)),
             _item("matilda", "Matilda", ("libris", 5661), ("elefant", 6499)),
             _item("gruffalo-ro", "Gruffalo", ("libris", 5700))]
    custom = _solve(client, ["libris"], items)
    assert custom["status"] == "not_possible"
    assert custom["selected_store_ids"] == ["libris"]
    assert custom["reason_code"] == "no_shop_left_lists"
    assert custom["reason_args"] == {"title": "The Gruffalo"}
    assert custom["reason"] == "no shop left lists The Gruffalo"


def test_every_book_no_remaining_shop_lists_is_named(client):
    items = [_item("gruffalo", "The Gruffalo", ("elefant", 13499)),
             _item("room", "Room on the Broom", ("elefant", 4999)),
             _item("gruffalo-ro", "Gruffalo", ("libris", 5700))]
    custom = _solve(client, ["libris"], items)
    assert custom["selected_store_ids"] == ["libris"]
    assert custom["reason_args"] == {"title": "The Gruffalo, Room on the Broom"}


def test_a_hand_picked_custom_set_keeps_its_wording(client):
    items = [_item("gruffalo", "The Gruffalo", ("elefant", 13499)), _item("gruffalo-ro", "Gruffalo", ("libris", 5700))]
    body = {"source": "given", "stores": [_store("libris"), _store("elefant")], "items": items,
            "selected_store_ids": ["libris"]}
    custom = client.post("/solve", json=body).json()["custom"]
    assert custom["reason_code"] == "no_chosen_shop_lists"

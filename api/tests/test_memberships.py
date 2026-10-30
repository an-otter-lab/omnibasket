"""Feature 5: declared memberships are rules read from the shop's page.

With today's data (Spike 3, 30 Oct 2026) Prime changes nothing on a
Romanian order and Genius is "rules not printed", so totals never move.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.memberships import apply_memberships, check_declared, load_profiles, memberships_payload
from shop_profiles.loader import ShopProfile
from solver.optimize import SolverError
from solver.types import Store

DECLARED = [None, ["amazon_prime"], ["emag_genius"], ["amazon_prime", "emag_genius"]]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


def _post(client: TestClient, declared: list[str] | None, **extra) -> dict:
    body = dict(extra)
    if declared is not None:
        body["memberships"] = declared
    response = client.post("/solve", json=body or None)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("declared", DECLARED)
def test_ro_v1_totals_do_not_move_with_memberships(client: TestClient, declared) -> None:
    body = _post(client, declared)
    assert body["cheapest"]["total_cents"] == 51516
    assert body["total_cents"] == 51516
    assert body["one_parcel"]["answer"]["total_cents"] == 55873
    assert body["one_parcel"]["best_store_id"] == "libris"


def test_payload_lists_prime_and_genius_with_source_and_date(client: TestClient) -> None:
    rows = {row["id"]: row for row in _post(client, ["amazon_prime"])["memberships"]}
    assert set(rows) == {"amazon_prime", "emag_genius"}
    prime = rows["amazon_prime"]
    assert prime["declared"] is True and prime["changes_totals"] is False
    assert prime["store_id"] == "amazon_de" and prime["effect"] == "none" and prime["read_status"] == "read"
    assert prime["source_url"] == "https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H"
    assert prime["read_date"] == "2026-10-30"
    # The RON threshold the solver already uses, for everyone, Prime included.
    assert prime["store_threshold_cents"] == 26217 and prime["store_currency"] == "RON"
    assert prime["everyone_rule"]["amount_cents"] == 4900 and prime["everyone_rule"]["currency"] == "EUR"
    assert prime["member_threshold_cents"] is None
    genius = rows["emag_genius"]
    assert genius["declared"] is False and genius["changes_totals"] is False
    assert genius["effect"] == "unknown" and genius["read_status"] == "refused"
    assert genius["source_url"] == "https://www.emag.ro/genius" and genius["read_date"] == "2026-10-30"
    # eMAG is not solved while its fees are null: no threshold is invented.
    assert genius["store_threshold_cents"] is None and genius["member_threshold_cents"] is None


def test_unknown_membership_is_a_400(client: TestClient) -> None:
    response = client.post("/solve", json={"memberships": ["libris_club"]})
    assert response.status_code == 400 and "unknown membership" in response.json()["error"]


@pytest.mark.parametrize("declared", DECLARED)
def test_given_basket_totals_do_not_move(client: TestClient, declared) -> None:
    stores = [
        {"id": "amazon_de", "currency": "RON", "free_shipping_threshold_cents": 26217,
         "shipping_fee_cents": 2000, "per_order_fee_cents": 0},
    ]
    items = [{"id": "a", "offers": [{"store_id": "amazon_de", "price_cents": 10000, "seller_certainty": "direct"}]}]
    body = _post(client, declared, stores=stores, items=items, source="given")
    assert body["total_cents"] == 12000
    assert {row["id"] for row in body["memberships"]} == {"amazon_prime", "emag_genius"}


# ---------------------------------------------------------------- generic effect


def _profile(membership: dict) -> ShopProfile:
    return ShopProfile.from_mapping(
        {
            "id": "shop", "name": "Shop", "domain": "shop.example", "status": "checked",
            "currency": "RON", "robots": None, "product_pages": {"strategy": "schema.org-first"},
            "shipping_rules": [], "memberships": [membership],
        }
    )


def _rule(**extra) -> dict:
    rule = {
        "id": "club", "name": "Club", "effect": "none", "read_status": "read",
        "source_url": "https://shop.example/club", "read_date": "2026-10-30", "evidence": "printed",
    }
    rule.update(extra)
    return rule


def test_a_later_free_threshold_rule_changes_only_the_data() -> None:
    profiles = [_profile(_rule(effect="free_threshold", threshold_cents=0))]
    store = Store("shop", "RON", 10000, 1500, 0)
    assert apply_memberships([store], [], profiles)[0].free_shipping_threshold_cents == 10000
    on = apply_memberships([store], ["club"], profiles)
    assert on[0].free_shipping_threshold_cents == 0
    row = memberships_payload(on, ["club"], profiles)[0]
    assert row["changes_totals"] is True and row["member_threshold_cents"] == 0


@pytest.mark.parametrize("effect", ["none", "unknown"])
def test_none_and_unknown_never_touch_the_store(effect) -> None:
    status = "refused" if effect == "unknown" else "read"
    profiles = [_profile(_rule(effect=effect, read_status=status))]
    store = Store("shop", "RON", 10000, 1500, 0)
    assert apply_memberships([store], ["club"], profiles) == [store]


def test_check_declared_dedupes_and_rejects_unknown() -> None:
    profiles = load_profiles()
    assert check_declared(["amazon_prime", "amazon_prime"], profiles) == ["amazon_prime"]
    with pytest.raises(SolverError):
        check_declared(["nope"], profiles)

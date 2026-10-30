"""R1: a shop's data file decides whether an unnamed seller is direct.

Approved policy (card A, 30 Oct 2026): a shop file may say ``seller_model:
direct_only`` when the shop sells only its own stock. A live offer from such
a shop then counts toward that shop's free-delivery bar even when the page
does not name a seller. eMAG and Amazon.de carry no such line, so their
offers stay unknown until the page names the seller.

The gap line is always threshold minus the qualifying subtotal, never the
bare threshold.
"""

from __future__ import annotations

from json import dumps
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.fetch_guard import GuardedFetch
from api.offers import ROOT
from api.cache import PageCache
from shop_profiles.loader import load_all


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "pages.sqlite"))


@pytest.fixture()
def cache(tmp_path: Path) -> PageCache:
    return PageCache(tmp_path / "cache.sqlite")


def _profile(shop_id: str):
    return next(profile for profile in load_all(ROOT / "data" / "shops") if profile.id == shop_id)


def _store(sid: str, threshold: int, shipping: int | None, fee: int = 0) -> dict:
    return {
        "id": sid,
        "currency": "RON",
        "free_shipping_threshold_cents": threshold,
        "shipping_fee_cents": shipping,
        "per_order_fee_cents": fee,
    }


def _item(iid: str, *offers: tuple[str, int, str]) -> dict:
    return {
        "id": iid,
        "offers": [
            {"store_id": store_id, "price_cents": price, "seller_certainty": certainty}
            for store_id, price, certainty in offers
        ],
    }


def _solve(client: TestClient, stores: list[dict], items: list[dict]) -> dict:
    response = client.post(
        "/solve",
        json={"source": "given", "stores": stores, "items": items, "selected_store_ids": [s["id"] for s in stores]},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------ the shop files


def test_free_delivery_policy_is_declared_in_the_three_shop_files() -> None:
    for shop_id in ("libris", "books_express", "bookzone"):
        assert _profile(shop_id).seller_model == "direct_only"
    # eMAG and Amazon.de may host third-party sellers: no policy line.
    for shop_id in ("emag", "amazon_de"):
        assert _profile(shop_id).seller_model == "mixed"


# ------------------------------------------------------------ live-shaped basket


def test_live_offers_over_the_bar_get_free_delivery(client: TestClient) -> None:
    """Libris at 169,84 lei, read live with no seller named: delivery 0, gap reached."""

    body = _solve(
        client,
        [_store("libris", 13500, 1290), _store("bookzone", 20000, 1090, 199)],
        [
            _item("a", ("libris", 10000, "unknown"), ("bookzone", 12000, "direct")),
            _item("b", ("libris", 6984, "unknown"), ("bookzone", 9000, "direct")),
        ],
    )
    libris = next(o for o in body["cheapest"]["orders"] if o["store_id"] == "libris")
    assert libris["qualifying_cents"] == 16984
    assert libris["threshold_crossed"] is True
    assert libris["delivery_cents"] == 0
    assert libris["order_total_cents"] == 16984
    assert libris["delivery_gap"] == {"status": "reached", "short_cents": 0, "threshold_cents": 13500}
    assert body["cheapest"]["total_cents"] == 16984


def test_free_delivery_gap_is_threshold_minus_qualifying(client: TestClient) -> None:
    """Libris at 100,00 lei: the gap is 35,00 lei, not the bare 135,00 lei bar."""

    body = _solve(
        client,
        [_store("libris", 13500, 1290), _store("bookzone", 20000, 1090, 199)],
        [
            _item("a", ("libris", 6000, "unknown"), ("bookzone", 12000, "direct")),
            _item("b", ("libris", 4000, "unknown"), ("bookzone", 9000, "direct")),
        ],
    )
    libris = next(o for o in body["cheapest"]["orders"] if o["store_id"] == "libris")
    assert libris["qualifying_cents"] == 10000
    assert libris["delivery_cents"] == 1290
    assert libris["delivery_gap"] == {"status": "short", "short_cents": 3500, "threshold_cents": 13500}
    assert libris["order_total_cents"] == 11290


def test_qualifying_counts_unknown_only_when_the_shop_file_says_direct() -> None:
    """The same cents: 0 delivery at a direct-only shop, charged at a mixed one."""

    from solver.optimize import solve
    from solver.types import Item, Offer, Store

    def _shop(direct_only: bool) -> Store:
        return Store(
            id="shop",
            currency="RON",
            free_shipping_threshold_cents=13500,
            shipping_fee_cents=1290,
            per_order_fee_cents=0,
            direct_only=direct_only,
        )

    items = [Item("a", (Offer("shop", 16984, "unknown"),))]
    policy = solve([_shop(True)], items)
    assert policy.total_cents == 16984
    assert policy.stores[0].qualifying_cents == 16984
    assert policy.stores[0].shipping_cents == 0
    assert policy.stores[0].unknown_cents == 0

    no_policy = solve([_shop(False)], items)
    assert no_policy.total_cents == 16984 + 1290
    assert no_policy.stores[0].qualifying_cents == 0
    assert no_policy.stores[0].shipping_cents == 1290
    assert no_policy.stores[0].unknown_cents == 16984


def test_free_delivery_policy_does_not_make_amazon_de_direct(client: TestClient) -> None:
    """Without the shop-file line an unnamed seller stays unknown and never qualifies."""

    response = client.post(
        "/solve",
        json={
            "source": "given",
            "stores": [_store("libris", 13500, 1290), _store("amazon_de", 26217, None)],
            "items": [
                _item("a", ("amazon_de", 15000, "unknown"), ("libris", 20000, "direct")),
                _item("b", ("amazon_de", 15000, "unknown"), ("libris", 20000, "direct")),
            ],
            "selected_store_ids": ["amazon_de"],
        },
    )
    assert response.status_code == 200, response.text
    order = response.json()["custom"]["orders"][0]
    assert order["store_id"] == "amazon_de"
    assert order["qualifying_cents"] == 0
    assert order["threshold_crossed"] is False
    assert order["delivery_cents"] is None
    assert order["delivery_gap"] == {"status": "short", "short_cents": 26217, "threshold_cents": 26217}


# ------------------------------------------------------------ the read path


PAGE = (
    '<html><script type="application/ld+json">'
    + dumps(
        {
            "@context": "https://schema.org",
            "@type": ["Product", "Book"],
            "name": "Ghici cat de mult te iubesc",
            "isbn": "9786068996011",
            "offers": {
                "@type": "Offer",
                "price": "57.00",
                "priceCurrency": "RON",
                "availability": "https://schema.org/InStock",
            },
        }
    )
    + "</script></html>"
)


@pytest.mark.parametrize(
    "shop_id,url",
    [
        ("libris", "https://www.libris.ro/carte/ghici/21197307"),
        ("books_express", "https://www.books-express.ro/ghici/p/x,9786068996011"),
        ("bookzone", "https://bookzone.ro/carte/ghici-cat-de-mult-te-iubesc"),
    ],
)
def test_free_delivery_read_of_a_direct_only_shop_marks_the_offer_direct(
    shop_id: str, url: str, cache, monkeypatch
) -> None:
    """A live offer whose page names no seller is direct at a direct-only shop."""

    import api.offers as offers

    def _fetch(target: str) -> GuardedFetch:
        return GuardedFetch(target, 200, "text/html", PAGE.encode(), PAGE, 0)

    monkeypatch.setattr(offers, "fetch", _fetch)
    result = offers.read_offers_sync(
        [shop_id], "9786068996011", "ghici", cache, index_lookup=lambda store, isbn: url
    )
    assert result[0].status == "ok"
    assert result[0].price_cents == 5700
    assert result[0].seller_certainty == "direct"


def test_free_delivery_policy_leaves_emag_unknown(cache, monkeypatch) -> None:
    """eMAG has no policy line: an unnamed seller stays unknown."""

    import api.offers as offers

    def _fetch(target: str) -> GuardedFetch:
        return GuardedFetch(target, 200, "text/html", PAGE.encode(), PAGE, 0)

    monkeypatch.setattr(offers, "fetch", _fetch)
    result = offers.read_offers_sync(
        ["emag"], "9786068996011", "ghici", cache, index_lookup=lambda store, isbn: "https://www.emag.ro/ghici/pd/DGJW95BBM/"
    )
    assert result[0].status == "ok"
    assert result[0].seller_certainty == "unknown"

"""P3: the Why checker and its fallback sentence in Romanian.

- RO "un magazin" is "a shop" (an article), not a shop count.
- A cheapest result of one order is not "o împărțire ... în 1 comandă".
"""

from __future__ import annotations

from api.explain_check import check_explanation, fallback_sentences


def _two_orders() -> dict:
    # Two orders at two shops; no list of length 1 anywhere, so 1 is not a shop count.
    return {
        "currency": "RON",
        "cheapest": {
            "currency": "RON",
            "total_cents": 9000,
            "order_count": 2,
            "orders": [
                {"store_id": "libris", "order_total_cents": 4000, "books": [{"price_cents": 4000}, {"price_cents": 0}]},
                {"store_id": "books_express", "order_total_cents": 5000, "books": [{"price_cents": 5000}, {"price_cents": 0}]},
            ],
        },
        "shops": [{"store_id": "libris"}, {"store_id": "books_express"}],
    }


def _one_order() -> dict:
    return {
        "currency": "RON",
        "cheapest": {
            "currency": "RON",
            "total_cents": 1000,
            "order_count": 1,
            "orders": [{"store_id": "libris", "order_total_cents": 1000, "books": [{"price_cents": 1000}]}],
        },
        "one_order": {"best_store_id": "libris", "answer": {"total_cents": 1000, "order_count": 1, "orders": []}},
        "shops": [{"store_id": "libris"}],
    }


def test_un_magazin_is_not_a_shop_count() -> None:
    text = "Cea mai ieftină împărțire este 90,00 lei în 2 comenzi. Nu există un magazin care să aibă toate cărțile."
    assert check_explanation(text, _two_orders()).ok


def test_number_and_word_shop_counts_are_still_checked() -> None:
    for text in ("Cele 2 comenzi vin de la 3 magazine.", "Cele 2 comenzi vin de la trei magazine."):
        result = check_explanation(text, _two_orders())
        assert not result.ok
        assert "magazine" in result.failures[0].span


def test_o_comanda_still_counts_as_one_order() -> None:
    result = check_explanation("O comandă la Libris costă 90,00 lei.", _two_orders())
    assert not result.ok
    assert result.failures[0].span.lower().startswith("o comand")


def test_one_order_fallback_reads_as_one_order() -> None:
    ro, en = fallback_sentences(_one_order())
    assert ro == "Cea mai ieftină variantă este o singură comandă la Libris: 10,00\u00a0lei."
    assert en == "The cheapest option is one order at Libris: 10,00\u00a0lei."
    assert "împărțire" not in ro and "1 comandă" not in ro
    assert check_explanation(ro, _one_order()).ok
    assert check_explanation(en, _one_order()).ok


def test_two_order_fallback_unchanged() -> None:
    ro, en = fallback_sentences(_two_orders())
    assert ro == "Cea mai ieftină împărțire este 90,00\u00a0lei în 2 comenzi, de la Libris și Books-Express."
    assert en == "The cheapest split is 90,00\u00a0lei in 2 orders, from Libris and Books-Express."

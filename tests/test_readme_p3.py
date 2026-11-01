"""P3: the README must not contradict the app (review 31 Oct, "README contradicts the app")."""

from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def test_no_stale_claims():
    for stale in (
        "Search-by-title is not available",
        "membership control stays disabled",
        "Membership is not implemented",
        "calls neither a store nor a model",
        "three result tabs",
        "three solve results",
    ):
        assert stale not in README, stale


def test_tabs_use_order_wording():
    assert "parcel" not in README.lower()
    assert "**1 order**" in README and "**Cheapest**" in README and "**Custom**" in README


def test_search_and_memberships_described():
    assert "title, author or ISBN search" in README
    assert "api/memberships.py" in README

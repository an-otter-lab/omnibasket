from pathlib import Path

import pytest

from shop_profiles.loader import ShopProfile, load_all, load_profile

ROOT = Path(__file__).resolve().parents[2]

def test_profiles_load_and_have_shipping_evidence():
    profiles = load_all(ROOT / "data" / "shops")
    by_id = {profile.id: profile for profile in profiles}
    assert set(by_id) == {"libris", "bookzone", "emag", "amazon_de", "books_express", "elefant", "paste_only"}
    for profile in profiles:
        want = "elefant-html" if profile.id == "elefant" else "schema.org-first"
        assert profile.product_pages["strategy"] == want
    for shop_id in set(by_id) - {"paste_only"}:
        profile = by_id[shop_id]
        assert profile.status == "checked" and profile.shipping_rules
        for rule in profile.shipping_rules:
            assert rule["source_url"].startswith("https://") and rule["read_date"]

def test_paste_only_unknown_shipping_stays_null():
    profile = load_profile(ROOT / "data" / "shops" / "paste_only.yaml")
    assert profile.status == "auto-read" and profile.shipping_rules is None

def test_checked_profile_cannot_allow_search_path():
    raw = {"id":"x", "name":"X", "domain":"x.example", "status":"checked", "currency":"RON", "robots":{"source_url":"https://x.example/robots.txt", "read_date":"2026-10-30", "allowed_paths":["/search/*"], "sitemaps":[]}, "product_pages":{"strategy":"schema.org-first"}, "shipping_rules":[]}
    with pytest.raises(ValueError, match="search paths"):
        ShopProfile.from_mapping(raw)

def test_rule_without_source_or_date_is_rejected():
    raw = {"id":"x", "name":"X", "domain":"x.example", "status":"checked", "currency":"RON", "robots":None, "product_pages":{"strategy":"schema.org-first"}, "shipping_rules":[{"kind":"free_threshold", "amount":100}]}
    with pytest.raises(ValueError):
        ShopProfile.from_mapping(raw)


# ------------------------------------------------------- memberships (feature 5)

def _with_membership(**override):
    rule = {
        "id": "club", "name": "Club", "effect": "none", "read_status": "read",
        "source_url": "https://x.example/club", "read_date": "2026-10-30", "evidence": "printed",
    }
    rule.update(override)
    rule = {k: v for k, v in rule.items() if v is not None}
    return {"id":"x", "name":"X", "domain":"x.example", "status":"checked", "currency":"RON", "robots":None, "product_pages":{"strategy":"schema.org-first"}, "shipping_rules":[], "memberships":[rule]}

def test_shop_memberships_load_from_data():
    by_id = {profile.id: profile for profile in load_all(ROOT / "data" / "shops")}
    prime, = by_id["amazon_de"].memberships
    assert prime["id"] == "amazon_prime" and prime["effect"] == "none"
    assert prime["source_url"] == "https://www.amazon.de/gp/help/customer/display.html?nodeId=GZXW7X6AKTHNUP6H"
    assert str(prime["read_date"]) == "2026-10-30" and prime["source_kind"] == "manual_capture"
    genius, = by_id["emag"].memberships
    assert genius["id"] == "emag_genius" and genius["effect"] == "unknown" and genius["read_status"] == "refused"
    assert genius["source_url"] == "https://www.emag.ro/genius" and str(genius["read_date"]) == "2026-10-30"
    for shop_id in {"libris", "bookzone", "books_express", "elefant", "paste_only"}:
        assert by_id[shop_id].memberships == ()

@pytest.mark.parametrize("override", [
    {"source_url": None}, {"source_url": "http://x.example/club"}, {"read_date": None},
    {"read_date": "30 Oct"}, {"effect": "discount"}, {"read_status": "maybe"},
    {"read_status": "refused"},
    {"effect": "free_threshold"}, {"effect": "free_threshold", "threshold_cents": -1},
    {"threshold_cents": 100}, {"evidence": None}, {"id": None},
])
def test_membership_rule_without_source_date_or_valid_effect_is_rejected(override):
    with pytest.raises(ValueError):
        ShopProfile.from_mapping(_with_membership(**override))

def test_valid_membership_rules_are_accepted():
    assert ShopProfile.from_mapping(_with_membership()).memberships[0]["id"] == "club"
    raw = _with_membership(effect="free_threshold", threshold_cents=0)
    assert ShopProfile.from_mapping(raw).memberships[0]["threshold_cents"] == 0
    raw = _with_membership(effect="unknown", read_status="refused")
    assert ShopProfile.from_mapping(raw).memberships[0]["effect"] == "unknown"

def test_non_live_profile_needs_manual_capture_memberships():
    raw = _with_membership()
    raw["live_reading"] = False
    with pytest.raises(ValueError, match="manual_capture"):
        ShopProfile.from_mapping(raw)


def test_elefant_profile_rules_and_strategy():
    """Elefant (3 Nov): free above 199 lei, else 16.99, and 9.99 processing on every order."""
    elefant = load_profile(ROOT / "data" / "shops" / "elefant.yaml")
    assert elefant.seller_model == "mixed" and elefant.currency == "RON"
    rules = {rule["kind"]: rule["amount"] for rule in elefant.shipping_rules}
    assert rules == {"free_threshold": 199.00, "below_threshold_fee": 16.99, "per_order_fee": 9.99}

def test_unknown_page_strategy_is_rejected():
    raw = {"id":"x", "name":"X", "domain":"x.example", "status":"checked", "currency":"RON", "robots":None, "product_pages":{"strategy":"model-reads-everything"}, "shipping_rules":[]}
    with pytest.raises(ValueError, match="product pages"):
        ShopProfile.from_mapping(raw)

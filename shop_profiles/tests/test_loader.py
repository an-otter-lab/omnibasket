from pathlib import Path

import pytest

from shop_profiles.loader import ShopProfile, load_all, load_profile

ROOT = Path(__file__).resolve().parents[2]

def test_profiles_load_and_have_shipping_evidence():
    profiles = load_all(ROOT / "data" / "shops")
    by_id = {profile.id: profile for profile in profiles}
    assert set(by_id) == {"libris", "bookzone", "emag", "amazon_de", "books_express", "paste_only"}
    for profile in profiles:
        assert profile.product_pages["strategy"] == "schema.org-first"
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

"""Declared memberships (feature 5): rules read from each shop's own page.

The rules live in ``data/shops/*.yaml`` under ``memberships``, each with a
``source_url`` and ``read_date``. This module reads the effect generically:

- ``none`` and ``unknown`` never change a store the solver sees;
- ``free_threshold`` swaps the store's free-delivery threshold for the
  member threshold printed on the rules page.

A rule read later changes only the YAML.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from shop_profiles.loader import ShopProfile, load_all
from solver.optimize import SolverError
from solver.types import Store

ROOT = Path(__file__).resolve().parents[1]
SHOPS_DIR = ROOT / "data" / "shops"


def load_profiles(directory: Path = SHOPS_DIR) -> list[ShopProfile]:
    return load_all(directory)


def membership_rules(profiles: list[ShopProfile]) -> list[tuple[ShopProfile, dict]]:
    return [(profile, rule) for profile in profiles for rule in profile.memberships]


def check_declared(declared: list[str] | None, profiles: list[ShopProfile]) -> list[str]:
    ids = list(dict.fromkeys(declared or []))
    known = {rule["id"] for _profile, rule in membership_rules(profiles)}
    unknown = [item for item in ids if item not in known]
    if unknown:
        raise SolverError("unknown membership: " + ", ".join(unknown))
    return ids


def apply_memberships(
    stores: list[Store], declared: list[str], profiles: list[ShopProfile]
) -> list[Store]:
    """Return the stores the solver sees with the declared memberships on."""

    on = set(declared)
    by_store = {store.id: store for store in stores}
    for profile, rule in membership_rules(profiles):
        if rule["id"] not in on or profile.id not in by_store:
            continue
        if rule["effect"] == "free_threshold":
            by_store[profile.id] = replace(
                by_store[profile.id], free_shipping_threshold_cents=int(rule["threshold_cents"])
            )
    return [by_store[store.id] for store in stores]


def memberships_payload(
    stores: list[Store], declared: list[str], profiles: list[ShopProfile]
) -> list[dict]:
    """One row per membership a shopper can declare, declared or not."""

    on = set(declared)
    by_store = {store.id: store for store in stores}
    rows = []
    for profile, rule in membership_rules(profiles):
        store = by_store.get(profile.id)
        changes = rule["effect"] == "free_threshold" and store is not None
        rows.append(
            {
                "id": rule["id"],
                "store_id": profile.id,
                "store_name": profile.name,
                "name": rule["name"],
                "effect": rule["effect"],
                "read_status": rule["read_status"],
                "declared": rule["id"] in on,
                "changes_totals": changes,
                "source_url": rule["source_url"],
                "read_date": str(rule["read_date"]),
                "evidence": rule["evidence"],
                "member_threshold_cents": rule.get("threshold_cents"),
                # The threshold the solver uses for this store, in the store currency.
                "store_threshold_cents": store.free_shipping_threshold_cents if store else None,
                "store_currency": store.currency if store else None,
                # The shop's own free-delivery rule for everyone, as printed.
                "everyone_rule": _everyone_rule(profile),
            }
        )
    return rows


def _everyone_rule(profile: ShopProfile) -> dict | None:
    for rule in profile.shipping_rules or []:
        if rule.get("kind") == "free_threshold" and rule.get("amount") is not None:
            return {
                "amount_cents": int(Decimal(str(rule["amount"])) * 100),
                "currency": rule.get("currency"),
                "source_url": rule.get("source_url"),
                "read_date": str(rule.get("read_date")),
            }
    return None

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

@dataclass(frozen=True)
class ShopProfile:
    id: str
    name: str
    domain: Optional[str]
    status: str
    currency: Optional[str]
    robots: Optional[dict]
    product_pages: dict
    shipping_rules: Optional[list]
    # Memberships a shopper can declare (feature 5). Each is a rule read
    # from the shop's own page, with its source and read date.
    memberships: tuple = ()
    # Who sells on this shop: "direct_only" when the shop sells only its own
    # stock (no third-party marketplace sellers). A live offer from such a
    # shop is direct even when the page does not name a seller.
    seller_model: str = "mixed"

    @classmethod
    def from_mapping(cls, raw: dict) -> "ShopProfile":
        required = {"id", "name", "domain", "status", "currency", "robots", "product_pages", "shipping_rules"}
        missing = required - set(raw)
        if missing:
            raise ValueError("missing profile fields: " + ", ".join(sorted(missing)))
        if raw["status"] not in {"checked", "auto-read"}:
            raise ValueError("invalid profile status")
        seller_model = raw.get("seller_model", "mixed")
        if seller_model not in SELLER_MODELS:
            raise ValueError("seller_model must be one of: " + ", ".join(sorted(SELLER_MODELS)))
        if not isinstance(raw["product_pages"], dict) or raw["product_pages"].get("strategy") not in PAGE_STRATEGIES:
            raise ValueError("product pages must use one of: " + ", ".join(sorted(PAGE_STRATEGIES)))
        rules = raw["shipping_rules"]
        if raw["status"] == "checked" and not isinstance(rules, list):
            raise ValueError("checked profiles require shipping rules list")
        if rules is not None:
            if not isinstance(rules, list):
                raise ValueError("shipping_rules must be a list or null")
            for rule in rules:
                if not isinstance(rule, dict) or not rule.get("kind") or not rule.get("source_url"):
                    raise ValueError("each shipping rule needs a kind and source_url")
                try:
                    date.fromisoformat(str(rule.get("read_date", "")))
                except ValueError:
                    raise ValueError("each shipping rule needs an ISO read_date")
                # manual_capture rules don't need robots-allowed sources
                source_kind = rule.get("source_kind", "fetched")
                if source_kind not in {"fetched", "manual_capture"}:
                    raise ValueError("source_kind must be 'fetched' or 'manual_capture'")
        # Validate currency consistency for non-live profiles
        live_reading = raw.get("live_reading", True)
        if live_reading is False and rules is not None:
            # A profile that is never read live must not claim a fetched source
            for rule in rules:
                source_kind = rule.get("source_kind", "fetched")
                if source_kind != "manual_capture":
                    raise ValueError("non-live profiles require all rules to be source_kind: manual_capture")
        if raw["robots"] is not None:
            robots = raw["robots"]
            if not robots.get("source_url") or not robots.get("read_date"):
                raise ValueError("robots evidence requires source_url and read_date")
            if not isinstance(robots.get("allowed_paths"), list) or not isinstance(robots.get("sitemaps"), list):
                raise ValueError("robots evidence requires allowed_paths and sitemaps lists")
            if raw["status"] == "checked" and any("search" in path.lower() for path in robots["allowed_paths"]):
                raise ValueError("checked profiles may not allow shop search paths")
        if raw["status"] == "auto-read" and rules is not None:
            raise ValueError("paste-only rules must remain null until read")
        memberships = tuple(_memberships(raw.get("memberships"), live_reading))
        return cls(
            **{key: raw[key] for key in required},
            memberships=memberships,
            seller_model=seller_model,
        )


# How a product page is read. Both are plain code; a model only fills gaps.
#   schema.org-first  the page's schema.org JSON-LD (api/schema_org.py)
#   elefant-html      Elefant's own markup (api/elefant_page.py): it has no JSON-LD
PAGE_STRATEGIES = frozenset({"schema.org-first", "elefant-html"})

# Who sells on the shop.
#   mixed        the shop may host third-party sellers (default: seller unknown)
#   direct_only  the shop sells only its own stock, so every offer is direct
SELLER_MODELS = frozenset({"mixed", "direct_only"})

# What a declared membership does to an order.
#   none            the rules page was read and the membership changes nothing here
#   unknown         the rules page could not be read: "rules not printed"
#   free_threshold  members get free delivery from threshold_cents (store currency)
# A rule read later only changes the YAML; the solver reads the effect generically.
MEMBERSHIP_EFFECTS = frozenset({"none", "unknown", "free_threshold"})
MEMBERSHIP_READ_STATUSES = frozenset({"read", "refused"})


def _memberships(rows: Any, live_reading: bool) -> list[dict]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("memberships must be a list or null")
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each membership must be a mapping")
        for key in ("id", "name", "effect", "read_status", "evidence"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"each membership needs {key}")
        if row["id"] in seen:
            raise ValueError(f"duplicate membership id {row['id']!r}")
        seen.add(row["id"])
        source_url = row.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise ValueError("each membership needs an https source_url")
        try:
            date.fromisoformat(str(row.get("read_date", "")))
        except ValueError:
            raise ValueError("each membership needs an ISO read_date")
        if row["effect"] not in MEMBERSHIP_EFFECTS:
            raise ValueError("membership effect must be one of: " + ", ".join(sorted(MEMBERSHIP_EFFECTS)))
        if row["read_status"] not in MEMBERSHIP_READ_STATUSES:
            raise ValueError("membership read_status must be 'read' or 'refused'")
        if row["read_status"] == "refused" and row["effect"] != "unknown":
            raise ValueError("a membership whose page refused the read must have effect 'unknown'")
        if row["effect"] == "free_threshold":
            cents = row.get("threshold_cents")
            if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
                raise ValueError("free_threshold memberships need integer threshold_cents >= 0")
        elif "threshold_cents" in row:
            raise ValueError("only free_threshold memberships carry threshold_cents")
        source_kind = row.get("source_kind", "fetched")
        if source_kind not in {"fetched", "manual_capture"}:
            raise ValueError("source_kind must be 'fetched' or 'manual_capture'")
        if live_reading is False and source_kind != "manual_capture":
            raise ValueError("non-live profiles require memberships to be source_kind: manual_capture")
        out.append(dict(row))
    return out


def load_profile(path: str | Path) -> ShopProfile:
    with Path(path).open(encoding="utf-8") as stream:
        raw: Any = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError("profile must be a YAML mapping")
    return ShopProfile.from_mapping(raw)

def load_all(directory: str | Path) -> list[ShopProfile]:
    return [load_profile(path) for path in sorted(Path(directory).glob("*.yaml"))]

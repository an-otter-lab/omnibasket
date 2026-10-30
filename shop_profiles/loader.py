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

    @classmethod
    def from_mapping(cls, raw: dict) -> "ShopProfile":
        required = {"id", "name", "domain", "status", "currency", "robots", "product_pages", "shipping_rules"}
        missing = required - set(raw)
        if missing:
            raise ValueError("missing profile fields: " + ", ".join(sorted(missing)))
        if raw["status"] not in {"checked", "auto-read"}:
            raise ValueError("invalid profile status")
        if not isinstance(raw["product_pages"], dict) or raw["product_pages"].get("strategy") != "schema.org-first":
            raise ValueError("product pages must use schema.org-first")
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
        return cls(**{key: raw[key] for key in required})

def load_profile(path: str | Path) -> ShopProfile:
    with Path(path).open(encoding="utf-8") as stream:
        raw: Any = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError("profile must be a YAML mapping")
    return ShopProfile.from_mapping(raw)

def load_all(directory: str | Path) -> list[ShopProfile]:
    return [load_profile(path) for path in sorted(Path(directory).glob("*.yaml"))]

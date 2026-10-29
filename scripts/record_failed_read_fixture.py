"""Record the failed-read /solve payload for the UI (Cărturești is not in data/baskets/ro-v1.yaml).

The real basket has no failed read. This runs the real solve and plan code on the
locked basket and adds one shop whose pages could not be read: three tries, a
failed_at time, no offers. Nothing is priced for that shop. Output is a /solve payload
the UI loads with ?fixture=failed-read.

    PYTHONPATH=. .venv/bin/python scripts/record_failed_read_fixture.py ui/public/fixtures/failed-read.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from api.app import DEFAULT_DB, _drop_excluded_store_offers
from api.basket import excluded_for_unresolved_fees, load_locked, locked_shop_rows
from api.cache import open_seeded
from api.solve_service import context_from_locked, offers_from_cache, solution_payload

SHOP_ID = "carturesti"
FAILED_AT = "2026-10-28T09:41:00+02:00"


def main(out: Path) -> None:
    _day, _currency, stores, _items, pages = load_locked()
    items, events = offers_from_cache(open_seeded(DEFAULT_DB), pages, source="cache")
    items = _drop_excluded_store_offers(stores, items)
    shops = locked_shop_rows() + [{"id": SHOP_ID, "solvable": True, "read_at": None, "fees": {}}]
    ctx = context_from_locked(stores, items, pages, events, shops)
    failed = [
        {
            "item_id": item.id,
            "store_id": SHOP_ID,
            "reason": "page_unreadable",
            "attempts": 3,
            "failed_at": FAILED_AT,
        }
        for item in items
    ]
    ctx = replace(ctx, failed_reads=ctx.failed_reads + failed)
    payload = solution_payload(
        stores,
        items,
        excluded_stores=excluded_for_unresolved_fees(),
        plan_ctx=ctx,
    )
    payload["source"] = "fixture"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

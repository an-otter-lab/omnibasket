#!/usr/bin/env python3
"""Report the Muse Spark read stored for every page in the demo seed.

The reads are already in ``data/cache/ro-v1-seed.json``: one ``model_json`` per
page, produced when the pages were captured. This tool never calls a model,
opens a browser or fetches a shop, and it never spends: it re-checks each stored
read against the facts and the locked basket the demo prices come from.

A page whose read disagrees with the capture is reported as a mismatch; the
stored price is never changed here.

Commands:
    python3 tools/muse_reads.py                 # every page in the seed
    python3 tools/muse_reads.py --items ghici --stores libris
    python3 tools/muse_reads.py --json
Exit code is 1 when any read mismatches or is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402  (the model id and the ledger's TZ)

from matching.validate import compare_read_to_capture  # noqa: E402

SEED = ROOT / "data" / "cache" / "ro-v1-seed.json"


def captured_prices() -> dict:
    """(store_id, item_id) -> what the locked basket captured for that offer."""

    from api.basket import load_locked

    _day, _currency, _stores, _items, pages = load_locked()
    return {
        (page["store_id"], page["item_id"]): {
            "price_cents": page["price_cents"],
            "isbn13": page["isbn13"] or None,
        }
        for page in pages
    }


def report(seed: dict, stores: set[str], items: set[str]) -> dict:
    captured = captured_prices()
    job = {"pages": 0, "match": 0, "mismatch": 0, "not_read": 0}
    rows = []
    for page in seed["pages"]:
        key = (page["store_id"], page["item_id"])
        if stores and page["store_id"] not in stores:
            continue
        if items and page["item_id"] not in items:
            continue
        record = page.get("model_json")
        check = compare_read_to_capture(
            record,
            price_cents=captured.get(key, {}).get("price_cents"),
            isbn13=captured.get(key, {}).get("isbn13"),
            currency=seed.get("currency") or "RON",
        )
        job["pages"] += 1
        job[check["status"]] = job.get(check["status"], 0) + 1
        rows.append(
            {
                "store": page["store_id"],
                "item": page["item_id"],
                "model": (record or {}).get("model"),
                "read_at": (record or {}).get("read_at"),
                "check": check["status"],
                "mismatch_fields": list(check["mismatch_fields"]),
            }
        )
    job["ok"] = job["mismatch"] == 0 and job["not_read"] == 0
    return {"job": job, "rows": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stored Muse Spark reads for the saved demo pages")
    parser.add_argument("--seed", default=str(SEED))
    parser.add_argument("--stores", default="", help="comma list of store ids")
    parser.add_argument("--items", default="", help="comma list of item ids")
    parser.add_argument("--json", action="store_true", help="one JSON object per page")
    args = parser.parse_args(argv)

    seed = json.loads(Path(args.seed).read_text())
    stores = set(filter(None, args.stores.split(",")))
    items = set(filter(None, args.items.split(",")))
    result = report(seed, stores, items)
    if args.json:
        for row in result["rows"]:
            print(json.dumps(row, ensure_ascii=False))
    else:
        for row in result["rows"]:
            print(
                "%-10s %-8s %-16s %-8s %s"
                % (row["store"], row["item"], row["model"] or "-", row["check"], ",".join(row["mismatch_fields"]))
            )
    print(json.dumps({"job": result["job"], "tz": str(meta_budget.TZ)}, ensure_ascii=False))
    return 0 if result["job"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

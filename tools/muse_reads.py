#!/usr/bin/env python3
"""Read every saved product page in the demo seed with Muse Spark, in replay mode.

The page text already sits in ``data/cache/ro-v1-seed.json``; this script never
opens a browser and never fetches a shop. One Muse Spark call per page, routed
through ``tools/meta_budget.py`` so every call lands in the spend ledger.

The read is stored next to its page under ``model_json``: the model id, the read
time, the fields the model returned and the check against the captured page.
A price, fee or threshold from the capture is never overwritten.

Commands:
    python3 tools/muse_reads.py                 # all pages in the seed
    python3 tools/muse_reads.py --skip-existing
    python3 tools/muse_reads.py --items ghici --stores libris
    python3 tools/muse_reads.py --dry-run       # show the plan, spend nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "spike"))

import extract  # noqa: E402  (spike/extract.py: PROMPT, call_model, parse_json)
import meta_budget  # noqa: E402  (the spend ledger and the cap)

from matching.validate import compare_read_to_capture, validate_extraction  # noqa: E402

SEED = ROOT / "data" / "cache" / "ro-v1-seed.json"
JOB_CAP_USD = 1.0
MAX_TEXT_CHARS = 30000
MAX_OUT_TOKENS = 2500


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


def estimate_usd(text: str) -> float:
    """Worst-case cost of one text read, at the ledger's list rates."""

    tokens_in = int(len(text) / 4) + 200
    return meta_budget.compute_cost(tokens_in, MAX_OUT_TOKENS)


def read_pages(seed: dict, only: set[tuple[str, str]], dry_run: bool) -> dict:
    captured = captured_prices()
    model_id = meta_budget.MODEL
    job = {"calls": 0, "cost_usd": 0.0, "match": 0, "mismatch": 0, "not_read": 0}
    rows = []
    for page in seed["pages"]:
        key = (page["store_id"], page["item_id"])
        if only and key not in only:
            continue
        rows.append(page)

    for page in rows:
        text = (page.get("page_text") or "")[:MAX_TEXT_CHARS]
        if not text.strip():
            page["model_json"] = {
                "model": model_id,
                "read_at": None,
                "status": "NO_TEXT",
                "fields": None,
                "check": {"status": "not_read", "mismatch_fields": [], "reason": "no_page_text"},
            }
            print(json.dumps({"store": page["store_id"], "item": page["item_id"], "read": "NO_TEXT"}))
            continue
        estimate = estimate_usd(text)
        if job["cost_usd"] + estimate > JOB_CAP_USD:
            print(
                json.dumps(
                    {
                        "stop": "job cap reached",
                        "spent_usd": round(job["cost_usd"], 6),
                        "next_estimate_usd": round(estimate, 6),
                        "job_cap_usd": JOB_CAP_USD,
                    }
                )
            )
            break
        if dry_run:
            print(json.dumps({"store": page["store_id"], "item": page["item_id"], "estimate_usd": round(estimate, 6)}))
            continue
        meta_budget.assert_can_spend(estimate)
        content = [{"type": "text", "text": extract.PROMPT + "\n\nPAGE TEXT:\n" + text}]
        raw, latency_ms, tokens, endpoint = extract.call_model(content)
        tokens_in = int(tokens[0] or 0)
        tokens_out = int(tokens[1] or 0)
        cost = meta_budget.compute_cost(tokens_in, tokens_out)
        meta_budget.record(
            tokens_in,
            tokens_out,
            cost,
            note="muse-reads %s/%s" % (page["store_id"], page["item_id"]),
            extra={"endpoint": endpoint, "latency_ms": latency_ms, "cost_source": "computed_list_rate"},
        )
        job["calls"] += 1
        job["cost_usd"] += cost

        parsed, json_ok = extract.parse_json(raw)
        fields = None
        validation = None
        status = "OK" if json_ok and isinstance(parsed, dict) else "BAD_JSON"
        if status == "OK":
            fields, validation = validate_extraction(parsed)
        check = compare_read_to_capture(
            {"status": status, "fields": fields},
            price_cents=captured.get((page["store_id"], page["item_id"]), {}).get("price_cents"),
            isbn13=captured.get((page["store_id"], page["item_id"]), {}).get("isbn13"),
            currency=seed.get("currency") or "RON",
        )
        page["model_json"] = {
            "model": model_id,
            "variant": "b_text",
            "replay": True,
            "browser_launched": False,
            "read_at": datetime.now(meta_budget.TZ).isoformat(timespec="seconds"),
            "status": status,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 8),
            "latency_ms": latency_ms,
            "endpoint": endpoint,
            "fields": fields,
            "validation": validation,
            "check": check,
            "raw": raw,
        }
        job[check["status"]] = job.get(check["status"], 0) + 1
        print(
            json.dumps(
                {
                    "store": page["store_id"],
                    "item": page["item_id"],
                    "read": status,
                    "check": check["status"],
                    "fields": check["mismatch_fields"],
                    "price_cents": None
                    if not fields
                    else round(float(fields.get("price") or 0) * 100),
                    "tokens": [tokens_in, tokens_out],
                    "cost_usd": round(cost, 6),
                },
                ensure_ascii=False,
            )
        )
        SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")

    job["matches"] = job.pop("match", 0)
    job["mismatches"] = job.pop("mismatch", 0)
    return job


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Muse Spark reads for the saved demo pages")
    parser.add_argument("--seed", default=str(SEED))
    parser.add_argument("--stores", default="", help="comma list of store ids")
    parser.add_argument("--items", default="", help="comma list of item ids")
    parser.add_argument("--skip-existing", action="store_true", help="keep pages that already have a read")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    seed_path = Path(args.seed)
    seed = json.loads(seed_path.read_text())
    stores = set(filter(None, args.stores.split(",")))
    items = set(filter(None, args.items.split(",")))
    only = {
        (page["store_id"], page["item_id"])
        for page in seed["pages"]
        if (not stores or page["store_id"] in stores)
        and (not items or page["item_id"] in items)
        and not (args.skip_existing and page.get("model_json"))
    }
    meta_budget.load_dotenv()
    if not meta_budget.os.environ.get("META_API_KEY"):
        print("META_API_KEY is not set; nothing read, nothing spent")
        return 2
    job = read_pages(seed, only, args.dry_run)
    if not args.dry_run:
        print(json.dumps({"job": job}, ensure_ascii=False))
        print("\n".join(meta_budget.status_lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

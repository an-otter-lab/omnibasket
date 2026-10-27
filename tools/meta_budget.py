#!/usr/bin/env python3
"""Muse Spark spend ledger and 50 USD cap.

Every call this process makes is refused before it is sent if the ledger total
plus the estimate would reach 50 USD. The external hourly audit reads exactly
~/Projects/omnibasket/data/meta-spend.jsonl and sums cost_usd.

Commands: status, check, calibrate, model, selftest.
Never prints the API key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CAP_USD = 50.0
# Published Meta Model API list rates for muse-spark-1.3 (not the Contributor tier).
# Computed cost uses these until a response includes its own cost figure.
RATE_IN_PER_M = 1.25
RATE_OUT_PER_M = 4.25
MODEL = "muse-spark-1.3"
LEDGER = Path("~/Projects/omnibasket/data/meta-spend.jsonl")
MAIN_ENV = Path("~/Projects/omnibasket/.env")
TZ = ZoneInfo("Europe/Bucharest")


class CapExceeded(RuntimeError):
    def __init__(self, spent, estimate):
        self.spent = spent
        self.estimate = estimate
        super().__init__(
            "refused: spend %.6f + estimate %.6f would reach the %.2f USD cap" % (spent, estimate, CAP_USD)
        )


def ledger_path():
    override = os.environ.get("META_SPEND_PATH")
    return Path(override) if override else LEDGER


def compute_cost(tokens_in, tokens_out):
    return (int(tokens_in) / 1_000_000.0) * RATE_IN_PER_M + (int(tokens_out) / 1_000_000.0) * RATE_OUT_PER_M


def _iter_rows(path):
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and "cost_usd" in row:
                yield row


def spent_usd(path=None):
    path = path or ledger_path()
    total = 0.0
    for row in _iter_rows(path):
        total += float(row["cost_usd"])
    return total


def tonight_usd(path=None):
    path = path or ledger_path()
    day = datetime.now(TZ).date().isoformat()
    total = 0.0
    for row in _iter_rows(path):
        ts = str(row.get("ts", ""))
        if ts[:10] == day:
            total += float(row["cost_usd"])
    return total


def would_exceed(estimate_usd, path=None):
    """True if this call would take the ledger total to or past the cap.
    The audit sums every cost_usd line, so the cap is that same total, not a
    separate window. tonight_usd is reported by status only.
    """
    estimate_usd = float(estimate_usd)
    if estimate_usd < 0:
        raise ValueError("estimate must be >= 0")
    return spent_usd(path) + estimate_usd >= CAP_USD


def assert_can_spend(estimate_usd, path=None):
    if would_exceed(estimate_usd, path):
        raise CapExceeded(spent_usd(path), float(estimate_usd))


def record(tokens_in, tokens_out, cost_usd, model=MODEL, note=None, extra=None):
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "model": model,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "cost_usd": round(float(cost_usd), 8),
    }
    if note:
        row["note"] = note
    if extra:
        for k, v in extra.items():
            if k in row or k.lower().find("key") >= 0 or k.lower().find("token") >= 0 and k not in ("tokens_in", "tokens_out"):
                continue
            row[k] = v
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def _redact(text):
    key = os.environ.get("META_API_KEY")
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return text


def status_lines():
    path = ledger_path()
    rows = list(_iter_rows(path))
    spent = sum(float(r["cost_usd"]) for r in rows)
    night = tonight_usd(path)
    return [
        "ledger: %s" % path,
        "calls: %d" % len(rows),
        "spend_usd: %.6f" % spent,
        "tonight_usd: %.6f" % night,
        "cap_usd: %.2f" % CAP_USD,
        "remaining_usd: %.6f" % (CAP_USD - spent),
        "rates_usd_per_mtok: in %.2f out %.2f" % (RATE_IN_PER_M, RATE_OUT_PER_M),
        "key: not shown",
    ]


def cmd_status(_a):
    print("\n".join(status_lines()))
    return 0


def cmd_check(a):
    est = a.usd
    ok = not would_exceed(est)
    print("estimate_usd: %.6f" % est)
    print("spend_usd: %.6f" % spent_usd())
    print("allowed: %s" % ("yes" if ok else "no"))
    print("key: not shown")
    return 0 if ok else 2


def load_dotenv():
    """Load KEY=VALUE into the environment. Never prints values."""
    candidates = [MAIN_ENV, Path(__file__).resolve().parents[1] / ".env"]
    seen = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v


def _post(path, body):
    base = os.environ.get("META_API_BASE", "https://api.meta.ai/v1").rstrip("/")
    key = os.environ.get("META_API_KEY")
    if not key:
        raise RuntimeError("META_API_KEY is not set")
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _usage_tokens(usage):
    usage = usage or {}
    tin = usage.get("input_tokens", usage.get("prompt_tokens"))
    tout = usage.get("output_tokens", usage.get("completion_tokens"))
    return int(tin or 0), int(tout or 0)


def _response_cost(payload):
    """Return a provider cost if the body actually carries one. Never invent it."""
    if not isinstance(payload, dict):
        return None
    for key in ("cost", "cost_usd"):
        if isinstance(payload.get(key), (int, float)):
            return float(payload[key])
    usage = payload.get("usage") or {}
    for key in ("cost", "cost_usd", "total_cost"):
        if isinstance(usage.get(key), (int, float)):
            return float(usage[key])
    return None


def guarded_post(body, estimate_usd, note):
    """Check the cap, send one Meta call, record tokens and computed cost."""
    assert_can_spend(estimate_usd)
    t0 = time.time()
    endpoint = "/responses"
    try:
        payload = _post("/responses", body)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            # Do not include the body: it can echo request headers in some proxies.
            raise RuntimeError("model HTTP %s" % e.code) from None
        endpoint = "/chat/completions"
        payload = _post("/chat/completions", body)
    tin, tout = _usage_tokens(payload.get("usage"))
    computed = compute_cost(tin, tout)
    billed = _response_cost(payload)
    # A call that already happened is recorded even if the actual cost crosses
    # the cap; the next call is refused. The pre-check uses the estimate.
    row = record(
        tin,
        tout,
        computed,
        note=note,
        extra={
            "endpoint": endpoint,
            "latency_ms": int((time.time() - t0) * 1000),
            "provider_cost_usd": None if billed is None else round(billed, 8),
            "cost_source": "computed_list_rate" if billed is None else "provider",
        },
    )
    return payload, row


def cmd_calibrate(_a):
    load_dotenv()
    # Worst case for this prompt: ~50 input tokens and 32 output tokens.
    estimate = compute_cost(50, 32)
    body = {
        "model": os.environ.get("META_MODEL", MODEL),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply with the single word pong."}]}],
        "max_output_tokens": 16,
    }
    try:
        payload, row = guarded_post(body, estimate, note="calibrate")
    except CapExceeded as e:
        print(_redact(str(e)))
        return 2
    text = payload.get("output_text") or ""
    print("calibrate: ok")
    print("model: %s" % row["model"])
    print("tokens_in: %s" % row["tokens_in"])
    print("tokens_out: %s" % row["tokens_out"])
    print("cost_usd: %.8f" % row["cost_usd"])
    print("latency_ms: %s" % row.get("latency_ms"))
    print("provider_cost_usd: %s" % row.get("provider_cost_usd"))
    print("reply_chars: %d" % len(text.strip()))
    print("\n".join(status_lines()))
    return 0


def _estimate_content(content):
    chars = 0
    images = 0
    for part in content:
        if part.get("type") == "text":
            chars += len(part.get("text") or "")
        else:
            images += 1
    # Text ~4 chars/token. A viewport screenshot was ~1,711 tokens in the US spike.
    tin = int(chars / 4) + images * 2000 + 200
    return compute_cost(tin, 2500)


def cmd_model(a):
    """Run spike/extract.py's model phase with call_model routed through the cap.
    Does not modify extract.py. Text variant first; screenshot only as fallback.
    """
    load_dotenv()
    spike = Path(__file__).resolve().parents[1] / "spike"
    sys.path.insert(0, str(spike))
    import extract  # noqa: E402

    orig = extract.call_model

    def wrapped(content):
        est = _estimate_content(content)
        assert_can_spend(est)
        out, ms, toks, ep = orig(content)
        tin, tout = int(toks[0] or 0), int(toks[1] or 0)
        cost = compute_cost(tin, tout)
        record(tin, tout, cost, note="extract-model", extra={"endpoint": ep, "latency_ms": ms, "cost_source": "computed_list_rate"})
        return out, ms, toks, ep

    extract.call_model = wrapped
    stores = set(filter(None, (a.stores or "").split(",")))
    variants = [v for v in (a.variants or "b_text").split(",") if v]
    root = a.replay
    try:
        runs = extract.model_phase(stores, set(variants), root=root, replay=True)
    except CapExceeded as e:
        print(_redact(str(e)))
        return 2
    # Screenshot fallback only when text did not return parseable JSON.
    if variants == ["b_text"] or (len(variants) == 1 and variants[0] == "b_text"):
        failed = []
        for (name, variant), rec in runs.items():
            if variant == "b_text" and not (rec.get("status") == "OK" and rec.get("json_ok")):
                failed.append(name)
        if failed:
            print(json.dumps({"fallback": "a_screenshot", "stores": failed}))
            try:
                extract.model_phase(set(failed), {"a_screenshot"}, root=root, replay=True)
            except CapExceeded as e:
                print(_redact(str(e)))
                return 2
    print("\n".join(status_lines()))
    return 0


def cmd_selftest(_a):
    """Prove the cap and that status does not echo a key. Uses a temp ledger only."""
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="meta-budget-")) / "spend.jsonl"
    os.environ["META_SPEND_PATH"] = str(tmp)
    os.environ["META_API_KEY"] = "test-key-should-not-appear-9f3c"
    record(10, 10, 49.99, note="selftest-fill")
    if not would_exceed(0.02):
        print("selftest fail: 49.99 + 0.02 must be refused")
        return 1
    try:
        assert_can_spend(0.02)
        print("selftest fail: assert_can_spend did not raise")
        return 1
    except CapExceeded:
        pass
    if would_exceed(0.0):
        # 49.99 is still under the cap; a zero estimate must be allowed.
        print("selftest fail: zero estimate refused while under the cap")
        return 1
    # Crossing exactly 50 is refused. 49.99 + 0.009 = 49.999 is still under.
    if would_exceed(0.01):
        pass
    else:
        print("selftest fail: 49.99 + 0.01 must reach the cap")
        return 1
    text = "\n".join(status_lines())
    if "test-key-should-not-appear" in text or "9f3c" in text:
        print("selftest fail: status exposed the key")
        return 1
    if "key: not shown" not in text:
        print("selftest fail: status missing key line")
        return 1
    # A fresh ledger under the cap accepts a small estimate and records computed cost.
    tmp2 = tmp.parent / "fresh.jsonl"
    os.environ["META_SPEND_PATH"] = str(tmp2)
    assert_can_spend(0.001)
    row = record(1000, 1000, compute_cost(1000, 1000), note="selftest-rate")
    expect = compute_cost(1000, 1000)
    if abs(row["cost_usd"] - round(expect, 8)) > 1e-9:
        print("selftest fail: cost mismatch")
        return 1
    if abs(spent_usd() - row["cost_usd"]) > 1e-9:
        print("selftest fail: spent mismatch")
        return 1
    print("selftest: pass")
    print(text)
    print("sample_cost_1k_1k: %.8f" % row["cost_usd"])
    # Drop the fake key so later commands in this process cannot leak it.
    os.environ.pop("META_API_KEY", None)
    os.environ.pop("META_SPEND_PATH", None)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Muse Spark spend ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    c = sub.add_parser("check")
    c.add_argument("--usd", type=float, required=True)
    c.set_defaults(fn=cmd_check)
    sub.add_parser("calibrate").set_defaults(fn=cmd_calibrate)
    m = sub.add_parser("model")
    m.add_argument("--replay", required=True)
    m.add_argument("--stores", default="")
    m.add_argument("--variants", default="b_text")
    m.set_defaults(fn=cmd_model)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:
        print(_redact(type(e).__name__ + ": " + str(e)[:300]))
        return 1


if __name__ == "__main__":
    sys.exit(main())

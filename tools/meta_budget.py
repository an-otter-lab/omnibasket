#!/usr/bin/env python3
"""Muse Spark spend ledger and 50 USD cap.

Every call this process makes is refused before it is sent if the ledger total
plus the estimate would reach 50 USD. The external hourly audit reads the
ledger at `data/meta-spend.jsonl` (or `META_SPEND_PATH`) and sums cost_usd.
Each checkout writes its rows to its own tracked `data/meta-spend.jsonl`, which
its branch commits. The caps count the rows of the main checkout and of every
worktree together (see `ledger_paths`), so every worktree spends from one cap.
The spend windows and the key file are the main checkout's (see `shared_root`).
Set `META_SPEND_PATH`, `OMNIBASKET_ENV` or `META_SPEND_WINDOWS` to point elsewhere.

Commands: status, check, calibrate, selftest.
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
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

CAP_USD = 50.0
# Published Meta Model API list rates for muse-spark-1.3 (not the Contributor tier).
# Computed cost uses these until a response includes its own cost figure.
RATE_IN_PER_M = 1.25
RATE_OUT_PER_M = 4.25
MODEL = "muse-spark-1.3"
ROOT = Path(__file__).resolve().parents[1]


def shared_root(root: Path) -> Path:
    """The main checkout when ``root`` is a git worktree, else ``root`` itself.

    A worktree's ``.git`` is a file naming ``<main>/.git/worktrees/<name>``. The
    windows and the key file are one set for every worktree.
    """
    marker = root / ".git"
    try:
        if marker.is_file():
            text = marker.read_text().strip()
            if text.startswith("gitdir:"):
                gitdir = Path(text[len("gitdir:"):].strip())
                if not gitdir.is_absolute():
                    gitdir = (root / gitdir).resolve()
                if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                    return gitdir.parent.parent.parent
    except OSError:
        pass
    return root


def checkout_roots(shared: Path) -> list[Path]:
    """The main checkout and every worktree git lists for it.

    ``<main>/.git/worktrees/<name>/gitdir`` names the worktree's ``.git`` file.
    """
    roots = [shared]
    try:
        entries = sorted((shared / ".git" / "worktrees").iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            gitfile = Path((entry / "gitdir").read_text().strip())
        except OSError:
            continue
        if gitfile.parent not in roots:
            roots.append(gitfile.parent)
    return roots


SHARED = shared_root(ROOT)
# This checkout's own ledger: a worktree's rows are committed on its branch and
# reach main with the merge, never written into the main checkout's working copy.
LEDGER = ROOT / "data" / "meta-spend.jsonl"

# One row per provider this ledger can hold. A provider with no rate cannot be
# priced, so a call to it is refused instead of being recorded as free: the cap
# would otherwise be a lie. Baseten serves Muse Spark Open, Meta's open-weights
# model, at its Model APIs list rate of 1.25 / 4.25 USD per million tokens in / out
# (pricing page as captured 23 Oct 2026); BASETEN_RATE_IN_PER_M and
# BASETEN_RATE_OUT_PER_M override it. The hackathon key works only with this model
# id, and Baseten speaks Chat Completions only.
PROVIDERS = {
    "meta": {
        "model": MODEL,
        "base_env": "META_API_BASE",
        "default_base": "https://api.meta.ai/v1",
        "key_env": "META_API_KEY",
        "endpoint": "/responses",
        "rate_in": RATE_IN_PER_M,
        "rate_out": RATE_OUT_PER_M,
        "rate_in_env": None,
        "rate_out_env": None,
    },
    "baseten": {
        "model": "meta-models/muse-spark-open-1026",
        "base_env": "BASETEN_API_BASE",
        "default_base": "https://inference.baseten.co/v1",
        "key_env": "BASETEN_API_KEY",
        "endpoint": "/chat/completions",
        "rate_in": 1.25,
        "rate_out": 4.25,
        "rate_in_env": "BASETEN_RATE_IN_PER_M",
        "rate_out_env": "BASETEN_RATE_OUT_PER_M",
    },
}
# Calls that go to Muse Spark Open first, with Muse Spark 1.3 as the fallback
# (Adrian, 3 Nov): Ask Omnibasket's action mapping and the free-text query parse.
# Plain code checks both answers before anything is used. The lane is on while
# BASETEN_API_KEY is set; OMNIBASKET_OPEN_WEIGHT=0 turns it off.
OPEN_WEIGHT_PROVIDER = "baseten"
OPEN_WEIGHT_NOTES = frozenset({"ask-map", "input-free-text"})
# Meta's ask-map latency is p50 2.3 s and at most 10.8 s over 32 calls.
OPEN_WEIGHT_TIMEOUT_S = 12
MAIN_ENV = Path(os.environ.get("OMNIBASKET_ENV") or (SHARED / ".env"))
# Dated spend windows on top of the lifetime cap, e.g. Adrian's 10 USD limit on Meta
# for the 30 Oct overnight session. The main checkout's file, so every worktree
# obeys the same windows.
WINDOWS = SHARED / "config" / "spend-windows.json"
TZ = ZoneInfo("Europe/Bucharest")


class CapExceeded(RuntimeError):
    def __init__(self, spent, estimate):
        self.spent = spent
        self.estimate = estimate
        super().__init__(
            "refused: spend %.6f + estimate %.6f would reach the %.2f USD cap" % (spent, estimate, CAP_USD)
        )


class WindowCapExceeded(CapExceeded):
    def __init__(self, window, spent, estimate):
        self.window = window
        self.spent = spent
        self.estimate = estimate
        since = "today" if window.get("period") == "day" else "since %s" % window["from"]
        RuntimeError.__init__(
            self,
            "refused: %s spend %s is %.6f + estimate %.6f, over the %.2f USD window cap (%s)"
            % (window["provider"], since, spent, estimate, float(window["cap_usd"]), window.get("note", "")),
        )


def ledger_path():
    """Where this process writes its rows."""
    override = os.environ.get("META_SPEND_PATH")
    return Path(override) if override else LEDGER


def ledger_paths():
    """Every ledger the caps count: this one, the main checkout's and every worktree's."""
    if os.environ.get("META_SPEND_PATH"):
        return [ledger_path()]
    paths = [LEDGER]
    for root in checkout_roots(SHARED):
        path = root / "data" / "meta-spend.jsonl"
        if path not in paths:
            paths.append(path)
    return paths


def provider_config(provider="meta"):
    cfg = PROVIDERS.get(provider)
    if cfg is None:
        raise RuntimeError("unknown provider %r" % provider)
    return cfg


def provider_rates(provider="meta"):
    """(in, out) USD per million tokens, or (None, None) when unpriced."""
    cfg = provider_config(provider)
    rin, rout = cfg["rate_in"], cfg["rate_out"]
    if cfg["rate_in_env"] and os.environ.get(cfg["rate_in_env"]):
        rin = float(os.environ[cfg["rate_in_env"]])
    if cfg["rate_out_env"] and os.environ.get(cfg["rate_out_env"]):
        rout = float(os.environ[cfg["rate_out_env"]])
    return rin, rout


def compute_cost(tokens_in, tokens_out, provider="meta"):
    rin, rout = provider_rates(provider)
    if rin is None or rout is None:
        raise RuntimeError(
            "provider %r has no published rate in this repo; set its rate env vars before calling it" % provider
        )
    return (int(tokens_in) / 1_000_000.0) * rin + (int(tokens_out) / 1_000_000.0) * rout


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


def _all_rows(path=None):
    """Rows of one ledger, or of every ledger once each.

    A row merged into main is also in each worktree branched after the merge;
    an identical line is the same call, so it counts once.
    """
    if path is not None:
        yield from _iter_rows(path)
        return
    seen = set()
    for one in ledger_paths():
        for row in _iter_rows(one):
            line = json.dumps(row, sort_keys=True)
            if line in seen:
                continue
            seen.add(line)
            yield row


def spent_usd(path=None):
    total = 0.0
    for row in _all_rows(path):
        total += float(row["cost_usd"])
    return total


def tonight_usd(path=None):
    day = datetime.now(TZ).date().isoformat()
    total = 0.0
    for row in _all_rows(path):
        ts = str(row.get("ts", ""))
        if ts[:10] == day:
            total += float(row["cost_usd"])
    return total


def windows_path():
    override = os.environ.get("META_SPEND_WINDOWS")
    return Path(override) if override else WINDOWS


def active_windows(now=None):
    """Windows in force now. An unreadable file refuses everything: a cap that
    silently disappears is worse than a stopped call."""
    path = windows_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text())["windows"]
    except (OSError, ValueError, KeyError, TypeError):
        return [{"provider": "*", "from": "1970-01-01T00:00:00+00:00", "until": None, "cap_usd": 0.0,
                 "note": "unreadable %s" % path}]
    now = now or datetime.now(TZ)
    live = []
    for w in rows:
        start = datetime.fromisoformat(w["from"])
        end = datetime.fromisoformat(w["until"]) if w.get("until") else None
        if start <= now and (end is None or now < end):
            live.append(w)
    return live


def window_bounds(window, now=None):
    """(start, end) of the spend a window counts; end None means open.

    ``"period": "day"`` repeats the cap every Bucharest day from ``from`` on, so
    only today's rows count.
    """
    start = datetime.fromisoformat(window["from"])
    end = datetime.fromisoformat(window["until"]) if window.get("until") else None
    if window.get("period") == "day":
        today = (now or datetime.now(TZ)).astimezone(TZ).date()
        day_start = datetime.combine(today, dtime.min, tzinfo=TZ)
        day_end = datetime.combine(today + timedelta(days=1), dtime.min, tzinfo=TZ)
        start = max(start, day_start)
        end = day_end if end is None else min(end, day_end)
    return start, end


def window_gates(window, provider):
    """True when the window stops calls to ``provider``. ``"gates": "own"`` stops
    only calls to the window's own provider (Adrian, 3 Nov: the Baseten window);
    every other window stops every call."""
    return window.get("gates") != "own" or window["provider"] in ("*", provider)


def window_spent_usd(window, path=None, now=None):
    start, end = window_bounds(window, now)
    total = 0.0
    for row in _all_rows(path):
        if window["provider"] != "*" and row.get("provider", "meta") != window["provider"]:
            continue
        try:
            ts = datetime.fromisoformat(str(row.get("ts")))
        except ValueError:
            continue
        if ts >= start and (end is None or ts < end):
            total += float(row["cost_usd"])
    return total


def window_exceeded(estimate_usd, path=None, provider="meta"):
    """The first window this call would take past its cap, or None. A window
    applies to every call, whichever provider makes it, so a capped night stops
    all model spend rather than shifting it elsewhere. The exception is a
    ``"gates": "own"`` window, which stops only calls to its own provider."""
    for w in active_windows():
        if not window_gates(w, provider):
            continue
        if window_spent_usd(w, path) + float(estimate_usd) > float(w["cap_usd"]):
            return w
    return None


def would_exceed(estimate_usd, path=None, provider="meta"):
    """True if this call would take the ledger total to or past the cap.
    The audit sums every cost_usd line, so the cap is that same total, not a
    separate window. tonight_usd is reported by status only.
    """
    estimate_usd = float(estimate_usd)
    if estimate_usd < 0:
        raise ValueError("estimate must be >= 0")
    return spent_usd(path) + estimate_usd >= CAP_USD or window_exceeded(estimate_usd, path, provider) is not None


def assert_can_spend(estimate_usd, path=None, provider="meta"):
    w = window_exceeded(estimate_usd, path, provider)
    if w is not None:
        raise WindowCapExceeded(w, window_spent_usd(w, path), float(estimate_usd))
    if would_exceed(estimate_usd, path, provider):
        raise CapExceeded(spent_usd(path), float(estimate_usd))


def record(tokens_in, tokens_out, cost_usd, model=None, note=None, extra=None, provider="meta"):
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    model = model or provider_config(provider)["model"]
    row = {
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "provider": provider,
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
    for cfg in PROVIDERS.values():
        key = os.environ.get(cfg["key_env"])
        if key and key in text:
            text = text.replace(key, "[redacted]")
    return text


def status_lines():
    rows = list(_all_rows())
    spent = sum(float(r["cost_usd"]) for r in rows)
    night = tonight_usd()
    return [
        "ledger: %s" % ledger_path(),
        "ledgers_counted: %d" % len(ledger_paths()),
        "calls: %d" % len(rows),
        "spend_usd: %.6f" % spent,
        "tonight_usd: %.6f" % night,
        "cap_usd: %.2f" % CAP_USD,
        "remaining_usd: %.6f" % (CAP_USD - spent),
    ] + [
        "window_%s_%s: %.6f of %.2f" % (
            w["provider"], "today" if w.get("period") == "day" else "since_" + w["from"],
            window_spent_usd(w), float(w["cap_usd"]),
        )
        for w in active_windows()
    ] + [
        "rates_usd_per_mtok: in %.2f out %.2f" % (RATE_IN_PER_M, RATE_OUT_PER_M),
        "baseten_priced: %s" % ("yes" if provider_rates("baseten")[0] is not None else "no (set BASETEN_RATE_IN_PER_M / BASETEN_RATE_OUT_PER_M)"),
        "baseten_key: %s" % ("set" if os.environ.get("BASETEN_API_KEY") else "absent"),
        "open_weight_notes: %s" % ", ".join(sorted(OPEN_WEIGHT_NOTES)),
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


def _post(path, body, provider="meta", timeout=120):
    cfg = provider_config(provider)
    base = os.environ.get(cfg["base_env"], cfg["default_base"]).rstrip("/")
    if not os.environ.get(cfg["key_env"]):
        # The app process does not inherit the CLI's environment; load the
        # configured values once, here, so every caller behaves the same.
        load_dotenv()
    key = os.environ.get(cfg["key_env"])
    if not key:
        raise RuntimeError("%s is not set" % cfg["key_env"])
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
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


def _reply_text(payload):
    """The model's text from a Responses or a Chat Completions body."""
    if not isinstance(payload, dict):
        return ""
    if payload.get("output_text"):
        return str(payload["output_text"])
    parts = [
        piece["text"]
        for block in payload.get("output") or []
        for piece in block.get("content") or []
        if piece.get("text")
    ]
    if parts:
        return "".join(parts)
    choices = payload.get("choices") or []
    if choices:
        return str((choices[0].get("message") or {}).get("content") or "")
    return ""


def _chat_body(body, model):
    """Our Responses-style body as Chat Completions, for a provider that speaks only that."""
    messages = []
    for item in body.get("input") or []:
        parts = []
        for piece in item.get("content") or []:
            if piece.get("type") == "input_text":
                parts.append({"type": "text", "text": piece.get("text", "")})
            elif piece.get("type") == "input_image":
                parts.append({"type": "image_url", "image_url": {"url": piece.get("image_url", "")}})
        if all(p["type"] == "text" for p in parts):
            content = "\n\n".join(p["text"] for p in parts)
        else:
            content = parts
        messages.append({"role": item.get("role", "user"), "content": content})
    out = {"model": model, "messages": messages}
    if body.get("max_output_tokens"):
        out["max_tokens"] = int(body["max_output_tokens"])
    effort = (body.get("reasoning") or {}).get("effort")
    if effort:
        out["reasoning_effort"] = effort
    return out


def open_weight_lane(note):
    """True when a call with this note goes to Muse Spark Open first."""
    if note not in OPEN_WEIGHT_NOTES:
        return False
    key_env = provider_config(OPEN_WEIGHT_PROVIDER)["key_env"]
    if not os.environ.get(key_env):
        # Load .env before reading the switch, so a switch set there holds from the first call.
        load_dotenv()
    if os.environ.get("OMNIBASKET_OPEN_WEIGHT", "").strip().lower() in ("0", "false", "off", "no"):
        return False
    return bool(os.environ.get(key_env))


def guarded_post(body, estimate_usd, note, provider="meta", timeout=120, accept=None):
    """Check the cap, send one model call, record tokens and computed cost.

    A default-provider call whose note is in the open-weight lane goes to Baseten
    first. If that fails, comes back empty, or its text fails ``accept`` (the
    caller's own parse check), the same call goes to Meta and its row names the
    fallback. So does a call stopped by a Baseten-only window. Any other cap
    refusal is never retried: those caps cover every provider.
    """
    if provider == "meta" and open_weight_lane(note):
        try:
            payload, row = _guarded_once(
                body, estimate_usd, note, OPEN_WEIGHT_PROVIDER, min(timeout, OPEN_WEIGHT_TIMEOUT_S)
            )
            text = _reply_text(payload).strip()
            if text and (accept is None or accept(text)):
                return payload, row
            reason = "unusable reply" if text else "empty reply"
        except WindowCapExceeded as e:
            if window_gates(e.window, "meta"):
                raise
            reason = "%s window full" % e.window["provider"]
        except CapExceeded:
            raise
        except Exception as e:
            reason = _redact(type(e).__name__ + (": " + str(e)[:80] if isinstance(e, RuntimeError) else ""))
        return _guarded_once(
            body, estimate_usd, note, "meta", timeout,
            fallback={"fallback_from": OPEN_WEIGHT_PROVIDER, "fallback_reason": reason},
        )
    return _guarded_once(body, estimate_usd, note, provider, timeout)


def _guarded_once(body, estimate_usd, note, provider, timeout, fallback=None):
    assert_can_spend(estimate_usd, provider=provider)
    cfg = provider_config(provider)
    t0 = time.time()
    endpoint = cfg["endpoint"]
    if endpoint == "/chat/completions":
        try:
            payload = _post(endpoint, _chat_body(body, cfg["model"]), provider=provider, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError("model HTTP %s" % e.code) from None
    else:
        try:
            payload = _post("/responses", body, provider=provider, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                # Do not include the body: it can echo request headers in some proxies.
                raise RuntimeError("model HTTP %s" % e.code) from None
            endpoint = "/chat/completions"
            payload = _post("/chat/completions", body, provider=provider, timeout=timeout)
    tin, tout = _usage_tokens(payload.get("usage"))
    computed = compute_cost(tin, tout, provider=provider)
    billed = _response_cost(payload)
    # A call that already happened is recorded even if the actual cost crosses
    # the cap; the next call is refused. The pre-check uses the estimate.
    row = record(
        tin,
        tout,
        computed,
        note=note,
        provider=provider,
        extra={
            "endpoint": endpoint,
            "latency_ms": int((time.time() - t0) * 1000),
            "provider_cost_usd": None if billed is None else round(billed, 8),
            "cost_source": "computed_list_rate" if billed is None else "provider",
            **(fallback or {}),
        },
    )
    return payload, row


def cmd_calibrate(a):
    load_dotenv()
    provider = getattr(a, "provider", "meta")
    # Worst case for this prompt: ~50 input tokens and 32 output tokens.
    estimate = compute_cost(50, 32, provider=provider)
    body = {
        "model": os.environ.get("META_MODEL", provider_config(provider)["model"]) if provider == "meta" else provider_config(provider)["model"],
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply with the single word pong."}]}],
        "max_output_tokens": 16,
    }
    try:
        payload, row = guarded_post(body, estimate, note="calibrate", provider=provider)
    except CapExceeded as e:
        print(_redact(str(e)))
        return 2
    text = _reply_text(payload)
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


def cmd_selftest(_a):
    """Prove the cap and that status does not echo a key. Uses a temp ledger only."""
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="meta-budget-")) / "spend.jsonl"
    os.environ["META_SPEND_PATH"] = str(tmp)
    os.environ["META_API_KEY"] = "test-key-should-not-appear-9f3c"
    os.environ["META_SPEND_WINDOWS"] = str(tmp.parent / "no-windows.json")
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
    cal = sub.add_parser("calibrate")
    cal.add_argument("--provider", default="meta", choices=sorted(PROVIDERS))
    cal.set_defaults(fn=cmd_calibrate)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:
        print(_redact(type(e).__name__ + ": " + str(e)[:300]))
        return 1


if __name__ == "__main__":
    sys.exit(main())

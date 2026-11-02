"""The windows and key file are one set for every worktree; each checkout writes its own
ledger, and the caps count every checkout's rows together."""

import json
import subprocess
from pathlib import Path

from tools import meta_budget


def test_main_checkout_is_its_own_shared_root(tmp_path):
    (tmp_path / ".git").mkdir()
    assert meta_budget.shared_root(tmp_path) == tmp_path


def test_worktree_resolves_to_the_main_checkout(tmp_path):
    main = tmp_path / "main"
    wt = tmp_path / "wt" / "feat-x"
    (main / ".git" / "worktrees" / "feat-x").mkdir(parents=True)
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: %s\n" % (main / ".git" / "worktrees" / "feat-x"))
    assert meta_budget.shared_root(wt) == main


def test_a_real_git_worktree_finds_the_main_checkout(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    run = lambda *a, cwd=main: subprocess.run(a, cwd=cwd, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path / "wt"
    run("git", "worktree", "add", "-q", "-b", "w", str(wt))
    assert meta_budget.shared_root(wt).resolve() == main.resolve()


def test_a_tree_with_no_git_uses_itself(tmp_path):
    assert meta_budget.shared_root(tmp_path) == tmp_path


def test_the_ledger_is_this_checkouts_and_the_windows_the_main_ones():
    assert meta_budget.LEDGER == meta_budget.ROOT / "data" / "meta-spend.jsonl"
    assert meta_budget.WINDOWS == meta_budget.SHARED / "config" / "spend-windows.json"


def _row(ts, cost):
    return json.dumps({"ts": ts, "provider": "meta", "model": "m", "tokens_in": 1, "tokens_out": 1, "cost_usd": cost})


def test_caps_count_every_checkouts_rows_once(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    run = lambda *a, cwd=main: subprocess.run(a, cwd=cwd, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path / "wt"
    run("git", "worktree", "add", "-q", "-b", "w", str(wt))
    merged = _row("2026-11-02T10:00:00+02:00", 1.0)
    for root, rows in ((main, [merged]), (wt, [merged, _row("2026-11-03T10:00:00+02:00", 2.5)])):
        (root / "data").mkdir()
        (root / "data" / "meta-spend.jsonl").write_text("\n".join(rows) + "\n")
    monkeypatch.delenv("META_SPEND_PATH", raising=False)
    monkeypatch.setattr(meta_budget, "ROOT", wt)
    monkeypatch.setattr(meta_budget, "SHARED", meta_budget.shared_root(wt))
    monkeypatch.setattr(meta_budget, "LEDGER", wt / "data" / "meta-spend.jsonl")
    assert meta_budget.ledger_path() == wt / "data" / "meta-spend.jsonl"
    assert meta_budget.spent_usd() == 3.5


def test_a_worktree_writes_only_its_own_ledger(tmp_path, monkeypatch):
    main, wt = tmp_path / "main", tmp_path / "wt"
    monkeypatch.delenv("META_SPEND_PATH", raising=False)
    monkeypatch.setattr(meta_budget, "SHARED", main)
    monkeypatch.setattr(meta_budget, "LEDGER", wt / "data" / "meta-spend.jsonl")
    meta_budget.record(1, 1, 0.01, note="t")
    assert (wt / "data" / "meta-spend.jsonl").exists()
    assert not (main / "data" / "meta-spend.jsonl").exists()

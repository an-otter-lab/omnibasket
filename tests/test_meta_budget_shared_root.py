"""The spend ledger, windows and key file are one set for the main checkout and every worktree."""

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


def test_a_real_git_worktree_shares_the_main_ledger(tmp_path):
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


def test_paths_hang_off_the_shared_root():
    assert meta_budget.LEDGER == meta_budget.SHARED / "data" / "meta-spend.jsonl"
    assert meta_budget.WINDOWS == meta_budget.SHARED / "config" / "spend-windows.json"

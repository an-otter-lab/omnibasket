import json
import os
from datetime import datetime, timedelta

import pytest

from tools import meta_budget as mb


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "spend.jsonl"
    monkeypatch.setenv("META_SPEND_PATH", str(path))
    return path


def windows(tmp_path, monkeypatch, rows):
    path = tmp_path / "windows.json"
    path.write_text(json.dumps({"windows": rows}))
    monkeypatch.setenv("META_SPEND_WINDOWS", str(path))
    return path


def since(hours):
    return (datetime.now(mb.TZ) - timedelta(hours=hours)).isoformat()


def test_meta_window_refuses_past_ten_dollars(ledger, tmp_path, monkeypatch):
    windows(tmp_path, monkeypatch, [{"provider": "meta", "from": since(2), "until": None, "cap_usd": 10.0}])
    mb.record(10, 10, 9.99, note="fill")
    assert not mb.would_exceed(0.005)
    assert mb.would_exceed(0.02)
    with pytest.raises(mb.WindowCapExceeded):
        mb.assert_can_spend(0.02)


def test_spend_before_the_window_does_not_count(ledger, tmp_path, monkeypatch):
    old = {"ts": since(30), "provider": "meta", "cost_usd": 9.0}
    ledger.write_text(json.dumps(old) + "\n")
    windows(tmp_path, monkeypatch, [{"provider": "meta", "from": since(2), "until": None, "cap_usd": 10.0}])
    assert not mb.would_exceed(5.0)


def test_window_blocks_other_providers_once_meta_is_spent(ledger, tmp_path, monkeypatch):
    windows(tmp_path, monkeypatch, [{"provider": "meta", "from": since(2), "until": None, "cap_usd": 10.0}])
    mb.record(10, 10, 10.0, note="fill")
    with pytest.raises(mb.WindowCapExceeded):
        mb.assert_can_spend(0.0001)


def test_unreadable_windows_file_refuses(ledger, tmp_path, monkeypatch):
    path = tmp_path / "windows.json"
    path.write_text("{not json")
    monkeypatch.setenv("META_SPEND_WINDOWS", str(path))
    assert mb.would_exceed(0.0001)


def test_expired_window_no_longer_applies(ledger, tmp_path, monkeypatch):
    windows(tmp_path, monkeypatch, [{"provider": "meta", "from": since(5), "until": since(1), "cap_usd": 1.0}])
    mb.record(10, 10, 2.0, note="after window")
    assert not mb.would_exceed(0.01)


def test_committed_config_holds_the_overnight_cap():
    rows = json.loads(open(os.path.join(os.path.dirname(__file__), "..", "config", "spend-windows.json")).read())["windows"]
    night = [w for w in rows if w["provider"] == "meta" and w["from"].startswith("2026-10-30")]
    assert night and night[0]["cap_usd"] == 10.0

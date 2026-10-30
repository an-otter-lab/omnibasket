"""SQLite page cache keyed by store, ISBN, item and day.

ISBN-less editions (the locked basket has two) would collide on store+ISBN+day,
so the item id is part of the key. A hit is the saved capture. A miss is not
filled from the network by this module.

Each call opens its own connection and closes it before returning. A connection
is never stored on the cache and never shared across threads. WAL plus a busy
timeout let a solve run while another request is reading. Callers must finish
every read before they start yielding a stream.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "ro-v1-seed.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    store_id TEXT NOT NULL,
    isbn13 TEXT NOT NULL,
    item_id TEXT NOT NULL,
    day TEXT NOT NULL,
    page_text TEXT NOT NULL,
    screenshot_path TEXT,
    model_json TEXT,
    provenance_json TEXT NOT NULL,
    PRIMARY KEY (store_id, isbn13, item_id, day)
);
"""

CONFIRMATION_TTL = 24 * 3600  # a shop confirmation (ISBN, price, title match) is reused for 24 h

_CONFIRMATIONS = """
CREATE TABLE IF NOT EXISTS confirmations (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    stored_at REAL NOT NULL
);
"""

_BUSY_TIMEOUT_MS = 5000


class PageCache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)
            db.executescript(_CONFIRMATIONS)

    def close(self) -> None:
        """Nothing is held open. Kept so older callers can still call close()."""

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT_MS / 1000)
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def put(self, row: dict) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO pages (
                    store_id, isbn13, item_id, day, page_text,
                    screenshot_path, model_json, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["store_id"],
                    row.get("isbn13") or "",
                    row["item_id"],
                    row["day"],
                    row["page_text"],
                    row.get("screenshot_path"),
                    _dump(row.get("model_json")),
                    _dump(row.get("provenance") or {}),
                ),
            )

    def get(self, store_id: str, isbn13: str | None, item_id: str, day: str) -> dict | None:
        with self._connect() as db:
            found = db.execute(
                """
                SELECT * FROM pages
                WHERE store_id = ? AND isbn13 = ? AND item_id = ? AND day = ?
                """,
                (store_id, isbn13 or "", item_id, day),
            ).fetchone()
            if found is None:
                return None
            return _row(found)

    def get_confirmation(self, key: str, now: float | None = None) -> dict | None:
        """A stored shop confirmation, or None when absent or older than CONFIRMATION_TTL."""
        import time
        with self._connect() as db:
            found = db.execute("SELECT payload, stored_at FROM confirmations WHERE key = ?", (key,)).fetchone()
        if found is None or (now or time.time()) - found["stored_at"] > CONFIRMATION_TTL:
            return None
        return json.loads(found["payload"])

    def put_confirmation(self, key: str, payload: dict, now: float | None = None) -> None:
        import time
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO confirmations (key, payload, stored_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False), now or time.time()),
            )

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM pages").fetchone()[0])


def load_seed(cache: PageCache, seed_path: Path | None = None) -> int:
    payload = json.loads((seed_path or SEED_PATH).read_text())
    for row in payload["pages"]:
        cache.put(row)
    return len(payload["pages"])


def open_seeded(path: Path | str, seed_path: Path | None = None) -> PageCache:
    cache = PageCache(path)
    if cache.count() == 0:
        load_seed(cache, seed_path)
    return cache


def _dump(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row(found: sqlite3.Row) -> dict:
    model = found["model_json"]
    provenance = found["provenance_json"]
    return {
        "store_id": found["store_id"],
        "isbn13": found["isbn13"],
        "item_id": found["item_id"],
        "day": found["day"],
        "page_text": found["page_text"],
        "screenshot_path": found["screenshot_path"],
        "model_json": json.loads(model) if model else None,
        "provenance": json.loads(provenance) if provenance else {},
    }

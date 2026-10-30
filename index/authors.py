"""Lazy author enrichment for the book index from Open Library (plain HTTP, no model).

The index has almost no real author names. When a query matches no row's author_hint,
look the query up as an author on Open Library (author search, then that author's works),
match the work titles to index rows, and write the author name into books.author_hint
only where it is empty or a URL slug. Results, hits and misses, are cached in SQLite.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request

try:
    from index.search import normalize, UA
except ImportError:  # pragma: no cover
    from search import normalize, UA

TIMEOUT = 3
MAX_CALLS = 3
HIT_TTL = 30 * 86400
MISS_TTL = 86400
ERROR_TTL = 600
MAX_TITLES = 100
MAX_ROWS_PER_TITLE = 200


def cache_init(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS author_cache (
        query_key TEXT PRIMARY KEY, author_ol_id TEXT, name TEXT,
        titles_json TEXT, fetched INTEGER NOT NULL, status TEXT NOT NULL)""")


def _tnorm(value: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalize(value)).split())


def is_slug(hint: str | None) -> bool:
    """True for an empty hint or a URL slug (lowercase words joined by - or _)."""
    if not hint or not hint.strip():
        return True
    h = hint.strip()
    return bool(re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", h)) and h == h.lower()


def hint_matches(hint: str | None, tokens: list[str]) -> bool:
    if is_slug(hint):
        return False
    hn = set(_tnorm(hint).split())
    return bool(tokens) and all(t in hn for t in tokens)


def _get(opener, url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with opener(req, timeout=TIMEOUT) as response:
        status = getattr(response, "status", 200)
        if isinstance(status, int) and status >= 400:
            raise OSError(f"HTTP {status}")
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unexpected payload")
    return payload


def _pick_author(docs: list, tokens: list[str]) -> tuple[str, str] | None:
    """First (Open Library order) author whose name holds every query token."""
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        name, key = doc.get("name"), doc.get("key")
        if not isinstance(name, str) or not isinstance(key, str):
            continue
        parts = set(_tnorm(name).split())
        if tokens and all(t in parts for t in tokens):
            return key.rsplit("/", 1)[-1], name
    return None


def fetch_author(query: str, tokens: list[str], opener) -> tuple[str, dict]:
    """Return (status, record). status: hit | miss | error. At most 2 calls."""
    try:
        found = _get(opener, "https://openlibrary.org/search/authors.json?" + urllib.parse.urlencode({"q": query, "limit": 10}))
        picked = _pick_author(found.get("docs") or [], tokens)
        if not picked:
            return "miss", {}
        ol_id, name = picked
        works = _get(opener, f"https://openlibrary.org/authors/{urllib.parse.quote(ol_id)}/works.json?limit={MAX_TITLES}")
    except Exception:
        return "error", {}
    titles = []
    for entry in works.get("entries") or []:
        if isinstance(entry, dict) and isinstance(entry.get("title"), str) and entry["title"].strip():
            titles.append(entry["title"].strip())
    titles = list(dict.fromkeys(titles))
    return ("hit" if titles else "miss"), {"author_ol_id": ol_id, "name": name, "titles": titles}


def apply_titles(db: sqlite3.Connection, name: str, titles: list[str]) -> int:
    """Write name into author_hint of rows whose title equals or starts with an OL title."""
    changed = 0
    for title in titles:
        tn = _tnorm(title)
        toks = tn.split()
        if not toks:
            continue
        phrase = '"' + " ".join(toks).replace('"', "") + '"'
        try:
            rows = db.execute(
                """SELECT b.rowid, b.title, b.author_hint FROM books_search s
                   JOIN books b ON b.rowid = s.rowid WHERE books_search MATCH ? LIMIT ?""",
                ("title:" + phrase, MAX_ROWS_PER_TITLE)).fetchall()
        except sqlite3.OperationalError:
            continue
        for rowid, row_title, hint in rows:
            rn = _tnorm(row_title)
            if rn == tn or (len(toks) >= 2 and rn.startswith(tn + " ")):
                if is_slug(hint):
                    db.execute("UPDATE books SET author_hint=? WHERE rowid=?", (name, rowid))
                    changed += 1
    return changed


def enrich(db: sqlite3.Connection, query: str, tokens: list[str], opener, now: float | None = None) -> int:
    """Lazy author lookup for one query. Returns rows updated. Never raises on network trouble."""
    now = int(now if now is not None else time.time())
    cache_init(db)
    key = " ".join(tokens)
    row = db.execute("SELECT name, titles_json, fetched, status FROM author_cache WHERE query_key=?", (key,)).fetchone()
    if row:
        name, titles_json, fetched, status = row
        ttl = {"hit": HIT_TTL, "miss": MISS_TTL}.get(status, ERROR_TTL)
        if now - fetched < ttl:
            if status == "hit":
                return apply_titles(db, name, json.loads(titles_json or "[]"))
            return 0
    status, rec = fetch_author(query, tokens, opener)
    db.execute(
        "INSERT OR REPLACE INTO author_cache(query_key,author_ol_id,name,titles_json,fetched,status) VALUES(?,?,?,?,?,?)",
        (key, rec.get("author_ol_id"), rec.get("name"), json.dumps(rec.get("titles", [])), now, status))
    if status == "hit":
        return apply_titles(db, rec["name"], rec["titles"])
    return 0

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
MAX_AMBIGUOUS_ROWS = 8  # a work matching more rows than this is a generic/mislinked title: skipped
MAX_SUFFIX_TOKENS = 4  # prefix match: what follows the work title must be short...
EDITION_WORDS = frozenset(
    "a an and audio board book books box boxed cd colour color colouring coloring colour edn edition ed"
    " hardcover hardback paperback pbk hb illustrated level of other pachet pop padded oversized read ready"
    " set the to up vol with s".split())  # ...and edition-like (or hold the author's surname)


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
    """Best person candidate: holds every query token, its last token (surname) is a query
    token, and it has the fewest extra tokens ('Eric Carle' beats 'World of Eric Carle').
    Ties keep Open Library order. No qualifying candidate: None."""
    best, best_extra = None, None
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        name, key = doc.get("name"), doc.get("key")
        if not isinstance(name, str) or not isinstance(key, str):
            continue
        toks = _tnorm(name).split()
        if not tokens or not toks or not all(t in toks for t in tokens) or toks[-1] not in tokens:
            continue
        extra = len(toks) - len(set(tokens))
        if best_extra is None or extra < best_extra:
            best, best_extra = (key.rsplit("/", 1)[-1], name), extra
    return best


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
            credited = [a.get("author", {}).get("key", "") for a in entry.get("authors") or [] if isinstance(a, dict)]
            if credited and (len(credited) > 1 or credited[0].rsplit("/", 1)[-1] != ol_id):
                continue  # co-credited or anthology work: only sole-author works are trusted
            titles.append(entry["title"].strip())
    titles = list(dict.fromkeys(titles))
    return ("hit" if titles else "miss"), {"author_ol_id": ol_id, "name": name, "titles": titles}


def apply_titles(db: sqlite3.Connection, name: str, titles: list[str], query_key: str = "") -> int:
    """Write name into author_hint of rows that match an Open Library work of that author.

    Rules: a work titled like the query or the author name is dropped (it would prefix-match
    every study of the author); a row equal to the query is never labelled; a multi-word work
    matches a row equal to or starting with it; a single-word work matches a row equal to it
    or starting with it only when the row also holds the author's surname token."""
    changed = 0
    name_n = _tnorm(name)
    qn = _tnorm(query_key)
    name_toks = name_n.split()
    surname = name_toks[-1] if name_toks else ""
    for title in titles:
        tn = _tnorm(title)
        toks = tn.split()
        if not toks or tn == qn or tn == name_n:
            continue
        single = len(toks) == 1
        if single and not surname:
            continue
        phrase = '"' + " ".join(toks).replace('"', "") + '"'
        matches = ["title:" + phrase]
        if single:  # equal-title rows (few, exact) plus rows that also hold the surname
            matches = ['title:' + phrase + ' AND title:"%s"' % surname, 'title:' + phrase + ' NOT title:"%s"' % surname]
        rows = []
        for match in matches:
            try:
                rows += db.execute(
                    """SELECT b.rowid, b.title, b.author_hint FROM books_search s
                       JOIN books b ON b.rowid = s.rowid WHERE books_search MATCH ? LIMIT ?""",
                    (match, MAX_ROWS_PER_TITLE)).fetchall()
            except sqlite3.OperationalError:
                continue
        hits = []
        for rowid, row_title, hint in rows:
            rn = _tnorm(row_title)
            if rn == qn or rn == name_n:
                continue
            if rn == tn:
                ok = True
            elif rn.startswith(tn + " "):
                suffix = rn[len(tn) + 1:].split()
                holds_surname = surname in rn.split()
                ok = holds_surname or (not single and len(suffix) <= MAX_SUFFIX_TOKENS
                                       and all(w in EDITION_WORDS for w in suffix))
            else:
                ok = False
            if ok:
                hits.append((rowid, hint))
        if len(hits) > MAX_AMBIGUOUS_ROWS:
            continue
        for rowid, hint in hits:
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
                return apply_titles(db, name, json.loads(titles_json or "[]"), key)
            return 0
    status, rec = fetch_author(query, tokens, opener)
    db.execute(
        "INSERT OR REPLACE INTO author_cache(query_key,author_ol_id,name,titles_json,fetched,status) VALUES(?,?,?,?,?,?)",
        (key, rec.get("author_ol_id"), rec.get("name"), json.dumps(rec.get("titles", [])), now, status))
    if status == "hit":
        return apply_titles(db, rec["name"], rec["titles"], key)
    return 0

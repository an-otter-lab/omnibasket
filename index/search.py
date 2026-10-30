"""Plain-code search over the local book index with FTS5 and cached Open Library enrichment.

FTS retrieval is OR (any query token may match). Ranking, not the MATCH clause, decides order.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)
# MATCH failures are recorded here so an empty result is not silent.
MATCH_ERRORS: list[dict] = []

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "index" / "books.sqlite3"
UA = "Omnibasket/1.0 (+https://omnibasket.anottersolution.com/contact)"
TIMEOUT = 5
SKIP_TTL = 600  # seconds an ISBN lookup cut off by the budget is not retried (throttle, not a cached result)

# Common stop words for Romanian and English
STOP_WORDS = {
    "si", "și", "de", "din", "la", "cu", "pe", "in", "un", "o", "le", "lui",
    "a", "ale", "ea", "ei", "eu", "tu", "el", "noi", "voi", "ele",
    "the", "a", "an", "and", "or", "of", "for", "in", "on", "at", "to",
}


def normalize(value: str | None) -> str:
    """Normalize text: casefold, remove diacritics, strip combining characters."""
    if not value:
        return ""
    value = value.translate(str.maketrans({"ș": "s", "ş": "s", "ț": "t", "ţ": "t"}))
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def validate_isbn(isbn: str) -> bool:
    """Validate ISBN-10 or ISBN-13 check digit."""
    if not isbn:
        return False
    isbn_clean = isbn.replace("-", "").replace(" ", "").upper()
    if len(isbn_clean) == 10:
        total = 0
        for i, ch in enumerate(isbn_clean[:-1]):
            if not ch.isdigit():
                return False
            total += (10 - i) * int(ch)
        last = isbn_clean[-1]
        if last == "X":
            total += 10
        elif last.isdigit():
            total += int(last)
        else:
            return False
        return total % 11 == 0
    elif len(isbn_clean) == 13:
        if not isbn_clean.isdigit():
            return False
        total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(isbn_clean))
        return total % 10 == 0
    return False


def _filter_stop_words(tokens: list[str]) -> list[str]:
    """Remove stop words from token list, but keep at least one token."""
    filtered = [t for t in tokens if t not in STOP_WORDS]
    return filtered if filtered else tokens


def _cache_init(db: sqlite3.Connection) -> None:
    """Initialize Open Library cache table."""
    db.execute("""CREATE TABLE IF NOT EXISTS openlibrary_cache (
        cache_key TEXT PRIMARY KEY, isbn TEXT, checked INTEGER NOT NULL DEFAULT 1)""")


_FTS_TRIGGERS = (
    "books_fts_ai",
    "books_fts_ad",
    "books_fts_au",
)


def ensure_books_search(db: sqlite3.Connection) -> None:
    """Create books_search when missing and keep it synced from books writes.

    Shared by search and by index.pull.init. Triggers, not a later rebuild, are
    what make a pull visible to the next search.
    """
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='books_search'"
    ).fetchone()
    if not exists:
        db.execute("""CREATE VIRTUAL TABLE books_search USING fts5(
            title, author, isbn, tokenize="unicode61 remove_diacritics 2")""")
        db.execute("""INSERT INTO books_search(rowid, title, author, isbn)
            SELECT rowid, COALESCE(title, ''), COALESCE(author_hint, ''), COALESCE(isbn, '')
            FROM books""")
    else:
        # Rows written while the triggers were absent stay invisible for ever:
        # an UPDATE only rewrites an FTS row that already exists. Compare counts
        # and rebuild when they drift, so a stale index heals on the next call.
        books_n = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        fts_n = db.execute("SELECT COUNT(*) FROM books_search").fetchone()[0]
        if books_n != fts_n:
            db.execute("DROP TABLE IF EXISTS books_search")
            db.execute("""CREATE VIRTUAL TABLE books_search USING fts5(
                title, author, isbn, tokenize="unicode61 remove_diacritics 2")""")
            db.execute("""INSERT INTO books_search(rowid, title, author, isbn)
                SELECT rowid, COALESCE(title, ''), COALESCE(author_hint, ''), COALESCE(isbn, '')
                FROM books""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn)")
    current = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name IN ('books_fts_ai','books_fts_ad','books_fts_au')"
    ).fetchall()
    body = " ".join(row[0] or "" for row in current)
    if len(current) == 3 and "UPDATE books_search" in body and "DELETE FROM books_search" in body:
        return
    for name in _FTS_TRIGGERS:
        db.execute(f"DROP TRIGGER IF EXISTS {name}")
    db.executescript("""
        CREATE TRIGGER books_fts_ai AFTER INSERT ON books BEGIN
          INSERT INTO books_search(rowid, title, author, isbn)
          VALUES (new.rowid, COALESCE(new.title, ''), COALESCE(new.author_hint, ''), COALESCE(new.isbn, ''));
        END;
        CREATE TRIGGER books_fts_ad AFTER DELETE ON books BEGIN
          DELETE FROM books_search WHERE rowid = old.rowid;
        END;
        CREATE TRIGGER books_fts_au AFTER UPDATE ON books BEGIN
          UPDATE books_search
          SET title = COALESCE(new.title, ''),
              author = COALESCE(new.author_hint, ''),
              isbn = COALESCE(new.isbn, '')
          WHERE rowid = new.rowid;
        END;
    """)


def _ensure_fts_table(db: sqlite3.Connection) -> None:
    """Backward-compatible name for ensure_books_search."""
    ensure_books_search(db)


def refresh_fts(db_path: Path | str = DB) -> None:
    """Drop and rebuild books_search from books. Used by --rebuild-fts."""
    if not Path(db_path).is_file():
        return
    with sqlite3.connect(str(db_path)) as db:
        db.execute("DROP TABLE IF EXISTS books_search")
        ensure_books_search(db)
        db.commit()


def _record_match_error(query: str, exc: sqlite3.OperationalError) -> None:
    """Remember a MATCH failure. Callers still get a list; the endpoint stays up."""
    MATCH_ERRORS.append({"query": query, "error": str(exc)})
    log.warning("books_search MATCH failed for %r: %s", query, exc)


def _rank_key(title: str | None, author: str | None, isbn: str | None, query: str, tokens: list[str]):
    """Order hits: exact title, prefix, phrase, token coverage, extra tokens, position."""
    title_n = normalize(title)
    query_n = normalize(query)
    combined = f"{title_n} {normalize(author)} {normalize(isbn)}"
    matched = sum(1 for token in tokens if token in combined)
    query_tokens = set(query_n.split())
    extra = sum(1 for token in title_n.split() if token not in query_tokens)
    first = float("inf")
    for token in tokens:
        pos = title_n.find(token)
        if pos != -1:
            first = min(first, pos)
    return (
        0 if query_n and title_n == query_n else 1,
        0 if query_n and title_n.startswith(query_n) else 1,
        0 if query_n and query_n in title_n else 1,
        -matched,
        extra,
        len(title_n),
        first,
        title_n,
    )


def _budget() -> float:
    try:
        from index import authors as _a
        return _a.BUDGET
    except Exception:  # pragma: no cover
        return 4.0


def _fetch_isbn(title: str, author: str | None, opener, timeout: float) -> str | None:
    """Network part of an ISBN lookup. Raises on any failure."""
    params = {"title": title}
    if author:
        params["author"] = author
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with opener(req, timeout=timeout) as response:
        payload = json.loads(response.read(1_000_000).decode("utf-8"))
    docs = payload.get("docs", [])
    if docs and isinstance(docs[0].get("isbn"), list):
        for candidate in docs[0]["isbn"]:
            if re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", candidate) and validate_isbn(candidate):
                return candidate
    return None


def _prefetch_isbns(db: sqlite3.Connection, items: list, opener, deadline: float) -> None:
    """Look up the uncached ISBNs in parallel inside the shared deadline. Lookups that finish in
    time are cached (hit, or a genuine miss/failure as before); lookups cut off by the deadline
    are left uncached so a later call retries them."""
    db.execute("CREATE TABLE IF NOT EXISTS openlibrary_skip (cache_key TEXT PRIMARY KEY, until INTEGER NOT NULL)")
    now = int(time.time())
    todo = {}
    for item in items:
        key = normalize(item["title"]) + "|" + normalize(item["author"] or "")
        if key in todo or db.execute("SELECT 1 FROM openlibrary_cache WHERE cache_key=?", (key,)).fetchone() is not None:
            continue
        if db.execute("SELECT 1 FROM openlibrary_skip WHERE cache_key=? AND until>?", (key, now)).fetchone() is None:
            todo[key] = item
    left = deadline - time.monotonic()
    if not todo or left <= 0:
        return
    timeout = TIMEOUT if left >= TIMEOUT else left
    from concurrent.futures import ThreadPoolExecutor, wait
    pool = ThreadPoolExecutor(max_workers=min(len(todo), 8))
    futures = {pool.submit(_fetch_isbn, it["title"], it["author"], opener, timeout): k for k, it in todo.items()}
    done, _ = wait(futures, timeout=left)
    pool.shutdown(wait=False, cancel_futures=True)
    for fut in done:
        try:
            isbn = fut.result()
        except Exception:
            isbn = None
        db.execute("INSERT OR IGNORE INTO openlibrary_cache(cache_key,isbn) VALUES(?,?)", (futures[fut], isbn))
    for fut, key in futures.items():  # cut off by the budget: not cached as a result, only throttled for a while
        if fut not in done:
            db.execute("INSERT OR REPLACE INTO openlibrary_skip(cache_key,until) VALUES(?,?)", (key, now + SKIP_TTL))


def _lookup_isbn(db: sqlite3.Connection, title: str, author: str | None, opener, cache_only: bool = False) -> str | None:
    """Look up ISBN from Open Library, validate check digit, and cache result."""
    key = normalize(title) + "|" + normalize(author or "")
    found = db.execute("SELECT isbn FROM openlibrary_cache WHERE cache_key=?", (key,)).fetchone()
    if found is not None:
        return found[0]
    if cache_only:
        return None
    params = {"title": title}
    if author:
        params["author"] = author
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
    isbn = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with opener(req, timeout=TIMEOUT) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
        docs = payload.get("docs", [])
        if docs and isinstance(docs[0].get("isbn"), list):
            # Find first valid ISBN with correct check digit
            for candidate in docs[0]["isbn"]:
                if re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", candidate) and validate_isbn(candidate):
                    isbn = candidate
                    break
    except Exception:
        # Cache an unsuccessful single attempt as well; do not retry on later queries.
        isbn = None
    db.execute("INSERT OR IGNORE INTO openlibrary_cache(cache_key,isbn) VALUES(?,?)", (key, isbn))
    return isbn


def _group_key(row: dict) -> tuple:
    """Compute grouping key for a row.
    
    Group by ISBN when present, otherwise by normalized title+author.
    """
    isbn = row["isbn"]
    if isbn:
        return ("isbn", isbn)
    else:
        title = normalize(row["title"])
        author = normalize(row["author_hint"])
        return ("title_author", title, author)


def search(query: str, limit: int = 10, db_path: Path | str = DB, opener=None) -> list[dict]:
    """Search books. FTS uses OR so partial hits stay candidates; ranking orders them."""
    query = (query or "").strip()
    if not query or not Path(db_path).is_file():
        return []
    opener = opener or urllib.request.urlopen
    limit = max(1, min(int(limit), 100))
    tokens = normalize(query).split()
    if not tokens:
        return []

    # Filter stop words
    tokens = _filter_stop_words(tokens)

    deadline = time.monotonic() + _budget()  # one wall-clock budget: author calls, matching, ISBN lookups
    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        _cache_init(db)
        ensure_books_search(db)

        # Check if query is an exact ISBN match
        isbn_query = query.replace("-", "").replace(" ", "").upper()
        if re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", isbn_query):
            # Exact ISBN lookup path
            try:
                rows = db.execute(
                    "SELECT shop, url, title, author_hint, isbn FROM books WHERE isbn = ?",
                    (isbn_query,)
                ).fetchall()
            except sqlite3.OperationalError as exc:
                _record_match_error(query, exc)
                return []
        else:
            # FTS5 OR candidates, then rank in Python. A bad MATCH is logged, not swallowed.
            try:
                fts_query = " OR ".join(f'"{token}"*' for token in tokens)
                rows = db.execute("""
                    SELECT b.shop, b.url, b.title, b.author_hint, b.isbn
                    FROM books_search s
                    JOIN books b ON b.rowid = s.rowid
                    WHERE books_search MATCH ?
                """, (fts_query,)).fetchall()
            except sqlite3.OperationalError as exc:
                _record_match_error(query, exc)
                rows = []

        # Lazy author enrichment (Open Library, cached): only when no row's author already matches.
        if not re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", isbn_query) and 1 <= len(tokens) <= 4:
            try:
                from index import authors as _authors
                qn = _authors._tnorm(query)
                title_query = any(
                    _authors._tnorm(r["title"]) == qn for r in rows
                )  # an exact title match already found its book: no author lookup
                if not title_query and not any(_authors.hint_matches(r["author_hint"], tokens) for r in rows):
                    if _authors.enrich(db, query, tokens, opener, deadline=deadline):
                        db.commit()
                        rows = db.execute("""
                            SELECT b.shop, b.url, b.title, b.author_hint, b.isbn
                            FROM books_search s JOIN books b ON b.rowid = s.rowid
                            WHERE books_search MATCH ?
                        """, (" OR ".join(f'"{t}"*' for t in tokens),)).fetchall()
            except Exception as exc:  # Open Library trouble never breaks search
                log.warning("author enrichment failed for %r: %s", query, exc)

        # Group results by ISBN (when present) or by title+author
        # Strategy:
        # 1. First pass: group by ISBN or by title+author
        # 2. Second pass: merge title+author groups into ISBN groups if they match
        groups = {}

        # First pass: create initial groups
        isbn_groups = {}  # isbn -> group
        title_author_groups = {}  # (normalized_title, normalized_author) -> group
        
        for row in rows:
            isbn = row["isbn"]
            title_norm = normalize(row["title"])
            author_norm = normalize(row["author_hint"])
            
            if isbn:
                # Group by ISBN
                if isbn not in isbn_groups:
                    isbn_groups[isbn] = {
                        "title": row["title"],
                        "author": row["author_hint"],
                        "isbn": isbn,
                        "cover_url": None,
                        "shops": [],
                        "_tokens_matched": 0,
                        "_is_exact_phrase": False,
                        "_first_token_pos": float('inf'),
                    }
                item = isbn_groups[isbn]
                item["_tokens_matched"] += 1
                
                # Choose longest/most informative title
                if len(row["title"] or "") > len(item["title"] or ""):
                    item["title"] = row["title"]
                    if row["author_hint"]:
                        item["author"] = row["author_hint"]
                
                # Add shop listing (dedupe by shop, url)
                listing = {"shop": row["shop"], "url": row["url"]}
                if listing not in item["shops"]:
                    item["shops"].append(listing)
            else:
                # Group by title+author
                key = (title_norm, author_norm)
                if key not in title_author_groups:
                    title_author_groups[key] = {
                        "title": row["title"],
                        "author": row["author_hint"],
                        "isbn": None,
                        "cover_url": None,
                        "shops": [],
                        "_tokens_matched": 0,
                        "_is_exact_phrase": False,
                        "_first_token_pos": float('inf'),
                    }
                item = title_author_groups[key]
                item["_tokens_matched"] += 1
                
                # Add shop listing (dedupe by shop, url)
                listing = {"shop": row["shop"], "url": row["url"]}
                if listing not in item["shops"]:
                    item["shops"].append(listing)
        
        # Second pass: merge title_author_groups into isbn_groups if they match
        for (title_norm, author_norm), item in title_author_groups.items():
            merged = False
            for isbn, isbn_item in isbn_groups.items():
                isbn_title_norm = normalize(isbn_item["title"])
                isbn_author_norm = normalize(isbn_item["author"])
                
                if isbn_title_norm == title_norm and isbn_author_norm == author_norm:
                    # Merge into ISBN group
                    for shop_listing in item["shops"]:
                        if shop_listing not in isbn_item["shops"]:
                            isbn_item["shops"].append(shop_listing)
                    isbn_item["_tokens_matched"] += item["_tokens_matched"]
                    merged = True
                    break
            
            if not merged:
                # Keep as separate group
                groups[("title_author", title_norm, author_norm)] = item
        
        # Add ISBN groups to final groups
        for isbn, item in isbn_groups.items():
            groups[("isbn", isbn)] = item
        
        ranked = sorted(
            groups.values(),
            key=lambda x: _rank_key(x["title"], x.get("author"), x.get("isbn"), query, tokens),
        )

        results = []
        _prefetch_isbns(db, [i for i in ranked if not i["isbn"]][:limit], opener, deadline)
        for item in ranked:
            if not item["isbn"]:
                item["isbn"] = _lookup_isbn(db, item["title"], item["author"], opener, cache_only=True)
            if item["isbn"]:
                item["cover_url"] = f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(item['isbn'])}-M.jpg"
            results.append({k: item[k] for k in ("title", "author", "isbn", "cover_url", "shops")})
            if len(results) >= limit:
                break

        db.commit()

    return results

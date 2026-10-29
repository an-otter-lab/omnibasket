"""Plain-code search over the local book index with FTS5 and cached Open Library enrichment."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "index" / "books.sqlite3"
UA = "Omnibasket/1.0 (+https://omnibasket.anottersolution.com/contact)"
TIMEOUT = 5

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


def _ensure_fts_table(db: sqlite3.Connection) -> None:
    """Create FTS5 table if missing, populate it, and add ISBN index"""
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='books_search'"
    ).fetchone()
    if not exists:
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS books_search USING fts5(
            title, author, isbn, tokenize="unicode61 remove_diacritics 2")""")
        db.execute("""INSERT INTO books_search(title, author, isbn)
            SELECT COALESCE(title, ''), COALESCE(author_hint, ''), COALESCE(isbn, '') FROM books""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn)")


def refresh_fts(db_path: Path | str = DB) -> None:
    """Rebuild FTS table from books. Call after a pull to keep search in sync."""
    if not Path(db_path).is_file():
        return
    with sqlite3.connect(str(db_path)) as db:
        db.execute("DROP TABLE IF EXISTS books_search")
        _ensure_fts_table(db)
        db.commit()


def _lookup_isbn(db: sqlite3.Connection, title: str, author: str | None, opener) -> str | None:
    """Look up ISBN from Open Library, validate check digit, and cache result."""
    key = normalize(title) + "|" + normalize(author or "")
    found = db.execute("SELECT isbn FROM openlibrary_cache WHERE cache_key=?", (key,)).fetchone()
    if found is not None:
        return found[0]
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
    """Search books using FTS5 with AND semantics, ranking, and ISBN-based grouping."""
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

    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        _cache_init(db)
        _ensure_fts_table(db)

        # Check if query is an exact ISBN match
        isbn_query = query.replace("-", "").replace(" ", "").upper()
        if re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", isbn_query):
            # Exact ISBN lookup path
            try:
                rows = db.execute(
                    "SELECT shop, url, title, author_hint, isbn FROM books WHERE isbn = ?",
                    (isbn_query,)
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        else:
            # FTS5 search path with OR semantics (candidates), then rank by token matches
            try:
                # Build FTS5 query with OR semantics to get all candidates
                fts_query = " OR ".join(f'"{token}"*' for token in tokens)
                rows = db.execute("""
                    SELECT b.shop, b.url, b.title, b.author_hint, b.isbn
                    FROM books_search s
                    JOIN books b ON b.rowid = s.rowid
                    WHERE books_search MATCH ?
                """, (fts_query,)).fetchall()
            except sqlite3.OperationalError:
                return []

        # Group results by ISBN (when present) or by title+author
        # Strategy:
        # 1. First pass: group by ISBN or by title+author
        # 2. Second pass: merge title+author groups into ISBN groups if they match
        groups = {}
        normalized_query = normalize(query)
        
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
        
        # Compute ranking metrics
        for item in groups.values():
            title_normalized = normalize(item["title"])
            author_normalized = normalize(item.get("author") or "")
            isbn_normalized = normalize(item.get("isbn") or "")
            combined = f"{title_normalized} {author_normalized} {isbn_normalized}"
            
            # Count how many tokens match
            matched_count = sum(1 for token in tokens if token in combined)
            item["_tokens_matched"] = matched_count
            
            # Check exact phrase match
            if normalized_query in title_normalized:
                item["_is_exact_phrase"] = True
            
            # Find first token position
            item["_first_token_pos"] = float('inf')
            for token in tokens:
                pos = title_normalized.find(token)
                if pos != -1:
                    item["_first_token_pos"] = min(item["_first_token_pos"], pos)
        
        # Sort by ranking criteria
        ranked = sorted(
            groups.values(),
            key=lambda x: (
                # 1. Results with all tokens first (already guaranteed by AND)
                # 2. Exact phrase match
                not x["_is_exact_phrase"],
                # 3. Number of matched tokens (more is better)
                -x["_tokens_matched"],
                # 4. First token position (earlier is better)
                x["_first_token_pos"],
                # 5. Shorter title first
                len(normalize(x["title"])),
                # 6. Alphabetical for stability
                normalize(x["title"]),
            )
        )

        results = []
        for item in ranked:
            if not item["isbn"]:
                item["isbn"] = _lookup_isbn(db, item["title"], item["author"], opener)
            if item["isbn"]:
                item["cover_url"] = f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(item['isbn'])}-M.jpg"
            results.append({k: item[k] for k in ("title", "author", "isbn", "cover_url", "shops")})
            if len(results) >= limit:
                break

        db.commit()

    return results

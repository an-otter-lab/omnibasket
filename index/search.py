"""Plain-code search over the local book index with cached Open Library enrichment."""
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


def normalize(value: str | None) -> str:
    value = (value or "").translate(str.maketrans({"ș": "s", "ş": "s", "ț": "t", "ţ": "t"}))
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _cache_init(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS openlibrary_cache (
        cache_key TEXT PRIMARY KEY, isbn TEXT, checked INTEGER NOT NULL DEFAULT 1)""")


def _lookup_isbn(db: sqlite3.Connection, title: str, author: str | None, opener) -> str | None:
    key = normalize(title) + "|" + normalize(author)
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
            isbn = next((x for x in docs[0]["isbn"] if re.fullmatch(r"(?:97[89])?\d{9}[\dXx]", x)), None)
    except Exception:
        # Cache an unsuccessful single attempt as well; do not retry on later queries.
        isbn = None
    db.execute("INSERT OR IGNORE INTO openlibrary_cache(cache_key,isbn) VALUES(?,?)", (key, isbn))
    return isbn


def search(query: str, limit: int = 10, db_path: Path | str = DB, opener=None) -> list[dict]:
    query = (query or "").strip()
    if not query or not Path(db_path).is_file():
        return []
    opener = opener or urllib.request.urlopen
    limit = max(1, min(int(limit), 100))
    tokens = normalize(query).split()
    if not tokens:
        return []
    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        _cache_init(db)
        try:
            rows = db.execute("SELECT shop,url,title,author_hint,isbn FROM books WHERE title IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            return []
        groups = {}
        for row in rows:
            title, author, isbn = row["title"] or "", row["author_hint"], row["isbn"]
            fields = [normalize(title), normalize(author), normalize(isbn)]
            score = sum(1 for token in tokens if any(token in field for field in fields))
            if normalize(query) == fields[0]:
                score += 2 * len(tokens) + 1
            elif normalize(query) in fields[0]:
                score += len(tokens) + 1
            if not score:
                continue
            key = ("isbn", isbn) if isbn else ("title-author", normalize(title), normalize(author))
            item = groups.setdefault(key, {"title": title, "author": author, "isbn": isbn,
                "cover_url": None, "shops": [], "_score": 0})
            item["_score"] = max(item["_score"], score)
            if not item["author"] and author:
                item["author"] = author
            if not item["isbn"] and isbn:
                item["isbn"] = isbn
            listing = {"shop": row["shop"], "url": row["url"]}
            if listing not in item["shops"]:
                item["shops"].append(listing)
        ranked = sorted(groups.values(), key=lambda x: (-x["_score"], -len(x["shops"]), abs(len(normalize(x["title"])) - len(normalize(query))), normalize(x["title"])))
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

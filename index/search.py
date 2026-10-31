"""Book search: the Open Library catalogue decides what a book is; the shops decide where it is sold.

Open Library (search.json) returns works with proper titles, authors, ISBNs and covers, in RO and EN.
Shop availability is then added per ISBN: Books-Express from the local index ISBN lookup, Libris by an
index title match confirmed once from the product page's schema.org JSON-LD (cached), Bookzone and eMAG
as a link plus an honest "not checked here". Shop rows are never shown as books and shop images never
used as covers. The local index keeps FTS only for the photo reader (api/photo_read.py).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from matching import ranking

log = logging.getLogger(__name__)
# MATCH failures are recorded here so an empty result is not silent.
MATCH_ERRORS: list[dict] = []

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "index" / "books.sqlite3"
UA = "Omnibasket/1.0 (+https://omnibasket.anottersolution.com/contact)"
TIMEOUT = 5
OL_CACHE_TTL = 86400  # 24 h for Open Library answers and confirmed Libris reads
ERROR_TTL = 600  # a failed Libris read is not retried for 10 min
MIN_REQUEST_INTERVAL = 1.0  # polite: at most one Open Library request per second, process-wide
LIBRIS_READS = 3  # product pages read per search (the top results only)
LIBRIS_TIMEOUT = 4.0
# S30: the most one Libris title match may take. A photo read runs it once per line, so a slow
# match must give up (no Libris link for that line) rather than hold the whole read.
LIBRIS_MATCH_SECONDS = 1.0
LIBRIS_MATCH_CHECK_EVERY = 1000  # SQLite steps between two looks at the clock
OL_FIELDS = "key,title,author_name,cover_i,isbn,first_publish_year"
BOOST = 1.5  # a result with a known shop offer moves up one place; Open Library's top result stays first

_rate_lock = threading.Lock()
_last_request_time = 0.0

STOP_WORDS = {
    "si", "și", "de", "din", "la", "cu", "pe", "in", "un", "o", "le", "lui",
    "a", "ale", "ea", "ei", "eu", "tu", "el", "noi", "voi", "ele",
    "the", "an", "and", "or", "of", "for", "on", "at", "to",
}


class SearchUnavailable(Exception):
    """Open Library did not answer and nothing fresh is cached. Never turned into an empty list."""


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
    s = isbn.replace("-", "").replace(" ", "").upper()
    if len(s) == 10:
        total = 0
        for i, ch in enumerate(s[:-1]):
            if not ch.isdigit():
                return False
            total += (10 - i) * int(ch)
        last = s[-1]
        if last == "X":
            total += 10
        elif last.isdigit():
            total += int(last)
        else:
            return False
        return total % 11 == 0
    if len(s) == 13:
        # S4b: an ISBN-13 always starts 978 or 979; anything else is a product barcode.
        if not s.isdigit() or s[:3] not in ("978", "979"):
            return False
        return sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(s)) % 10 == 0
    return False


def to_isbn13(isbn: str | None) -> str | None:
    """A valid ISBN-10/13 (hyphens allowed) as ISBN-13, else None."""
    s = (isbn or "").replace("-", "").replace(" ", "").upper()
    if not validate_isbn(s):
        return None
    if len(s) == 13:
        return s
    body = "978" + s[:-1]
    check = (10 - sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(body)) % 10) % 10
    return body + str(check)


def _filter_stop_words(tokens: list[str]) -> list[str]:
    """Remove stop words from token list, but keep at least one token."""
    filtered = [t for t in tokens if t not in STOP_WORDS]
    return filtered if filtered else tokens


# ---------------------------------------------------------------- Open Library client


def _cache_init(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS ol_search_cache (
        cache_key TEXT PRIMARY KEY, response_json TEXT, cached_at INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS libris_page_cache (
        url TEXT PRIMARY KEY, isbn TEXT, status TEXT NOT NULL, cached_at INTEGER NOT NULL)""")


def _rate_limit() -> None:
    """Hold the caller until MIN_REQUEST_INTERVAL has passed since the last Open Library request."""
    global _last_request_time
    with _rate_lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()


def _ol_get(db: sqlite3.Connection, key: str, url: str, opener, required: bool = True) -> dict | None:
    """Cached JSON GET. A hit costs no request. A failure raises SearchUnavailable (required) or
    returns None, and is never cached, so the next search tries again."""
    row = db.execute("SELECT response_json, cached_at FROM ol_search_cache WHERE cache_key=?", (key,)).fetchone()
    if row and time.time() - row[1] < OL_CACHE_TTL:
        return json.loads(row[0])
    _rate_limit()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with opener(req, timeout=TIMEOUT) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("unexpected Open Library payload")
    except Exception as exc:
        log.warning("open library request failed (%s): %s", key.split(":", 1)[0], exc)
        if required:
            raise SearchUnavailable(str(exc)) from exc
        return None
    db.execute("INSERT OR REPLACE INTO ol_search_cache(cache_key, response_json, cached_at) VALUES (?,?,?)",
               (key, json.dumps(payload), int(time.time())))
    return payload


def _ol_search(db: sqlite3.Connection, query: str, opener) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "limit": 10, "fields": OL_FIELDS})
    key = "search:" + " ".join(normalize(query).split())
    payload = _ol_get(db, key, "https://openlibrary.org/search.json?" + params, opener)
    return [d for d in payload.get("docs", []) if isinstance(d, dict) and d.get("title")]


def _edition(db: sqlite3.Connection, isbn: str, opener) -> dict | None:
    """The edition record for one ISBN (its own title and cover). Best effort, never fatal."""
    return _ol_get(db, "isbn:" + isbn, f"https://openlibrary.org/isbn/{isbn}.json", opener, required=False)


def cover_url(cover_i: int | None, isbn: str | None) -> str | None:
    """Open Library covers only, by cover id or ISBN. Shop images are never used."""
    if cover_i:
        return f"https://covers.openlibrary.org/b/id/{int(cover_i)}-M.jpg"
    if isbn:
        return f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(isbn)}-M.jpg"
    return None


# ---------------------------------------------------------------- shop availability


def _books_express(db: sqlite3.Connection, isbns: list[str]) -> dict[str, dict]:
    """isbn -> {shop, url} for the ISBNs the Books-Express index carries."""
    found: dict[str, dict] = {}
    for i in range(0, len(isbns), 400):
        chunk = isbns[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for isbn, url in db.execute(
            f"SELECT isbn, url FROM books WHERE shop='books-express' AND isbn IN ({marks})", chunk
        ):
            found.setdefault(isbn, {"shop": "books-express", "url": url})
    return found


def _index_titles(db: sqlite3.Connection, isbns: list[str]) -> dict[str, str]:
    """isbn -> the shop index's own title: evidence that a printing is a dialect or
    special edition ("matilda in scots"), or a different book in a bundle."""
    found: dict[str, str] = {}
    for i in range(0, len(isbns), 400):
        chunk = isbns[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for isbn, title in db.execute(
            f"SELECT isbn, title FROM books WHERE isbn IN ({marks}) AND title IS NOT NULL AND title != ''",
            chunk,
        ):
            found.setdefault(isbn, title)
    return found


def _doc_isbns(doc: dict) -> list[str]:
    """The work's ISBNs as ISBN-13, in the catalogue's order."""
    isbns: list[str] = []
    for raw in doc.get("isbn") or []:
        i13 = to_isbn13(raw)
        if i13 and i13 not in isbns:
            isbns.append(i13)
    return isbns[:400]


def _rows(items: list[dict]) -> list[dict]:
    """One row per book to show. The best work is shown as its Romanian edition and
    then its English original when both exist and the titles differ: a parent here
    may want either, and both are shoppable."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        doc_title = it["doc"]["title"]
        ro, en = it["ro_isbn"], it["en_isbn"]
        authors = it["doc"].get("author_name") or []
        if (it["pos"] == 0 and ro and en and ro != en and it["edition_title"]
                and ranking.fold(it["edition_title"]) != ranking.fold(doc_title)):
            rows.append({"item": it, "title": it["edition_title"], "isbn": ro, "cover_i": it["cover_i"]})
            rows.append({"item": it, "title": doc_title, "isbn": en, "cover_i": it["doc"].get("cover_i")})
            seen.add((ranking.fold(it["edition_title"]), ranking.fold(authors[0] if authors else "")))
            seen.add((ranking.fold(doc_title), ranking.fold(authors[0] if authors else "")))
            continue
        title = it["edition_title"] if (it["isbn"] == ro and it["edition_title"]) else doc_title
        key = (ranking.fold(title), ranking.fold(authors[0] if authors else ""))
        if key in seen:
            continue  # the same book, another catalogue record: one row is enough
        seen.add(key)
        rows.append({"item": it, "title": title, "isbn": it["isbn"], "cover_i": it["cover_i"]})
    return rows


def _fold(word: str) -> str:
    """z and s are folded: Romanian spellings differ (filozofala / filosofala)."""
    return word.replace("z", "s")


def _words(text: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", normalize(text)) if w not in STOP_WORDS]


def _libris_candidate(db: sqlite3.Connection, titles: list[str]) -> str | None:
    """URL of the Libris index row whose title holds every significant word of a work title."""
    for title in titles:
        words = _words(title)[:6]
        if len(words) < 2:
            continue
        stems = [re.split(r"[sz]", w, maxsplit=1)[0] for w in words]
        stems = [s for s in stems if s]
        if not stems:
            continue
        # S30: CROSS JOIN keeps the full-text match as the outer loop. With a plain JOIN SQLite
        # walked every Libris row (about 54k) and ran the MATCH once per row: 3-4 s for
        # "Matilda", minutes for "Guess How Much I Love You" (its "i"* prefix matches 100k+ words).
        deadline = time.monotonic() + LIBRIS_MATCH_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, LIBRIS_MATCH_CHECK_EVERY)
        try:
            rows = db.execute(
                """SELECT b.url, b.title FROM books_search s CROSS JOIN books b ON b.rowid = s.rowid
                   WHERE books_search MATCH ? AND b.shop = 'libris' LIMIT 200""",
                (" AND ".join(f'"{s}"*' for s in stems),),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if time.monotonic() > deadline:
                log.warning("libris title match over %.1f s, skipped: %s", LIBRIS_MATCH_SECONDS, title)
                MATCH_ERRORS.append({"query": title, "error": "time cap"})
            else:
                MATCH_ERRORS.append({"query": title, "error": str(exc)})
            return None
        finally:
            db.set_progress_handler(None, 0)
        want = {_fold(w) for w in words}
        fits = [(len(normalize(t)), u) for u, t in rows if want <= {_fold(w) for w in _words(t)}]
        if fits:
            return min(fits)[1]
    return None


def _libris_cached(db: sqlite3.Connection, url: str):
    row = db.execute("SELECT isbn, status, cached_at FROM libris_page_cache WHERE url=?", (url,)).fetchone()
    if not row:
        return None
    isbn, status, at = row
    if time.time() - at < (ERROR_TTL if status == "error" else OL_CACHE_TTL):
        return isbn, status
    return None


def _libris_read(url: str, fetcher) -> tuple[str | None, str]:
    """ONE product-page read through the fetch guard; the ISBN comes from schema.org JSON-LD only."""
    try:
        res = fetcher(url, timeout=LIBRIS_TIMEOUT)
    except Exception as exc:
        log.warning("libris page read failed: %s", exc)
        return None, "error"
    if res.status != 200:
        return None, "error"
    isbn = _jsonld_isbn(res.text)
    return (isbn, "ok") if isbn else (None, "no_isbn")


_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _jsonld_isbn(html: str) -> str | None:
    """The ISBN-13 a Product/Book node of the page's schema.org JSON-LD declares (flat, list or @graph)."""
    def nodes(obj):
        if isinstance(obj, list):
            for o in obj:
                yield from nodes(o)
        elif isinstance(obj, dict):
            yield obj
            yield from nodes(obj.get("@graph", []))

    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in nodes(data):
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not {"Product", "Book"} & {k for k in kinds if isinstance(k, str)}:
                continue
            for key in ("isbn", "gtin13", "gtin"):
                value = node.get(key)
                for v in value if isinstance(value, list) else [value]:
                    i13 = to_isbn13(str(v)) if v else None
                    if i13:
                        return i13
    return None


def _other_shops(isbn: str | None, title: str) -> list[dict]:
    needle = urllib.parse.quote(isbn or title)
    return [
        {"shop": "bookzone", "url": f"https://www.bookzone.ro/search?q={needle}",
         "status": "not_checked", "reason": "Not checked here"},
        {"shop": "emag", "url": f"https://www.emag.ro/search/{needle}",
         "status": "not_checked", "reason": "Not checked here"},
    ]


# ---------------------------------------------------------------- the search


def search(query: str, limit: int = 10, db_path: Path | str = DB, opener=None, fetcher=None) -> list[dict]:
    """Books for a title, author or ISBN (RO or EN, diacritics ignored), ranked by Open Library
    relevance and boosted when a shop is known to carry the ISBN. Raises SearchUnavailable when
    Open Library cannot be reached and nothing fresh is cached."""
    query = (query or "").strip()
    if not query or not Path(db_path).is_file():
        return []
    opener = opener or urllib.request.urlopen
    if fetcher is None:
        from api import fetch_guard

        def fetcher(url, timeout=LIBRIS_TIMEOUT):
            return fetch_guard.fetch(url, timeout=timeout)

    limit = max(1, min(int(limit), 100))
    asked = to_isbn13(query) if re.fullmatch(r"[\d\-\sXx]{10,17}", query) else None

    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        _cache_init(db)
        ensure_books_search(db)
        # S7: rank every doc Open Library returned (it is asked for 10), and cut to `limit`
        # only at the end, so a smaller limit is always a prefix of a larger one.
        docs = _ol_search(db, asked or query, opener)

        # The catalogue's order is for its whole corpus: rank it for this shopper first,
        # then choose the ISBN of each work (never a dialect or foreign printing).
        order = list(range(len(docs))) if asked else ranking.rank_docs(query, docs)
        ranked = [{"doc": docs[i], "isbns": _doc_isbns(docs[i])} for i in order]
        if asked:
            # An ISBN query names one edition: only the works that hold it answer it.
            holding = [it for it in ranked if asked in it["isbns"]]
            ranked = holding or ranked[:1]
            for it in ranked:
                if asked not in it["isbns"]:
                    it["isbns"].insert(0, asked)
        every_isbn = sorted({i for it in ranked for i in it["isbns"]})
        index_titles = _index_titles(db, every_isbn)
        carried = _books_express(db, every_isbn)

        items = []
        for it in ranked:
            usable = it["isbns"] if asked else ranking.usable_isbns(it["isbns"], index_titles)
            if it["isbns"] and not usable:
                continue  # only foreign printings (978-89, 978-7, ...): not a book we can price
            it["pos"] = len(items)
            it["ro_isbn"] = asked or ranking.pick_isbn(usable, index_titles, "ro")
            it["en_isbn"] = asked or ranking.pick_isbn(usable, index_titles, "en")
            it["isbn"] = asked or it["ro_isbn"] or it["en_isbn"] or (usable[0] if usable else None)
            # Romanian edition: its own title and cover when Open Library has them.
            it["edition_title"] = None
            it["cover_i"] = it["doc"].get("cover_i")
            if it["isbn"] and ranking.is_ro_isbn(it["isbn"]) and it["pos"] < 3:
                ed = _edition(db, it["isbn"], opener) or {}
                if ed.get("title"):
                    it["edition_title"] = ed["title"]
                if ed.get("covers"):
                    it["cover_i"] = next((c for c in ed["covers"] if isinstance(c, int) and c > 0), it["cover_i"])
            items.append(it)

        rows = _rows(items)

        # Libris: index title match, then ONE product-page read (cached) confirmed from schema.org.
        pending = {}
        for row in rows[:LIBRIS_READS]:
            url = _libris_candidate(db, [row["title"]])
            row["libris_url"] = url
            if url and _libris_cached(db, url) is None:
                pending[url] = None
        if pending:
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                futures = {u: pool.submit(_libris_read, u, fetcher) for u in pending}
                for u, fut in futures.items():
                    isbn, status = fut.result()
                    db.execute("INSERT OR REPLACE INTO libris_page_cache(url, isbn, status, cached_at) VALUES (?,?,?,?)",
                               (u, isbn, status, int(time.time())))
        db.commit()

        results = []
        for row in rows:
            it = row["item"]
            isbn = row["isbn"]
            url = row.get("libris_url")
            libris_isbn = None
            if url:
                hit = _libris_cached(db, url)
                if hit and hit[1] == "ok" and hit[0] in it["isbns"]:
                    libris_isbn = hit[0]
                    if not (asked and asked == isbn):
                        isbn = libris_isbn  # the edition a shop is confirmed to hold
            shops = []
            if isbn in carried:
                shops.append(dict(carried[isbn]))
            if libris_isbn and libris_isbn == isbn:
                shops.append({"shop": "libris", "url": url})
            title = row["title"] if isbn == row["isbn"] else it["doc"]["title"]
            authors = it["doc"].get("author_name") or []
            results.append({
                "title": title,
                "author": authors[0] if authors else None,
                "isbn": isbn,
                "cover_url": cover_url(row.get("cover_i"), isbn),
                "shops": shops,
                "other_shops": _other_shops(isbn, title),
                "_rank": -1 if it["pos"] == 0 else it["pos"] - (BOOST if shops else 0),
            })
        results.sort(key=lambda r: r["_rank"])
        for r in results:
            del r["_rank"]
        return results[:limit]


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



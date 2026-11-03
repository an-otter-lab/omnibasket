"""Book search: the Open Library catalogue decides what a book is; the shops decide where it is sold.

Open Library (search.json) returns works with proper titles, authors, ISBNs and covers, in RO and EN.
Shop availability is then added per ISBN: Libris by an index title match confirmed once from the product
page's schema.org JSON-LD (cached), Bookzone and eMAG as a link plus an honest "not checked here".
Elefant rows carry no ISBN, so Elefant is found by the live read, not here. Books-Express is no longer a
live shop (3 Nov), so its index rows are title evidence only, never a "found at" chip. Shop rows are never shown as books and shop images never
used as covers. The local index keeps FTS only for the photo reader (api/photo_read.py).

When Open Library does not answer in time and nothing is cached, /search answers from the shop index
instead (titles and ISBNs as the shops list them, marked "source": "shop_listings"). Network waits run on
a small shared pool behind one deadline; an answer that comes later is still cached for the next search.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from matching import ranking

log = logging.getLogger(__name__)
# MATCH failures are recorded here so an empty result is not silent.
MATCH_ERRORS: list[dict] = []

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "index" / "books.sqlite3"
UA = "Omnibasket/1.0 (+https://omnibasket.anottersolution.com/contact)"
TIMEOUT = 5  # one socket operation; the waits below bound the whole search
OL_HOST = "openlibrary.org"
OL_SEARCH_SECONDS = 3.0  # search.json gets this long, then a stale cached answer or the shop index answers
SEARCH_SECONDS = 3.0  # editions and Libris reads are waited for until this long after the search began
OL_WORKERS = 3  # Open Library requests in flight at once, every search together (still one start per second)
SHOP_WORKERS = 6  # Libris page reads in flight at once, every search together
OL_MAX_BYTES = 2_000_000
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

# Network waits run here, not on the request thread, so a search can stop waiting at its deadline while
# the request finishes and caches its answer. Two searches asking for the same thing share one request.
# Two pools: Open Library requests queue on the rate limit and must not hold up the shop reads.
_OL_POOL = ThreadPoolExecutor(max_workers=OL_WORKERS, thread_name_prefix="search-ol")
_SHOP_POOL = ThreadPoolExecutor(max_workers=SHOP_WORKERS, thread_name_prefix="search-shop")
_inflight: dict[tuple, Future] = {}
_inflight_lock = threading.RLock()

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


def _shared(pool: ThreadPoolExecutor, key: tuple, fn, *args) -> Future:
    """fn(*args) on the pool, or the run already in flight for the same key."""
    with _inflight_lock:
        fut = _inflight.get(key)
        if fut is None:
            fut = pool.submit(fn, *args)
            _inflight[key] = fut
            fut.add_done_callback(lambda done: _forget(key, done))
        return fut


def _forget(key: tuple, fut: Future) -> None:
    with _inflight_lock:
        if _inflight.get(key) is fut:
            del _inflight[key]


def _store(db_path, sql: str, args: tuple) -> None:
    """One cache write from a pool thread, on its own connection."""
    with closing(sqlite3.connect(str(db_path), timeout=10)) as db:
        db.execute(sql, args)
        db.commit()


class _Body:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]


_idle: list[http.client.HTTPSConnection] = []
_idle_lock = threading.Lock()


def _ol_open(req: urllib.request.Request, timeout: float = TIMEOUT) -> _Body:
    """GET from openlibrary.org on a kept-alive connection: a new TLS handshake costs 1.5-2 s of a
    2-5 s request, a reused connection answers in about 0.4 s. Follows same-host redirects
    (/isbn/ answers 302) and raises on anything but 200, as urlopen does."""
    url = req.full_url
    headers = dict(req.header_items())
    for _ in range(4):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname != OL_HOST:
            raise OSError(f"not an Open Library address: {parts.hostname}")
        status, location, body = _ol_request(parts.path + ("?" + parts.query if parts.query else ""), headers, timeout)
        if status in (301, 302, 303, 307, 308) and location:
            url = urllib.parse.urljoin(url, location)
            continue
        if status != 200:
            raise OSError(f"open library answered {status}")
        return _Body(body)
    raise OSError("open library redirected too often")


def _ol_request(path: str, headers: dict, timeout: float) -> tuple[int, str | None, bytes]:
    with _idle_lock:
        conn = _idle.pop() if _idle else None
    reused = conn is not None
    while True:
        if conn is None:
            conn = http.client.HTTPSConnection(OL_HOST, timeout=timeout)
        elif conn.sock is not None:
            conn.sock.settimeout(timeout)
        try:
            conn.request("GET", path, headers=headers)
            res = conn.getresponse()
            body = res.read(OL_MAX_BYTES + 1)
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
            conn.close()
            conn = None
            if reused:  # the kept connection had been closed by the server: once more on a new one
                reused = False
                continue
            raise
        except BaseException:
            conn.close()
            raise
        if len(body) > OL_MAX_BYTES or res.will_close:
            conn.close()
        else:
            with _idle_lock:
                if len(_idle) < OL_WORKERS:
                    _idle.append(conn)
                    conn = None
            if conn is not None:
                conn.close()
        return res.status, res.getheader("Location"), body[:OL_MAX_BYTES]


def _ol_fetch(db_path, key: str, url: str, opener) -> dict:
    """ONE Open Library request (rate-limited); a good answer is cached even when nobody waits for it."""
    _rate_limit()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with opener(req, timeout=TIMEOUT) as response:
        payload = json.loads(response.read(OL_MAX_BYTES).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unexpected Open Library payload")
    _store(db_path, "INSERT OR REPLACE INTO ol_search_cache(cache_key, response_json, cached_at) VALUES (?,?,?)",
           (key, json.dumps(payload), int(time.time())))
    return payload


def _ol_cached(db: sqlite3.Connection, key: str) -> tuple[dict, bool] | None:
    """The cached answer for a key and whether it is still fresh."""
    row = db.execute("SELECT response_json, cached_at FROM ol_search_cache WHERE cache_key=?", (key,)).fetchone()
    if not row:
        return None
    return json.loads(row[0]), time.time() - row[1] < OL_CACHE_TTL


def _ol_get(db: sqlite3.Connection, db_path, key: str, url: str, opener, wait: float,
            required: bool = True) -> dict | None:
    """Cached JSON GET. A fresh hit costs no request. Otherwise the request runs on the pool and is
    waited for `wait` seconds; a failure or a late answer falls back to a stale cached answer, then
    raises SearchUnavailable (required) or returns None. Failures are never cached."""
    cached = _ol_cached(db, key)
    if cached and cached[1]:
        return cached[0]
    fut = _shared(_OL_POOL, (str(db_path), key, opener), _ol_fetch, db_path, key, url, opener)
    try:
        return fut.result(timeout=max(0.0, wait))
    except Exception as exc:
        reason = str(exc) or ("no answer in %.1f s" % wait)
        log.warning("open library request failed (%s): %s", key.split(":", 1)[0], reason)
        if cached:
            return cached[0]  # yesterday's answer beats none
        if required:
            raise SearchUnavailable(reason) from exc
        return None


def _ol_search(db: sqlite3.Connection, db_path, query: str, opener) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "limit": 10, "fields": OL_FIELDS})
    key = "search:" + " ".join(normalize(query).split())
    payload = _ol_get(db, db_path, key, "https://openlibrary.org/search.json?" + params, opener, OL_SEARCH_SECONDS)
    return [d for d in payload.get("docs", []) if isinstance(d, dict) and d.get("title")]


CACHED_ANSWERS = 200  # cached Open Library answers looked at when it does not answer


def _cached_docs(db: sqlite3.Connection, query: str, asked: str | None) -> list[dict]:
    """Open Library did not answer: the works its earlier answers to OTHER queries named that fit
    this one (every word of the query in the title or author, or the asked ISBN), newest first."""
    words = list(dict.fromkeys(_words(query)))
    probe = asked or max(words, key=len, default="")
    if not probe:
        return []
    found: dict[tuple, dict] = {}
    for (raw,) in db.execute(
        """SELECT response_json FROM ol_search_cache WHERE cache_key LIKE 'search:%' AND response_json LIKE ?
           ORDER BY cached_at DESC LIMIT ?""", (f"%{probe}%", CACHED_ANSWERS)):
        try:
            docs = json.loads(raw).get("docs") or []
        except (ValueError, AttributeError):
            continue
        for doc in docs:
            if not isinstance(doc, dict) or not doc.get("title"):
                continue
            if asked:
                if asked not in _doc_isbns(doc):
                    continue
            else:
                have = set(_words(" ".join([doc["title"], *[a for a in doc.get("author_name") or [] if isinstance(a, str)]])))
                if not set(words) <= have:
                    continue
            authors = doc.get("author_name") or [""]
            found.setdefault(doc.get("key") or (ranking.fold(doc["title"]), ranking.fold(str(authors[0]))), doc)
    return list(found.values())[:10]


def _editions(db: sqlite3.Connection, db_path, isbns: list[str], opener, by: float,
              network: bool = True) -> dict[str, dict]:
    """isbn -> its edition record (own title and cover), asked for together and waited for until `by`.
    Best effort, never fatal: a late edition is cached for the next search and skipped in this one.
    Without `network` (Open Library just failed) only cached editions are used."""
    found: dict[str, dict] = {}
    pending: dict[str, Future] = {}
    for isbn in dict.fromkeys(isbns):
        cached = _ol_cached(db, "isbn:" + isbn)
        if cached and (cached[1] or not network):
            found[isbn] = cached[0]
            continue
        if not network:
            continue
        key = "isbn:" + isbn
        pending[isbn] = _shared(_OL_POOL, (str(db_path), key, opener), _ol_fetch, db_path, key,
                                f"https://openlibrary.org/isbn/{isbn}.json", opener)
    for isbn, fut in pending.items():
        try:
            found[isbn] = fut.result(timeout=max(0.0, by - time.monotonic()))
        except Exception as exc:
            log.warning("open library request failed (isbn): %s", str(exc) or "no answer by the deadline")
            cached = _ol_cached(db, "isbn:" + isbn)
            if cached:
                found[isbn] = cached[0]
    return found


def cover_url(cover_i: int | None, isbn: str | None) -> str | None:
    """Open Library covers only, by cover id or ISBN. Shop images are never used."""
    if cover_i:
        return f"https://covers.openlibrary.org/b/id/{int(cover_i)}-M.jpg"
    if isbn:
        return f"https://covers.openlibrary.org/b/isbn/{urllib.parse.quote(isbn)}-M.jpg"
    return None


# ---------------------------------------------------------------- shop availability


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


def _libris_task(db_path, url: str, fetcher) -> tuple[str | None, str]:
    """The one read of a Libris page, cached (an error for ERROR_TTL) even when nobody waits for it."""
    isbn, status = _libris_read(url, fetcher)
    _store(db_path, "INSERT OR REPLACE INTO libris_page_cache(url, isbn, status, cached_at) VALUES (?,?,?,?)",
           (url, isbn, status, int(time.time())))
    return isbn, status


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


# P3: a children's-books demo does not list titles with strong profanity ("the Subtle Art of Not
# Giving a F*ck" for "sapiens") unless the shopper typed such a word. An ISBN search is never filtered.
# Also the starred spellings on real covers ("F*ck", "Sh*t"). Hidden, not ranked lower (Adrian, 1 Nov).
_PROFANE = re.compile(r"\b(?:\w*f(?:u|\*)ck\w*|(?:bull)?sh(?:i|\*)t(?:s|ty)?|cunt\w*)\b", re.IGNORECASE)


def _profane(text: object) -> bool:
    return isinstance(text, str) and bool(_PROFANE.search(text))


FALLBACK_SECONDS = 1.0  # the most the shop-index match may take
FALLBACK_ROWS = 300  # best full-text matches looked at
# A shop slug drops the star and the apostrophe: "the subtle art of not giving a f ck".
_PROFANE_SLUG = re.compile(r"\b(?:f ck\w*|(?:bull)?sh t(?:s|ty)?)\b")


def _listing_title(title: str) -> str:
    """A shop's slug title as a title: sentence case, "philosopher s stone" -> "philosopher's stone"."""
    title = re.sub(r"(?<=[a-z])\s+s\b", "'s", title.strip())
    return title[:1].upper() + title[1:]


def _index_fallback(db: sqlite3.Connection, query: str, asked: str | None) -> list[dict]:
    """Open Library did not answer and nothing is cached: books from the shop index instead, as the
    shops list them (an ISBN and a title, no cover id, no shop chip: Books-Express rows are title
    evidence only). Ranked by the same score as catalogue works. Raises SearchUnavailable when the
    index has nothing either; an ISBN query it does not hold is an empty list (the ISBN still names
    a book the shops can be asked about)."""
    if asked:
        rows = db.execute("SELECT title, author_hint, isbn FROM books WHERE isbn = ? AND title != ''",
                          (asked,)).fetchall()
        if not rows:
            return []
    else:
        words = list(dict.fromkeys(_words(query)))[:8]
        if not words:
            raise SearchUnavailable("open library did not answer and the query has no words to match")
        deadline = time.monotonic() + FALLBACK_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, LIBRIS_MATCH_CHECK_EVERY)
        try:
            rows = db.execute(
                """SELECT b.title, b.author_hint, b.isbn FROM books_search s CROSS JOIN books b ON b.rowid = s.rowid
                   WHERE books_search MATCH ? AND b.isbn IS NOT NULL AND b.isbn != '' AND b.title != ''
                   ORDER BY s.rank LIMIT ?""",
                ("{title author} : (" + " AND ".join(f'"{w}"' for w in words) + ")", FALLBACK_ROWS),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise SearchUnavailable(f"open library did not answer and the index match failed: {exc}") from exc
        finally:
            db.set_progress_handler(None, 0)
    best: dict[str, tuple] = {}
    printings: dict[str, int] = {}
    for pos, (title, author, isbn) in enumerate(rows):
        isbn = to_isbn13(isbn)
        if not isbn or not ranking.is_allowed_isbn(isbn):
            continue
        if not asked and not _profane(query) and (_profane(title) or _PROFANE_SLUG.search(title)):
            continue
        doc = {"title": title, "author_name": [author] if author else [], "isbn": [isbn]}
        score = ranking.rank_score(query, doc)
        key = ranking.fold(title)
        printings[key] = printings.get(key, 0) + 1
        if key not in best or (-score, pos) < best[key][0]:
            best[key] = ((-score, pos), title, author, isbn)  # one row per title: the best-scored printing
    if not best and not asked:
        raise SearchUnavailable("open library did not answer and the index holds no match")
    # A title the shops list in several printings is the book people buy ("sapiens a brief history
    # of humankind" over "sapiens reinvented"): one point per extra printing, two at most.
    order = sorted(best, key=lambda k: (best[k][0][0] - min(2, printings[k] - 1), best[k][0][1]))
    results = []
    for _rank, title, author, isbn in (best[k] for k in order):
        shown_title = _listing_title(title)
        results.append({
            "title": shown_title,
            "author": author or None,
            "isbn": isbn,
            "cover_url": cover_url(None, isbn),
            "shops": [],
            "other_shops": _other_shops(isbn, shown_title),
            "source": "shop_listings",
        })
    return results


def search(query: str, limit: int = 10, db_path: Path | str = DB, opener=None, fetcher=None,
           fallback: bool = False) -> list[dict]:
    """Books for a title, author or ISBN (RO or EN, diacritics ignored), ranked by Open Library
    relevance and boosted when a shop is known to carry the ISBN. Raises SearchUnavailable when
    Open Library cannot be reached and nothing is cached; with `fallback` (the /search route) the works
    its earlier answers named, then the shop index, answer instead, and SearchUnavailable means neither
    had anything. Edition lookups and Libris reads are waited for until SEARCH_SECONDS after the start;
    later answers are cached."""
    started = time.monotonic()
    query = (query or "").strip()
    if not query or not Path(db_path).is_file():
        return []
    opener = opener or _ol_open
    if fetcher is None:
        from api import fetch_guard

        def fetcher(url, timeout=LIBRIS_TIMEOUT):
            return fetch_guard.fetch(url, timeout=timeout)

    limit = max(1, min(int(limit), 100))
    asked = to_isbn13(query) if re.fullmatch(r"[\d\-\sXx]{10,17}", query) else None
    by = started + SEARCH_SECONDS

    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        _cache_init(db)
        ensure_books_search(db)
        db.commit()  # pool threads write the caches on their own connections
        # S7: rank every doc Open Library returned (it is asked for 10), and cut to `limit`
        # only at the end, so a smaller limit is always a prefix of a larger one.
        online = True
        try:
            docs = _ol_search(db, db_path, asked or query, opener)
        except SearchUnavailable:
            if not fallback:
                raise
            # Open Library is down or slow: the works it named for earlier searches, else the shop index.
            docs = _cached_docs(db, query, asked)
            if not docs:
                return _index_fallback(db, query, asked)[:limit]
            online = False

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
        if not asked and not _profane(query):
            ranked = [it for it in ranked if not (_profane(it["doc"].get("title")) or _profane(it["doc"].get("subtitle")))]
        every_isbn = sorted({i for it in ranked for i in it["isbns"]})
        index_titles = _index_titles(db, every_isbn)

        items = []
        for it in ranked:
            usable = it["isbns"] if asked else ranking.usable_isbns(it["isbns"], index_titles)
            if it["isbns"] and not usable:
                continue  # only foreign printings (978-89, 978-7, ...): not a book we can price
            it["pos"] = len(items)
            it["ro_isbn"] = asked or ranking.pick_isbn(usable, index_titles, "ro")
            it["en_isbn"] = asked or ranking.pick_isbn(usable, index_titles, "en")
            it["isbn"] = asked or it["ro_isbn"] or it["en_isbn"] or (usable[0] if usable else None)
            it["edition_title"] = None
            it["cover_i"] = it["doc"].get("cover_i")
            items.append(it)

        # Romanian edition: its own title and cover when Open Library has them (the top three, together).
        romanian = [it for it in items if it["isbn"] and ranking.is_ro_isbn(it["isbn"]) and it["pos"] < 3]
        editions = _editions(db, db_path, [it["isbn"] for it in romanian], opener, by, network=online)
        for it in romanian:
            ed = editions.get(it["isbn"]) or {}
            if ed.get("title"):
                it["edition_title"] = ed["title"]
            if ed.get("covers"):
                it["cover_i"] = next((c for c in ed["covers"] if isinstance(c, int) and c > 0), it["cover_i"])

        rows = _rows(items)

        # Libris: index title match, then ONE product-page read (cached) confirmed from schema.org.
        reads: dict[str, Future] = {}
        for row in rows[:LIBRIS_READS]:
            url = _libris_candidate(db, [row["title"]])
            row["libris_url"] = url
            if url and url not in reads and _libris_cached(db, url) is None:
                reads[url] = _shared(_SHOP_POOL, (str(db_path), "libris:" + url), _libris_task, db_path, url, fetcher)
        read: dict[str, tuple[str | None, str]] = {}
        for u, fut in reads.items():
            try:
                read[u] = fut.result(timeout=max(0.0, by - time.monotonic()))
            except Exception:
                pass  # not back by the deadline: cached when it is, shown by the next search

        results = []
        for row in rows:
            it = row["item"]
            isbn = row["isbn"]
            url = row.get("libris_url")
            libris_isbn = None
            if url:
                hit = read.get(url) or _libris_cached(db, url)
                if hit and hit[1] == "ok" and hit[0] in it["isbns"]:
                    libris_isbn = hit[0]
                    if not (asked and asked == isbn):
                        isbn = libris_isbn  # the edition a shop is confirmed to hold
            shops = []
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
        if not results and not online:
            return _index_fallback(db, query, asked)[:limit]  # the earlier answers' works were all filtered out
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
    # Elefant rows have no ISBN: a book finds them by exact slug title (api.offers.lookup_elefant_urls).
    db.execute("CREATE INDEX IF NOT EXISTS idx_books_shop_title ON books(shop, title)")
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



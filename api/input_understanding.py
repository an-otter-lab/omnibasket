"""Understand the one box: ISBN, link or free text -> a book (or a short candidate list).

Plain code decides everything it can. A model (Muse) is called only for
free text and for a foreign page that has no schema.org book-on-sale data,
always through meta_budget's guarded path. Muse never supplies an ISBN.
Nothing here writes to the index: a pasted shop lives only in the response.
"""

from __future__ import annotations

import html as _html
import re
import sys
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from api import muse_integration
from api.fetch_guard import FetchRefused, fetch
from api.schema_org import SchemaOrgData, extract_schema_org
from matching.isbn import isbn13_check_digit, normalize_isbn13

TZ = ZoneInfo("Europe/Bucharest")

NO_BOOK_MESSAGE = "I couldn't find a book on that page."
PASTE_LABEL = "new shop, not checked"
MUSE_EFFORT = "low"
MUSE_MAX_OUTPUT_TOKENS = 1500  # spike: at least 1200, or reasoning eats the budget
MAX_PAGE_CHARS = 12000
MAX_CANDIDATES = 5

# The spike's identifying prompt. title is the REAL title, not the typed words.
FREE_TEXT_PROMPT = (
    "You are the search box of a bookshop. The shopper typed a few words. Reply with strict JSON only, keys: "
    "title, author, language. title is the real title of the book you think they mean, or the words themselves if "
    "you cannot tell. author is its author or null. language is a two-letter code. Never invent an ISBN."
)
PAGE_PROMPT = (
    "You are reading a web page. Reply with strict JSON only, keys: title, author, language. "
    "Name the one book this page mentions or is about: title is its real title, author is its author or null, "
    "language is a two-letter code. If the page mentions no book, reply {\"title\": null, \"author\": null, \"language\": null}. "
    "Never invent an ISBN. Do not return prices or any other number."
)

_NUMBER_KEYS = ("price", "isbn", "isbn13", "isbn10", "year", "pages", "rating")
_URL_ISBN_RE = re.compile(r"(?<![\dA-Za-z])(\d{13}|\d{9}[\dXx])(?![\dA-Za-z])")
_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([0-9]{9}[0-9Xx])(?:[/?#]|$)")
_STRIP_BLOCK_RE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class ParseFailed(Exception):
    """The model reply was empty or not usable. Never turned into an empty query."""


# ---------------------------------------------------------------- ISBN


def _strip_isbn(raw: str) -> str:
    text = re.sub(r"(?i)^\s*isbn(?:-1[03])?\s*:?\s*", "", raw or "")
    return re.sub(r"[\s\-\u00ad\u2010-\u2014]", "", text).upper()


def _isbn10_ok(digits: str) -> bool:
    if len(digits) != 10 or not digits[:9].isdigit() or not (digits[9].isdigit() or digits[9] == "X"):
        return False
    total = sum((10 - i) * int(ch) for i, ch in enumerate(digits[:9]))
    total += 10 if digits[9] == "X" else int(digits[9])
    return total % 11 == 0


def isbn10_to_13(digits: str) -> str | None:
    digits = digits.upper()
    if not _isbn10_ok(digits):
        return None
    core = "978" + digits[:9]
    return core + isbn13_check_digit(core)


def to_isbn13(raw: str | None) -> str | None:
    """ISBN-10 or ISBN-13 with a valid check digit -> ISBN-13, else None."""
    if not raw:
        return None
    text = _strip_isbn(raw)
    if len(text) == 13:
        return normalize_isbn13(text)
    if len(text) == 10:
        return isbn10_to_13(text)
    return None


# ---------------------------------------------------------------- classify


def looks_like_url(raw: str) -> bool:
    text = (raw or "").strip()
    if not text or re.search(r"\s", text):
        return False
    low = text.lower()
    return low.startswith(("http://", "https://", "www."))


def with_scheme(raw: str) -> str:
    text = raw.strip()
    return text if text.lower().startswith(("http://", "https://")) else "https://" + text


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")


def indexed_shop_for(url: str) -> Any | None:
    """The indexed shop profile whose domain this link is on, or None."""
    from api.offers import _indexed_profiles

    host = host_of(url)
    for profile in _indexed_profiles():
        domain = (profile.domain or "").lower().removeprefix("www.")
        if host and (host == domain or host.endswith("." + domain)):
            return profile
    return None


# ---------------------------------------------------------------- index lookups (no network)


def _index_db(db_path: Path | str | None) -> Path:
    if db_path:
        return Path(db_path)
    from index.search import DB

    return Path(DB)


def _index_row_by_url(url: str, db_path: Path) -> dict | None:
    import sqlite3

    if not db_path.is_file():
        return None
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT title, author_hint, isbn FROM books WHERE url = ? LIMIT 1", (url,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {"title": row[0], "author": row[1], "isbn": row[2]} if row else None


def _index_row_by_isbn(isbn13: str, db_path: Path) -> dict | None:
    import sqlite3

    if not db_path.is_file():
        return None
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT title, author_hint FROM books WHERE isbn = ? ORDER BY length(coalesce(title,'')) DESC LIMIT 1",
            (isbn13,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {"title": row[0], "author": row[1]} if row else None


def _query_for_isbn(isbn13: str, db_path: Path) -> dict:
    row = _index_row_by_isbn(isbn13, db_path) or {}
    return {"title": row.get("title"), "author": row.get("author"), "language": None}


# ---------------------------------------------------------------- Muse (guarded path only)


def _text_of(payload: dict) -> str:
    return muse_integration._payload_text(payload).strip()


def call_muse_json(instructions: str, user_text: str, note: str, strict: bool = False) -> dict:
    """One Muse call through meta_budget.guarded_post. Empty or unparseable -> ParseFailed.

    strict=True (Ask): the whole reply must be one JSON object, optionally in one
    code fence. Prose around the JSON is ParseFailed, never searched for a lookalike.
    """
    body = {
        "model": muse_integration.meta_budget.MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": instructions + "\n\n" + user_text}],
            }
        ],
        "max_output_tokens": MUSE_MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": MUSE_EFFORT},
    }
    tokens_in = max(1, (len(instructions) + len(user_text)) // 3)
    estimate = muse_integration.meta_budget.compute_cost(tokens_in, MUSE_MAX_OUTPUT_TOKENS)
    payload, _row = muse_integration.meta_budget.guarded_post(body, estimate, note=note)
    text = _text_of(payload)
    if not text:
        raise ParseFailed("empty model output")
    if strict:
        parsed = _strict_json(text)
    else:
        parsed = muse_integration._extract_muse_json(text)
    if not isinstance(parsed, dict):
        raise ParseFailed("model output was not JSON")
    return parsed


def _strict_json(text: str):
    import json as _json

    body = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    try:
        return _json.loads(body)
    except ValueError:
        return None


def _clean_query(parsed: dict, page_text: str | None = None) -> dict | None:
    """title/author/language only. An ISBN or any number Muse returns is dropped.

    Numbers go through the same cross-check the offers path uses; with no
    structured price on a free-text query nothing numeric survives.
    """
    fields = muse_integration.adopt_muse_fields(parsed, page_text or "", SchemaOrgData())
    for key in list(fields):
        if key not in ("title", "author", "language"):
            fields.pop(key, None)
    title = fields.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    author = fields.get("author")
    language = fields.get("language")
    return {
        "title": title.strip(),
        "author": author.strip() if isinstance(author, str) and author.strip() else None,
        "language": language.strip().lower()[:2] if isinstance(language, str) and language.strip() else None,
    }


def parse_free_text(raw: str) -> dict:
    """Messy words -> {title, author, language}. Empty output is ParseFailed."""
    parsed = call_muse_json(FREE_TEXT_PROMPT, "SHOPPER: " + raw.strip(), note="input-free-text")
    query = _clean_query(parsed)
    if query is None:
        raise ParseFailed("model returned no title")
    return query


def book_on_page(page_text: str) -> dict | None:
    """The one Muse call for a foreign page: which book does it mention?"""
    parsed = call_muse_json(PAGE_PROMPT, "PAGE TEXT:\n" + page_text, note="input-page-book")
    return _clean_query(parsed, page_text)


# ---------------------------------------------------------------- page helpers


def visible_text(html: str) -> str:
    text = _STRIP_BLOCK_RE.sub(" ", html or "")
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:MAX_PAGE_CHARS]


def is_book_on_sale(schema: SchemaOrgData) -> bool:
    """Plain code: schema.org Product/Book with a price, a currency and a valid ISBN."""
    return bool(
        schema.price_cents is not None
        and schema.currency
        and schema.isbn13
        and normalize_isbn13(schema.isbn13)
    )


def _schema_title_author(schema: SchemaOrgData) -> tuple[str | None, str | None]:
    raw = schema.raw or {}
    name = raw.get("name")
    author = raw.get("author")
    if isinstance(author, dict):
        author = author.get("name")
    elif isinstance(author, list) and author:
        first = author[0]
        author = first.get("name") if isinstance(first, dict) else first
    return (
        name.strip() if isinstance(name, str) and name.strip() else None,
        author.strip() if isinstance(author, str) and author.strip() else None,
    )


# ---------------------------------------------------------------- BNR rates and the paste-only offer

_RATE_CACHE: dict[str, Any] = {}


def load_rates(today: date) -> Any | None:
    """Today's BNR table, or None when it cannot be had. One fetch per day."""
    key = today.isoformat()
    if key in _RATE_CACHE:
        return _RATE_CACHE[key]
    try:
        from matching import fx

        table = fx.parse_bnr_xml(fx.fetch_bnr_xml())
    except Exception:
        table = None
    _RATE_CACHE.clear()
    _RATE_CACHE[key] = table
    return table


def paste_offer(url: str, schema: SchemaOrgData, today: date, rates_loader: Callable[[date], Any] | None = None) -> dict:
    """An offer from a shop we do not index. Delivery is null, so its order is never ranked."""
    from matching import fx

    host = host_of(url)
    currency = (schema.currency or "").upper()
    row: dict[str, Any] = {
        "store_id": "paste:" + host,
        "label": host,
        "badge": PASTE_LABEL,
        "listing_url": url,
        "price_cents": schema.price_cents,
        "currency": currency,
        "ron_cents": None,
        "rate": None,
        "free_shipping_threshold_cents": None,
        "shipping_fee_cents": None,
        "per_order_fee_cents": None,
        "ranked": False,
        "not_ranked_reason": None,
    }
    conversion = None
    if currency == "RON":
        row["ron_cents"] = schema.price_cents
    else:
        rates = (rates_loader or load_rates)(today)
        if rates is None:
            row["not_ranked_reason"] = "no_bnr_rate"
        else:
            try:
                conversion = fx.convert_to_ron_cents(
                    schema.price_cents, currency, rates, today, allow_previous_banking_day=True
                )
            except (TypeError, ValueError):
                row["not_ranked_reason"] = "no_bnr_rate"
            else:
                if conversion.status != "converted":
                    row["not_ranked_reason"] = "no_bnr_rate"
                else:
                    row["ron_cents"] = conversion.ron_cents
                    disp = fx.rate_display(conversion)
                    if disp is not None:
                        row["rate"] = {
                            "date": disp.date, "units": disp.units, "currency": disp.currency, "rate": disp.rate,
                        }
    if row["not_ranked_reason"] is None:
        # Delivery rules are not read from a foreign page: they stay null.
        row["not_ranked_reason"] = "delivery_rules_not_read"
    return row


# ---------------------------------------------------------------- candidates


def candidates_for(query: dict, db_path: Path, opener=None, limit: int = MAX_CANDIDATES) -> list[dict]:
    from index.search import search

    text = " ".join(part for part in (query.get("title"), query.get("author")) if part)
    rows = search(text, limit=limit, db_path=db_path, opener=opener or _no_network_opener)
    out = []
    for row in rows:
        isbn = to_isbn13(row.get("isbn") or "")
        out.append(
            {
                "title": row.get("title"),
                "author": row.get("author"),
                "isbn13": isbn,
                "shops": [s.get("shop") for s in row.get("shops") or []],
            }
        )
    return out


def _no_network_opener(*_a, **_k):
    # search() may ask Open Library for an ISBN; the box does not wait for it.
    raise OSError("open library lookup skipped")


# ---------------------------------------------------------------- the entry point


def _events_url(isbn13: str, title: str | None) -> str:
    q = "/events?source=live&isbn13=" + isbn13
    if title:
        q += "&title=" + urllib.parse.quote(title)
    return q


def _base(kind: str) -> dict:
    return {
        "type": kind,
        "status": "resolved",
        "isbn13": None,
        "structured_query": None,
        "shop_context": {"shop_id": None, "product_url": None},
        "candidates": [],
        "paste_offer": None,
        "events_url": None,
        "message": None,
    }


def _resolved(kind: str, isbn13: str, query: dict, shop_id=None, product_url=None) -> dict:
    out = _base(kind)
    out.update(
        isbn13=isbn13,
        structured_query=query,
        shop_context={"shop_id": shop_id, "product_url": product_url},
        events_url=_events_url(isbn13, query.get("title")),
    )
    return out


def _failure(kind: str, status: str, message: str) -> dict:
    out = _base(kind)
    out.update(status=status, message=message)
    return out


class LimitTripped(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def understand(
    raw: str,
    *,
    ip: str = "unknown",
    limiter=None,
    index_db: Path | str | None = None,
    opener=None,
    rates_loader: Callable[[date], Any] | None = None,
    today: date | None = None,
) -> dict:
    """Turn what the shopper typed into a book. Raises LimitTripped on a paste limit."""
    text = (raw or "").strip()
    db = _index_db(index_db)
    today = today or datetime.now(TZ).date()
    if not text:
        return _failure("free_text", "not_found", "Type a title, an author, an ISBN or paste a link.")

    isbn = to_isbn13(text)
    if isbn:
        return _resolved("isbn", isbn, _query_for_isbn(isbn, db))

    if looks_like_url(text):
        return _understand_link(
            with_scheme(text), ip=ip, limiter=limiter, db=db, opener=opener, rates_loader=rates_loader, today=today
        )

    try:
        query = parse_free_text(text)
    except ParseFailed:
        return _failure("free_text", "parse_failed", "I couldn't read that. Try the title and the author.")
    except Exception:
        return _failure("free_text", "error", "I couldn't read that right now. Try an ISBN or paste a link.")
    cands = candidates_for(query, db, opener)
    out = _base("free_text")
    out["structured_query"] = query
    if len(cands) == 1 and cands[0]["isbn13"]:
        return _resolved("free_text", cands[0]["isbn13"], {**query, "title": cands[0]["title"] or query["title"]})
    out["status"] = "candidates" if cands else "not_found"
    out["candidates"] = cands
    if not cands:
        out["message"] = "I couldn't find that book in our shops."
    return out


def _understand_link(url, *, ip, limiter, db, opener, rates_loader, today) -> dict:
    shop = indexed_shop_for(url)
    if shop is not None:
        return _indexed_link(url, shop, db)

    host = host_of(url)
    if limiter is not None:
        reason = limiter.check(ip, host)
        if reason:
            raise LimitTripped(reason)
    try:
        page = fetch(url)
    except FetchRefused as exc:
        return _failure("link", "refused", "I couldn't open that link (" + exc.reason + ").")
    schema = extract_schema_org(page.text)
    if is_book_on_sale(schema):
        title, author = _schema_title_author(schema)
        query = {"title": title, "author": author, "language": None}
        out = _resolved("link", schema.isbn13, query, shop_id=None, product_url=page.final_url)
        out["paste_offer"] = paste_offer(page.final_url, schema, today, rates_loader)
        return out
    try:
        query = book_on_page(visible_text(page.text))
    except Exception:
        query = None
    cands = candidates_for(query, db, opener) if query else []
    if not cands:
        return _failure("link", "not_found", NO_BOOK_MESSAGE)
    out = _base("link")
    out["structured_query"] = query
    out["shop_context"] = {"shop_id": None, "product_url": page.final_url}
    if len(cands) == 1 and cands[0]["isbn13"]:
        return {**_resolved("link", cands[0]["isbn13"], query, product_url=page.final_url)}
    out["status"] = "candidates"
    out["candidates"] = cands
    return out


def _indexed_link(url: str, shop, db: Path) -> dict:
    """A link to one of the five shops: ISBN from our index, the URL, or the page (never Amazon)."""
    isbn = None
    row = _index_row_by_url(url, db)
    if row and row.get("isbn"):
        isbn = to_isbn13(row["isbn"])
    if isbn is None:
        for found in _URL_ISBN_RE.findall(urllib.parse.unquote(urllib.parse.urlsplit(url).path)):
            isbn = to_isbn13(found)
            if isbn:
                break
    if isbn is None and shop.id == "amazon_de":
        m = _ASIN_RE.search(urllib.parse.urlsplit(url).path)
        isbn = isbn10_to_13(m.group(1)) if m else None
    if isbn is None and shop.id != "amazon_de":
        # One guarded read of the shop's own product page.
        try:
            page = fetch(url)
        except FetchRefused as exc:
            return _failure("link", "refused", "I couldn't open that link (" + exc.reason + ").")
        isbn = extract_schema_org(page.text).isbn13
    if isbn is None:
        return _failure("link", "not_found", NO_BOOK_MESSAGE)
    query = _query_for_isbn(isbn, db)
    if row and not query.get("title"):
        query = {"title": row.get("title"), "author": row.get("author"), "language": None}
    return _resolved("link", isbn, query, shop_id=shop.id, product_url=url)

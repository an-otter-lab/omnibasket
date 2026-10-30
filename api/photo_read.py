"""Feature 2 backend: read a photographed list with Muse, match each line in the index.

Nothing here writes the image or logs its bytes. Muse returns title and author only;
an ISBN comes only from the index search (and its Open Library lookup), never from the model.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402
from api.muse_integration import _payload_text  # noqa: E402
from index.search import ensure_books_search, normalize, _filter_stop_words  # noqa: E402

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_LINES = 30
MAX_CANDIDATES = 5
QUERY_LIMIT = 200
MIN_WORD = 3
# A format variant may add only these words. Anything else is a different book.
FORMAT_WORDS = frozenset({
    "board", "book", "big", "deluxe", "edition", "special", "colour", "anniversary",
})
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}

PROMPT = (
    "You read a photographed or screenshot book list. Reply with strict JSON only, no prose, no code fences: "
    '{"lines": [{"title": "...", "author": "..."}]}. One entry per line of the list, in order. '
    "Copy only what is printed in the image; never complete, correct or guess a title or author. "
    "If an author is not printed on that line, use null. Never output an ISBN or any number that is not part of a title. "
    "If you cannot read any list, reply {\"lines\": []}."
)


class ReadFailed(Exception):
    pass


def sniff_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def parse_lines(text: str) -> list[dict]:
    """Strict parse. Anything off raises ReadFailed: no partial guess."""
    text = (text or "").strip()
    if not text:
        raise ReadFailed("empty")
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ReadFailed("not json") from None
    raw = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(raw, list) or not raw or len(raw) > MAX_LINES:
        raise ReadFailed("no lines")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ReadFailed("bad line")
        title, author = item.get("title"), item.get("author")
        if not isinstance(title, str) or not title.strip():
            raise ReadFailed("bad title")
        if author is not None and not isinstance(author, str):
            raise ReadFailed("bad author")
        out.append({"title": title.strip(), "author": (author or "").strip() or None})
    return out


def read_list(data: bytes, mime: str) -> list[dict]:
    """One guarded Muse call. Any failure (budget, network, empty, unparseable) is ReadFailed."""
    url = "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())
    body = {
        "model": meta_budget.MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": url},
                ],
            }
        ],
        "max_output_tokens": 1500,
        "reasoning": {"effort": "low"},
    }
    estimate = meta_budget.compute_cost(2500, 1500)
    try:
        payload, _row = meta_budget.guarded_post(body, estimate, note="photo-read")
    except Exception:  # budget refusal, HTTP or network error: same outcome, no detail leaked
        raise ReadFailed("call failed") from None
    return parse_lines(_payload_text(payload))


def title_words(value: str | None) -> list[str]:
    """Title words used for matching: no stop words, no words under 3 letters.

    Apostrophes split the way the FTS tokenizer does, so "Charlotte's" is "charlotte".
    """
    raw = normalize(value) if value else ""
    tokens = re.findall(r"[a-z0-9]+", raw)
    return [t for t in _filter_stop_words(tokens) if len(t) >= MIN_WORD]


def fts_and_query(words: list[str]) -> str:
    """FTS5 AND of whole tokens. No OR and no prefix, so a common word cannot scan the catalogue."""
    return " ".join('"%s"' % w for w in words)


def _cover(isbn: str) -> str:
    return "https://covers.openlibrary.org/b/isbn/%s-M.jpg" % urllib.parse.quote(isbn)


def _edition_label(want: list[str], have: list[str]) -> str | None:
    """None when this title is not the read title or a format variant of it.

    Empty string means an exact word match. Any other string is the edition label.
    """
    from collections import Counter

    spare = Counter(want)
    extras: list[str] = []
    for word in have:
        if spare[word]:
            spare[word] -= 1
        else:
            extras.append(word)
    if any(spare.values()):
        return None
    if not extras:
        return ""
    if any(word not in FORMAT_WORDS for word in extras):
        return None
    return " ".join(extras)


def query_line(words: list[str], db_path) -> list[sqlite3.Row]:
    """One query: every title word, ISBN only, at most 200 rows."""
    if not words or not Path(db_path).is_file():
        return []
    with sqlite3.connect(str(db_path)) as db:
        db.row_factory = sqlite3.Row
        ensure_books_search(db)
        try:
            return db.execute(
                """
                SELECT b.title AS title, b.author_hint AS author, b.isbn AS isbn
                FROM books_search s
                JOIN books b ON b.rowid = s.rowid
                WHERE books_search MATCH ? AND b.isbn IS NOT NULL AND b.isbn != ''
                LIMIT ?
                """,
                (fts_and_query(words), QUERY_LIMIT),
            ).fetchall()
        except sqlite3.OperationalError:
            return []


def match_line(line: dict, db_path, opener=None) -> dict:
    """Match one read line. The author is ignored; an ISBN comes only from the index.

    One exact ISBN is matched. More than one exact ISBN is ambiguous. No exact title
    but one format edition is matched and labelled with that edition. More than one
    edition is ambiguous. Anything else, including a spin-off, is not a candidate.
    """
    del opener  # matching never calls out; the index already holds the ISBN
    want = title_words(line.get("title"))
    base = {"read_title": line["title"], "read_author": line.get("author")}
    exact: dict[str, dict] = {}
    editions: dict[str, dict] = {}
    qualifiers: dict[str, tuple[int, dict]] = {}
    for row in query_line(want, db_path):
        have = title_words(row["title"])
        label = _edition_label(want, have)
        fallback = None
        if label is None:
            remaining = list(want)
            extras = []
            for w in have:
                if w in remaining:
                    remaining.remove(w)
                else:
                    extras.append(w)
            nonformat = [w for w in extras if w not in FORMAT_WORDS]
            if (want and have and have[0] == want[0] and not remaining and len(nonformat) <= 2
                    and (len(have) == len(want) or any(w in FORMAT_WORDS for w in have[len(want):]))
                    and all(w in FORMAT_WORDS for w in have[len(want) + len(nonformat):])):
                fallback = (len(nonformat), " ".join(nonformat) or "format variant")
        isbn = row["isbn"]
        item = {
            "title": row["title"],
            "author": row["author"] or None,
            "isbn": isbn,
            "cover_url": _cover(isbn),
        }
        if label == "":
            exact.setdefault(isbn, item)
        elif label is not None:
            item["edition"] = label
            editions.setdefault(isbn, item)
        else:
            if fallback is not None:
                item["edition"] = fallback[1]
                qualifiers[isbn] = (fallback[0], item)

    if len(exact) == 1:
        return {**base, "status": "matched", "candidate": next(iter(exact.values()))}
    if len(exact) > 1:
        picks = [exact[k] for k in sorted(exact)][:MAX_CANDIDATES]
        return {**base, "status": "ambiguous", "candidates": picks}
    if len(editions) == 1:
        return {**base, "status": "matched", "candidate": next(iter(editions.values()))}
    if len(editions) > 1:
        picks = [editions[k] for k in sorted(editions)][:MAX_CANDIDATES]
        return {**base, "status": "ambiguous", "candidates": picks}
    if qualifiers:
        picks = [qualifiers[k][1] for k in sorted(qualifiers, key=lambda k: (qualifiers[k][0], k))][:MAX_CANDIDATES]
        return {**base, "status": "ambiguous", "candidates": picks}
    return {**base, "status": "not_found"}


def read_and_match(data: bytes, mime: str, db_path, opener=None) -> dict:
    try:
        lines = read_list(data, mime)
    except ReadFailed:
        return {"error": "read_failed"}
    return {"lines": [match_line(l, db_path, opener) for l in lines]}

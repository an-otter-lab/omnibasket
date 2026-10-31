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


def _is_real_title(title: str | None) -> bool:
    """A title a person cased. Both shops' index rows are slugs: every word lowercase."""
    return any(ch.isupper() for ch in title or "")


def _index_picks(items: list[dict]) -> list[dict]:
    """Index candidates the shopper may see: real book records, never a shop slug."""
    return [it for it in items if _is_real_title(it.get("title"))][:MAX_CANDIDATES]


def _matched_index(item: dict, base: dict, line: dict, db_path, opener, specials: list[dict] = ()) -> dict:
    """A unique index hit, shown as the real work or not matched as that ISBN.

    A shop row is only evidence that a shop has a printing: its own title is a slug. The
    catalogue's record for the ISBN names the work; when it names a different one (the
    "the very hungry caterpillar s" row is the 123 board book, clipped in the slug), the
    ISBN is rejected and the read line is resolved from its own title instead.
    """
    shown = _show(item, line, db_path, opener)
    plain_extra: list[dict] = []
    if shown is not None and not _special_label(line.get("title"), [shown.get("title")]):
        if shown.get("isbn") in _listed(db_path, [shown.get("isbn")]):
            return {**base, "status": "matched", "candidate": shown}
        plain_extra = [shown]  # no shop lists it: a choice, not a match (S18 review)
    elif shown is not None:
        specials = [{**shown, "edition": _special_label(line.get("title"), [shown.get("title")])}, *specials]
    return resolve_online(line, base, db_path, opener, specials, plain_extra)


def match_line(line: dict, db_path, opener=None) -> dict:
    """Match one read line. An ISBN comes only from the index; the author only labels it.

    One exact ISBN is matched. More than one exact ISBN is ambiguous. No exact title
    but one format edition is matched and labelled with that edition. More than one
    edition is ambiguous. Anything else, including a spin-off, is not a candidate.
    A shop slug is never shown as a title: an index row without a cased title is
    labelled from the catalogue's record for its ISBN, or the line is not matched.
    """
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

    # S18: a special format (big book, pop-up, deluxe, gift, colour, board book, box set) is
    # only matched when the line asks for it; otherwise it is offered as a choice and the
    # plain printing is ranked first.
    shop = _shop_titles(db_path, list(exact) + list(editions) + list(qualifiers))
    specials: dict[str, dict] = {}
    for pool in (exact, editions):
        for isbn in list(pool):
            label = _special_label(line.get("title"), [pool[isbn]["title"]] + shop.get(isbn, []))
            if label:
                ed = pool[isbn].get("edition")
                specials.setdefault(isbn, {**pool[isbn], "edition": ed if ed and label in ed else label})
                del pool[isbn]
    special_list = [specials[k] for k in sorted(specials)]

    if len(exact) == 1:
        return _matched_index(next(iter(exact.values())), base, line, db_path, opener, special_list)
    if not exact and len(editions) == 1:
        return _matched_index(next(iter(editions.values())), base, line, db_path, opener, special_list)
    listed_exact = sorted(_listed(db_path, list(exact)))
    if len(exact) > 1 and len(listed_exact) == 1:
        # S18 review: of several plain printings, the one a shop lists is the match.
        return _matched_index(exact[listed_exact[0]], base, line, db_path, opener, special_list)
    exact_picks = _index_picks([exact[k] for k in sorted(exact)])
    if exact_picks:
        return {**base, "status": "ambiguous", "candidates": exact_picks}
    edition_picks = _index_picks([editions[k] for k in sorted(editions)])
    if edition_picks:
        return {**base, "status": "ambiguous", "candidates": edition_picks}
    if special_list:
        return resolve_online(line, base, db_path, opener, special_list)
    qualifier_rank = {
        k: (bool(_special_label(line.get("title"), [qualifiers[k][1]["title"]] + shop.get(k, []))), qualifiers[k][0], k)
        for k in qualifiers
    }
    qualifier_picks = _index_picks([qualifiers[k][1] for k in sorted(qualifiers, key=qualifier_rank.get)])
    if qualifier_picks:
        return {**base, "status": "ambiguous", "candidates": qualifier_picks}
    # Shop slugs only: a special printing among them is still a choice when no plain one is listed.
    special_q = [{**qualifiers[k][1], "edition": _special_label(line.get("title"), [qualifiers[k][1]["title"]] + shop.get(k, []))}
                 for k in sorted(qualifiers, key=qualifier_rank.get) if qualifier_rank[k][0]]
    return resolve_online(line, base, db_path, opener, special_q)


def _shop_titles(db_path, isbns: list[str]) -> dict[str, list[str]]:
    """isbn -> every shop index title for it: evidence that a printing is a special format."""
    found: dict[str, list[str]] = {}
    isbns = [i for i in dict.fromkeys(isbns) if i]
    if not isbns or not Path(db_path).is_file():
        return found
    try:
        with sqlite3.connect(str(db_path)) as db:
            marks = ",".join("?" * len(isbns))
            for isbn, title in db.execute(
                f"SELECT isbn, title FROM books WHERE isbn IN ({marks}) AND title IS NOT NULL AND title != ''",
                isbns,
            ):
                found.setdefault(isbn, []).append(title)
    except sqlite3.Error:
        return {}
    return found


def _listed(db_path, isbns: list[str]) -> set[str]:
    """ISBNs a live-read shop lists: an index product row (never a search URL) at a shop the
    live reads fetch. Amazon.de rows are captures, never read, so they are not a listing."""
    from api.offers import _searchish

    isbns = [i for i in dict.fromkeys(isbns) if i]
    if not isbns or not Path(db_path).is_file():
        return set()
    try:
        with sqlite3.connect(str(db_path)) as db:
            marks = ",".join("?" * len(isbns))
            rows = db.execute(
                f"SELECT isbn, url FROM books WHERE isbn IN ({marks}) AND shop != 'amazon_de'", isbns
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {isbn for isbn, url in rows if url and not _searchish(url)}


def _title_listed(line: dict, db_path) -> bool:
    """A shop row with the line's title and author but no ISBN: the live read can still find the
    work there as another printing (offers.lookup_title_url, then a strong page match)."""
    from api.offers import default_live_stores, lookup_title_url

    if not line.get("title") or not line.get("author") or not Path(db_path).is_file():
        return False
    try:
        return any(lookup_title_url(s, line["title"], line["author"], db_path=Path(db_path)) for s in default_live_stores())
    except Exception:  # a broken profile or index is not evidence of a listing
        return False


def _special_label(read_title: str | None, titles: list[str | None]) -> str:
    """The special formats these titles name and the read line does not ask for ("" = plain)."""
    from matching.ranking import EDITION_MARKERS, has_marker

    hits: list[str] = []
    for marker in EDITION_MARKERS:
        if has_marker(read_title, (marker,)):
            continue  # the line asks for this format
        if any(has_marker(t, (marker,)) for t in titles if t):
            hits.append(marker)
    # "giant board book" already says "board book".
    hits = [h for h in hits if not any(h != o and (" " + h + " ") in (" " + o + " ") for o in hits)]
    return ", ".join(hits)


ONLINE_LIMIT = 8
ONLINE_SIMILARITY = 0.85


def online_lookup(line: dict, db_path, opener=None, fetcher=None, isbn: str | None = None) -> list[dict]:
    """Resolve a read line through the same Open Library search the app uses for typed input.

    Returns candidate dicts (title, author, isbn, cover_url) whose title and author agree
    with the read line. An unreachable search is an empty answer, never an error.
    With `isbn`, the catalogue is asked for that edition only: its own title and author
    are the book's, not the shop index's lowercase slug.
    """
    from difflib import SequenceMatcher

    from index.search import search
    from api.title_match import core_title, fold, surname

    title = line.get("title") or ""
    author = line.get("author") or ""
    want = core_title(title)
    last = surname(author)
    if not want:
        return []
    found: dict[str, dict] = {}
    queries = [isbn] if isbn else ([" ".join([title, author]).strip(), title] if author else [title])
    for query in queries:
        try:
            results = search(query, limit=ONLINE_LIMIT, db_path=db_path, opener=opener, fetcher=fetcher)
        except Exception:  # SearchUnavailable, network, bad db: nothing resolved
            results = []
        for res in results:
            isbn = res.get("isbn")
            if not isbn or isbn in found:
                continue
            have = core_title(res.get("title"))
            if not have or SequenceMatcher(None, want, have).ratio() < ONLINE_SIMILARITY:
                continue
            if not _same_work(title, res.get("title")):
                continue  # a spin-off, not this printed book
            if sorted(re.findall(r"\d+", want)) != sorted(re.findall(r"\d+", have)):
                continue
            if last and res.get("author") and last not in fold(res["author"]).split():
                continue
            found[isbn] = {
                "title": res["title"],
                "author": res.get("author") or (line.get("author") or None),
                "isbn": isbn,
                "cover_url": res.get("cover_url") or _cover(isbn),
                "_exact": want == have,
                "_shops": len(res.get("shops") or []),
            }
        if found:
            break
    if any(c["_exact"] for c in found.values()):
        # The work whose title is the printed one: a spin-off beside it is a different book
        # ("the very hungry caterpillar's abc" is not "the very hungry caterpillar").
        found = {k: v for k, v in found.items() if v["_exact"]}
    ranked = sorted(found.values(), key=lambda c: (not c["_exact"], -c["_shops"]))
    for c in ranked:
        c.pop("_exact"), c.pop("_shops")
    return ranked


def _same_work(read_title: str | None, record_title: str | None) -> bool:
    """The catalogue's record is this line's book: the same title words, or a format variant.

    "The very hungry caterpillar's abc" adds a word that names another book, so it is not
    "The Very Hungry Caterpillar" even though the catalogue returns it for a near title.
    """
    from api.title_match import core_title

    return _edition_label(title_words(core_title(read_title)),
                          title_words(core_title(record_title))) is not None


def _canonical(item: dict, line: dict, db_path, opener) -> dict | None:
    """The catalogue's record for this ISBN when it is the printed work, else None (R13).

    The local index holds shop slugs ("the very hungry caterpillar s", no author); what
    the shopper is buying has a real title and an author. An ISBN the catalogue does not
    confirm as this work is a different book and must not be shown under this title. The
    edition label stays, so a special edition is still shown as one.
    """
    isbn = item.get("isbn")
    if not isbn:
        return None
    for cand in online_lookup(line, db_path, opener, isbn=isbn):
        if cand.get("isbn") != isbn or not cand.get("title"):
            continue
        if not _same_work(line.get("title"), cand["title"]):
            continue  # the same words, but a record of another book
        return {
            **item,
            "title": cand["title"],
            "author": cand.get("author") or item.get("author") or (line.get("author") or None),
        }
    return None


def _show(item: dict, line: dict, db_path, opener) -> dict | None:
    """An index row as it may be shown: its own record when that is a real book record,
    else the catalogue's record for its ISBN. None when neither exists."""
    if _is_real_title(item.get("title")):
        return {**item, "author": item.get("author") or (line.get("author") or None)}
    return _canonical(item, line, db_path, opener)


def resolve_online(line: dict, base: dict, db_path, opener=None, specials: list[dict] = (),
                   plain_extra: list[dict] = ()) -> dict:
    """not_found fallback: one plain candidate is matched, several are for the shopper to pick.

    S18: a special format (by its catalogue title or any shop title for its ISBN) is never
    matched for a line that does not ask for it. It is offered as a choice after the plain
    printings, with the index's special editions of the line (`specials`) beside it.

    S18 review: only a plain printing a shop lists (`_listed`) is matched, and a listed one
    is preferred over unlisted ones. When no plain printing is listed, the line is a choice
    (plain and special printings, listed first in each group) instead of a match that would
    leave the basket with no ranked answer. `plain_extra`: an index printing already shown.
    """
    cands = online_lookup(line, db_path, opener)
    shop = _shop_titles(db_path, [c["isbn"] for c in cands])
    plain: list[dict] = []
    special: list[dict] = []
    for c in cands:
        label = _special_label(line.get("title"), [c.get("title")] + shop.get(c["isbn"], []))
        if label:
            special.append({**c, "edition": label})
        else:
            plain.append(c)
    seen = {c["isbn"] for c in cands}
    for item in plain_extra:
        if item.get("isbn") and item["isbn"] not in seen:
            seen.add(item["isbn"])
            plain.insert(0, item)
    listed = _listed(db_path, [c.get("isbn") for c in plain + special + list(specials)])
    plain.sort(key=lambda c: c.get("isbn") not in listed)  # stable: listed first
    plain_listed = [c for c in plain if c.get("isbn") in listed]
    if len(plain_listed) == 1:
        return {**base, "status": "matched", "candidate": plain_listed[0]}
    if not plain_listed and len(plain) == 1 and _title_listed(line, db_path):
        return {**base, "status": "matched", "candidate": plain[0]}
    # A choice: the index's special printings beside the catalogue's, listed ones first. Each is
    # shown under its catalogue record (never a shop slug), so only the few that can be offered
    # are looked up.
    room = MAX_CANDIDATES - len(plain)
    for item in sorted(specials, key=lambda c: c.get("isbn") not in listed):
        if room <= sum(1 for c in special if c.get("isbn") in listed) or item.get("isbn") in seen:
            continue
        shown = _show(item, line, db_path, opener)
        if shown is not None:
            seen.add(item["isbn"])
            special.append({**shown, "edition": item.get("edition") or "special format"})
    special.sort(key=lambda c: c.get("isbn") not in listed)
    if not plain and not special:
        return {**base, "status": "not_found"}
    return {**base, "status": "ambiguous", "candidates": (plain + special)[:MAX_CANDIDATES]}


def read_and_match(data: bytes, mime: str, db_path, opener=None) -> dict:
    try:
        lines = read_list(data, mime)
    except ReadFailed:
        return {"error": "read_failed"}
    return {"lines": [match_line(l, db_path, opener) for l in lines]}

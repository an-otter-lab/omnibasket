"""Feature 2 backend: read a photographed list with Muse, match each line in the index.

Nothing here writes the image or logs its bytes. Muse returns title and author only;
an ISBN comes only from the index search (and its Open Library lookup), never from the model.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget  # noqa: E402
from api.muse_integration import _payload_text  # noqa: E402
from index.search import normalize, search, _filter_stop_words  # noqa: E402

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_LINES = 30
MAX_CANDIDATES = 5
SEARCH_LIMIT = 50
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


def _tokens(value: str | None) -> list[str]:
    return _filter_stop_words(normalize(value).split()) if value else []


def _is_candidate(line: dict, hit: dict) -> bool:
    if not hit.get("isbn"):
        return False
    want, have = _tokens(line["title"]), _tokens(hit.get("title"))
    if not want or not have:
        return False
    short, long_ = sorted((want, have), key=len)
    # same title, or the same title plus a short subtitle/series tag; not a different book that merely mentions it
    if long_[: len(short)] != short or len(long_) - len(short) > 3:
        return False
    if line.get("author") and hit.get("author"):
        if not set(_tokens(line["author"])) & set(_tokens(hit["author"])):
            return False
    return True


def match_line(line: dict, db_path, opener=None) -> dict:
    # The index search ORs prefix tokens and ranks in Python, so common words ("web", "white", "'s")
    # make it scan a large part of the catalogue. Ask it for the most distinctive (longest) title word
    # only; the full title and the author are then checked here, in _is_candidate.
    words = _filter_stop_words(normalize(line["title"]).split())
    query = max(words, key=len) if words else line["title"]
    hits = search(query, limit=SEARCH_LIMIT, db_path=db_path, opener=opener) if opener else search(query, limit=SEARCH_LIMIT, db_path=db_path)
    cands = [h for h in hits if _is_candidate(line, h)]
    seen, uniq = set(), []
    for h in cands:
        if h["isbn"] not in seen:
            seen.add(h["isbn"])
            uniq.append(h)

    def pick(h: dict) -> dict:
        # cover_url is the Open Library reference built from the ISBN; shop images are never used
        return {"title": h["title"], "author": h.get("author"), "isbn": h["isbn"], "cover_url": h["cover_url"]}

    base = {"read_title": line["title"], "read_author": line.get("author")}
    if not uniq:
        return {**base, "status": "not_found"}
    if len(uniq) == 1:
        return {**base, "status": "matched", "candidate": pick(uniq[0])}
    return {**base, "status": "ambiguous", "candidates": [pick(h) for h in uniq[:MAX_CANDIDATES]]}


def read_and_match(data: bytes, mime: str, db_path, opener=None) -> dict:
    try:
        lines = read_list(data, mime)
    except ReadFailed:
        return {"error": "read_failed"}
    return {"lines": [match_line(l, db_path, opener) for l in lines]}

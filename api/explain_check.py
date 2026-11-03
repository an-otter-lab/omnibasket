"""Check a "why this split" paragraph against the /solve payload.

Muse writes the paragraph. This module never calls a model. Every number
and every shop name has to be in the payload, or the paragraph is dropped
and the template sentence is shown instead.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

# Shop names the paragraph may use, including a shop that is not in this basket.
# A mention still fails unless that shop is in the payload.
_KNOWN_SHOPS = ("libris", "bookzone", "emag", "amazon_de", "books_express", "elefant")

_DISPLAY = {
    "libris": "Libris",
    "bookzone": "Bookzone",
    "emag": "eMAG",
    "amazon_de": "Amazon.de",
    "books_express": "Books-Express",
    "elefant": "Elefant",
}

# Spellings that do not fall out of the store id, including the shop's own domain.
_EXTRA_ALIASES = {
    "amazon_de": ("Amazon", "Amazon.de", "Amazon de"),
    "books_express": ("Books-Express", "Books Express", "books-express.ro"),
    "emag": ("eMAG", "e-mag", "emag.ro"),
    "libris": ("libris.ro",),
    "bookzone": ("bookzone.ro",),
    "elefant": ("elefant.ro",),
}

# amazon.de is the shop. amazon.com and any other host is a different shop.
_AMAZON_HOST_RE = re.compile(r"(?<![a-z0-9])amazon(?:\.[a-z0-9]+)+(?![a-z0-9])")

_STORE_KEYS = {
    "store_id",
    "best_store_id",
    "assigned_store_id",
    "from_store_id",
    "to_store_id",
    "cheapest_store_id",
}
_STORE_LIST_KEYS = {"selected_store_ids", "store_ids", "romanian_stores"}

# Totals a paragraph may subtract. Item prices and fees are amounts on
# their own; they are not totals, so two prices do not invent a saving.
_TOTAL_KEYS = {
    "total_cents",
    "order_total_cents",
    "books_subtotal_cents",
    "store_total_cents",
    "unpinned_total_cents",
    "items_cents",
    "without_membership_total_cents",
    "with_membership_total_cents",
}

_WORD_COUNTS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "unu": 1,
    "una": 1,
    "doi": 2,
    "doua": 2,
    "trei": 3,
    "patru": 4,
    "cinci": 5,
    "sase": 6,
    "sapte": 7,
    "opt": 8,
    "noua": 9,
    "zece": 10,
}

# "o" and "un" are also articles. They count only in front of a count noun, and never in
# front of a shop noun: RO "un magazin" is "a shop", not a shop count (P3).
_ARTICLE_COUNTS = {"o": 1, "un": 1}

_COUNT_NOUNS = {
    "book": "books",
    "books": "books",
    "title": "books",
    "titles": "books",
    "carte": "books",
    "carti": "books",
    "titlu": "books",
    "titluri": "books",
    "order": "orders",
    "orders": "orders",
    "comanda": "orders",
    "comenzi": "orders",
    "shop": "shops",
    "shops": "shops",
    "store": "shops",
    "stores": "shops",
    "magazin": "shops",
    "magazine": "shops",
}

_NOUN_RE = re.compile(
    r"\s+(" + "|".join(sorted(_COUNT_NOUNS, key=len, reverse=True)) + r")(?![a-z0-9])"
)
_CURRENCY_RE = re.compile(r"\s*(lei|ron|eur|euro|€)(?![a-z0-9])", re.IGNORECASE)
_CURRENCY_BEFORE_RE = re.compile(r"(?<![a-z0-9])(?:lei|ron|eur|euro|€)\s*$")
_PERCENT_RE = re.compile(r"\s*(%|percent\b|procent\b|la suta\b)")
_NUMBER_RE = re.compile(
    r"(?<![a-z0-9])("
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:[.,]\d+)?"
    r")(?![a-z0-9])"
)

_CHAR_FOLD = str.maketrans(
    {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
        "á": "a",
        "à": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ö": "o",
        "ü": "u",
    }
)


@dataclass(frozen=True)
class CheckFailure:
    """One claim the paragraph made that the payload does not support."""

    span: str
    reason: str
    start: int
    end: int


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    failures: tuple[CheckFailure, ...]
    fallback_ro: str
    fallback_en: str


@dataclass(frozen=True)
class _Facts:
    money_cents: frozenset[int]
    percents: frozenset[Decimal]
    book_counts: frozenset[int]
    order_counts: frozenset[int]
    shop_counts: frozenset[int]
    store_ids: frozenset[str]


@dataclass(frozen=True)
class _Hit:
    kind: str
    start: int
    end: int
    span: str
    cents: int | None = None
    count: int | None = None
    count_kind: str | None = None
    percent: Decimal | None = None
    store_ids: frozenset[str] = frozenset()


def check_explanation(paragraph: str, payload: dict) -> CheckResult:
    """Drop the paragraph unless every number and shop name is in the payload.

    Money has to equal an amount the payload states, or the exact difference
    of two of its totals. 515,2 does not stand in for 515,16. Counts have to
    equal a book, order or shop count. A shop name has to be one of the shops
    in the payload. The fallback sentences are built from the payload either way.
    """

    facts = _facts(payload)
    failures = _failures(paragraph or "", facts)
    fallback_ro, fallback_en = fallback_sentences(payload)
    return CheckResult(
        ok=not failures,
        failures=tuple(failures),
        fallback_ro=fallback_ro,
        fallback_en=fallback_en,
    )


def one_order_of(payload) -> dict | None:
    """The one-order option. The UI posts it as `one_order` (live /why payloads); /solve's own
    key is `one_parcel`, kept as a fallback."""
    if not isinstance(payload, dict):
        return None
    for key in ("one_order", "one_parcel"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    return None


def fallback_sentences(payload: dict) -> tuple[str, str]:
    """The plain sentence shown when the paragraph is dropped. No model."""

    cheapest = payload.get("cheapest") if isinstance(payload.get("cheapest"), dict) else {}
    one = one_order_of(payload) or {}
    answer = one.get("answer") if isinstance(one.get("answer"), dict) else {}
    total = _int_or_none(cheapest.get("total_cents"))
    if total is None:
        total = _int_or_none(payload.get("total_cents"))
    one_total = _int_or_none(answer.get("total_cents"))
    if total is None:
        return (
            "Coșul acesta nu are o împărțire cu preț.",
            "This basket has no priced split.",
        )

    currency = cheapest.get("currency") or payload.get("currency") or "RON"
    unit = _unit(currency)
    orders = cheapest.get("orders") if isinstance(cheapest.get("orders"), list) else []
    names = [display_name(o["store_id"]) for o in orders if isinstance(o, dict) and o.get("store_id")]
    count = cheapest.get("order_count")
    if not isinstance(count, int) or isinstance(count, bool):
        count = len(orders)
    ro_shops = _join(names, "și")
    en_shops = _join(names, "and")
    ro_from = f", de la {ro_shops}" if ro_shops else ""
    en_from = f", from {en_shops}" if en_shops else ""
    if count == 1:
        # P3: one order is not a split, so say so instead of "în 1 comandă".
        ro_at = f" la {ro_shops}" if ro_shops else ""
        en_at = f" at {en_shops}" if en_shops else ""
        ro = f"Cea mai ieftină variantă este o singură comandă{ro_at}: {_money(total)}\u00a0{unit}."
        en = f"The cheapest option is one order{en_at}: {_money(total)}\u00a0{unit}."
    else:
        ro = (
            f"Cea mai ieftină împărțire este {_money(total)}\u00a0{unit} "
            f"în {count} {_orders_ro(count)}{ro_from}."
        )
        en = (
            f"The cheapest split is {_money(total)}\u00a0{unit} "
            f"in {count} {_orders_en(count)}{en_from}."
        )
    one_store = one.get("best_store_id")
    if one_total is None or not isinstance(one_store, str) or not one_store:
        return ro, en
    shop = display_name(one_store)
    delta = one_total - total
    if delta == 0 and count == 1:
        pass  # the first sentence already is that one order
    elif delta == 0:
        ro += f" O comandă la {shop} are același total."
        en += f" One order at {shop} is the same total."
    elif delta > 0:
        ro += (
            f" O comandă la {shop} este {_money(one_total)}\u00a0{unit}, "
            f"cu {_money(delta)}\u00a0{unit} mai mult."
        )
        en += (
            f" One order at {shop} is {_money(one_total)}\u00a0{unit}, "
            f"{_money(delta)}\u00a0{unit} more."
        )
    else:
        less = -delta
        ro += (
            f" O comandă la {shop} este {_money(one_total)}\u00a0{unit}, "
            f"cu {_money(less)}\u00a0{unit} mai puțin."
        )
        en += (
            f" One order at {shop} is {_money(one_total)}\u00a0{unit}, "
            f"{_money(less)}\u00a0{unit} less."
        )
    return ro, en


def display_name(store_id: str) -> str:
    known = _DISPLAY.get(store_id) or _DISPLAY.get(_norm_id(store_id))
    if known:
        return known
    return store_id.replace("_", " ").replace("-", " ").title()


def _failures(paragraph: str, facts: _Facts) -> list[CheckFailure]:
    folded, index = _fold_map(paragraph)
    hits = _number_hits(paragraph, folded, index) + _shop_hits(paragraph, folded, index, facts)
    hits.sort(key=lambda hit: (hit.start, hit.end))
    failures = []
    for hit in hits:
        reason = _judge(hit, facts)
        if reason is None:
            continue
        failures.append(CheckFailure(span=hit.span, reason=reason, start=hit.start, end=hit.end))
    return failures


def _judge(hit: _Hit, facts: _Facts) -> str | None:
    if hit.kind == "shop":
        if hit.store_ids & facts.store_ids:
            return None
        return f"{hit.span} is not a shop in the payload"
    if hit.kind == "percent":
        if hit.percent in facts.percents:
            return None
        return f"{hit.span} is not a percentage in the payload"
    if hit.kind == "money":
        if hit.cents is not None and hit.cents in facts.money_cents:
            return None
        shown = _shown_lei(hit.cents)
        return f"{hit.span} is {shown}, which is not an amount in the payload"
    if hit.kind == "count":
        if hit.count is not None and _count_ok(hit.count, hit.count_kind, facts):
            return None
        kind = hit.count_kind or "count"
        return f"{hit.span} is not a {kind} count in the payload"
    # A bare integer may be whole lei (135 for 135,00) or a count. Not both required.
    whole = None if hit.cents is None else hit.cents
    money_ok = whole is not None and whole in facts.money_cents
    count_ok = hit.count is not None and _count_ok(hit.count, "any", facts)
    if money_ok or count_ok:
        return None
    return f"{hit.span} is not an amount or a count in the payload"


def _count_ok(count: int, kind: str | None, facts: _Facts) -> bool:
    if kind == "books":
        return count in facts.book_counts
    if kind == "orders":
        return count in facts.order_counts
    if kind == "shops":
        return count in facts.shop_counts
    return count in facts.book_counts or count in facts.order_counts or count in facts.shop_counts


def _number_hits(paragraph: str, folded: str, index: list[int]) -> list[_Hit]:
    hits = []
    occupied: list[tuple[int, int]] = []
    for match in _NUMBER_RE.finditer(folded):
        value = _parse_localized(match.group(1))
        if value is None:
            continue
        kind, end, count_kind = _classify(folded, match.start(), match.end(), value)
        start, stop = _original(index, match.start(), end)
        span = paragraph[start:stop]
        hits.append(_hit_from_value(kind, start, stop, span, value, count_kind))
        occupied.append((match.start(), match.end()))
    hits.extend(_word_hits(paragraph, folded, index, occupied))
    return hits


def _hit_from_value(kind: str, start: int, end: int, span: str, value: Decimal, count_kind: str | None) -> _Hit:
    if kind == "percent":
        return _Hit(kind="percent", start=start, end=end, span=span, percent=value)
    if kind == "money":
        return _Hit(kind="money", start=start, end=end, span=span, cents=_to_cents(value))
    if kind == "count":
        count = int(value) if value == value.to_integral_value() and value >= 0 else None
        return _Hit(kind="count", start=start, end=end, span=span, count=count, count_kind=count_kind)
    # Bare integer. Whole lei is N.00, never a truncated 515 standing in for 515,16.
    cents = None
    count = None
    if value == value.to_integral_value() and value >= 0:
        count = int(value)
        cents = count * 100
    return _Hit(kind="bare", start=start, end=end, span=span, cents=cents, count=count)


def _classify(folded: str, start: int, end: int, value: Decimal) -> tuple[str, int, str | None]:
    after = folded[end:]
    before = folded[max(0, start - 16) : start]
    percent = _PERCENT_RE.match(after)
    if percent:
        return "percent", end + percent.end(), None
    currency = _CURRENCY_RE.match(after)
    if currency or _CURRENCY_BEFORE_RE.search(before):
        stop = end + currency.end() if currency else end
        return "money", stop, None
    noun = _NOUN_RE.match(after)
    if noun:
        return "count", end + noun.end(), _COUNT_NOUNS[noun.group(1)]
    if value != value.to_integral_value():
        return "money", end, None
    return "bare", end, None


def _word_hits(paragraph: str, folded: str, index: list[int], occupied: list[tuple[int, int]]) -> list[_Hit]:
    words = sorted(_WORD_COUNTS, key=len, reverse=True)
    pattern = re.compile(r"(?<![a-z0-9])(" + "|".join(words) + r")(?![a-z0-9])")
    article = re.compile(r"(?<![a-z0-9])(o|un)(?![a-z0-9])")
    hits = []
    for match in list(pattern.finditer(folded)) + list(article.finditer(folded)):
        if any(not (match.end() <= lo or match.start() >= hi) for lo, hi in occupied):
            continue
        word = match.group(1)
        if word in _ARTICLE_COUNTS and _NOUN_RE.match(folded[match.end() :]) is None:
            continue
        value = Decimal(_ARTICLE_COUNTS[word] if word in _ARTICLE_COUNTS else _WORD_COUNTS[word])
        kind, end, count_kind = _classify(folded, match.start(), match.end(), value)
        if word in _ARTICLE_COUNTS and (kind != "count" or count_kind == "shops"):
            continue
        start, stop = _original(index, match.start(), end)
        hits.append(_hit_from_value(kind, start, stop, paragraph[start:stop], value, count_kind))
        occupied.append((match.start(), match.end()))
    return hits


def _shop_hits(paragraph: str, folded: str, index: list[int], facts: _Facts) -> list[_Hit]:
    alias_of: dict[str, set[str]] = {}
    for store_id in (*_KNOWN_SHOPS, *facts.store_ids):
        for alias, nid in _aliases(store_id):
            alias_of.setdefault(alias, set()).add(nid)
    candidates = []
    for alias, nids in alias_of.items():
        if not alias:
            continue
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(alias) + r"(?!\.[a-z0-9])(?![a-z0-9])"
        )
        for match in pattern.finditer(folded):
            candidates.append((match.start(), match.end(), frozenset(nids)))
    for match in _AMAZON_HOST_RE.finditer(folded):
        host = match.group(0)
        nids = frozenset({"amazon_de"}) if host == "amazon.de" else frozenset({host.replace(".", "_")})
        candidates.append((match.start(), match.end(), nids))
    candidates.sort(key=lambda row: (-(row[1] - row[0]), row[0]))
    chosen = []
    occupied: list[tuple[int, int]] = []
    for start, end, nids in candidates:
        if any(not (end <= lo or start >= hi) for lo, hi in occupied):
            continue
        occupied.append((start, end))
        orig_start, orig_end = _original(index, start, end)
        chosen.append(
            _Hit(
                kind="shop",
                start=orig_start,
                end=orig_end,
                span=paragraph[orig_start:orig_end],
                store_ids=nids,
            )
        )
    return chosen


def _aliases(store_id: str) -> list[tuple[str, str]]:
    nid = _norm_id(store_id)
    names = {nid, nid.replace("_", " "), nid.replace("_", "-")}
    display = _DISPLAY.get(store_id) or _DISPLAY.get(nid)
    if display:
        folded = _fold(display)
        names.add(folded)
        names.add(folded.replace("-", " "))
    for alias in _EXTRA_ALIASES.get(nid, ()):
        names.add(_fold(alias))
    return [(name, nid) for name in names if name]


def _facts(payload: dict) -> _Facts:
    money: set[int] = set()
    totals: set[int] = set()
    percents: set[Decimal] = set()
    books: set[int] = set()
    orders: set[int] = set()
    shops: set[int] = set()
    store_ids: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            _take_store(node, store_ids)
            for key, value in node.items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, int) and key.endswith("_cents"):
                    money.add(abs(value))
                    if key in _TOTAL_KEYS:
                        totals.add(value)
                elif _is_percent_key(key) and isinstance(value, (int, float)) and not isinstance(value, bool):
                    percents.add(Decimal(str(value)))
                elif key == "books" and isinstance(value, list):
                    books.add(len(value))
                elif key == "orders" and isinstance(value, list):
                    orders.add(len(value))
                    shops.add(len(value))
                elif key == "shops" and isinstance(value, list):
                    shops.add(len(value))
                elif key == "order_count" and isinstance(value, int):
                    orders.add(value)
                    shops.add(value)
                elif key == "books_listed" and isinstance(value, int):
                    books.add(value)
                elif key == "break_even_orders" and isinstance(value, int):
                    orders.add(value)
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item)

    walk(payload)
    # S17: "one order is not possible" / "nicio comandă unică" names the one-order option, whose
    # count is 1 by definition, even when the payload has no one-order answer to carry that count.
    one = one_order_of(payload)
    if isinstance(one, dict) and one.get("status") == "not_possible":
        orders.add(1)
    # A saving the payload does not store as its own field is still allowed
    # when it is the exact difference of two totals.
    total_list = [value for value in totals]
    for i, left in enumerate(total_list):
        for right in total_list[i + 1 :]:
            money.add(abs(left - right))
    return _Facts(
        money_cents=frozenset(money),
        percents=frozenset(percents),
        book_counts=frozenset(books),
        order_counts=frozenset(orders),
        shop_counts=frozenset(shops),
        store_ids=frozenset(store_ids),
    )


def _take_store(node: dict, store_ids: set[str]) -> None:
    for key, value in node.items():
        if key in _STORE_KEYS and isinstance(value, str) and value:
            store_ids.add(_norm_id(value))
        elif key in _STORE_LIST_KEYS and isinstance(value, list):
            store_ids.update(_norm_id(item) for item in value if isinstance(item, str) and item)
    store_id = node.get("id")
    if (
        isinstance(store_id, str)
        and store_id
        and "item_id" not in node
        and "title" not in node
        and ("currency" in node or any(isinstance(key, str) and key.endswith("_cents") for key in node))
    ):
        store_ids.add(_norm_id(store_id))


def _is_percent_key(key: str) -> bool:
    return "percent" in key or key.endswith("_pct")


def _parse_localized(token: str) -> Decimal | None:
    """Read RO and EN amounts. A group of three digits is a thousands separator.

    515,2 is 515.20, not a rounded 515,16. 1.234,56 and 1,234.56 are the same amount.
    """

    text = token.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", text):
        return None
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            head, tail = text.rsplit(",", 1)
            if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*", head):
                return None
            text = head.replace(".", "") + "." + tail
        else:
            head, tail = text.rsplit(".", 1)
            if not re.fullmatch(r"\d{1,3}(?:,\d{3})*", head):
                return None
            text = head.replace(",", "") + "." + tail
    elif text.count(".") > 1:
        if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
            return None
        text = text.replace(".", "")
    elif text.count(",") > 1:
        if not re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):
            return None
        text = text.replace(",", "")
    elif "." in text or "," in text:
        sep = "." if "." in text else ","
        head, tail = text.split(sep, 1)
        if len(tail) == 3 and re.fullmatch(r"\d{1,3}", head):
            text = head + tail
        else:
            text = head + "." + tail
    try:
        return Decimal(text)
    except ArithmeticError:
        return None


def _to_cents(value: Decimal) -> int | None:
    scaled = value * 100
    if scaled != scaled.to_integral_value() or scaled < 0:
        return None
    return int(scaled)


def _shown_lei(cents: int | None) -> str:
    if cents is None:
        return "not an exact lei amount"
    return f"{cents // 100}.{cents % 100:02d} lei"


def _money(cents: int) -> str:
    """The box shows comma decimals and a dot for thousands in both languages (462,58 lei)."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    lei, ban = divmod(cents, 100)
    grouped = f"{lei:,}".replace(",", ".")
    return f"{sign}{grouped},{ban:02d}"


def _unit(currency: str) -> str:
    code = (currency or "RON").strip().upper()
    if code in {"RON", "LEI"}:
        return "lei"
    return code


def _orders_en(count: int) -> str:
    return "order" if count == 1 else "orders"


def _orders_ro(count: int) -> str:
    return "comandă" if count == 1 else "comenzi"


def _join(names: list[str], conj: str) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} {conj} {names[1]}"
    return ", ".join(names[:-1]) + f" {conj} {names[-1]}"


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _norm_id(store_id: str) -> str:
    return store_id.strip().replace("-", "_").casefold()


def _fold(text: str) -> str:
    folded, _index = _fold_map(text)
    return folded


def _fold_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        for piece in _fold_char(char):
            chars.append(piece)
            index.append(position)
    return "".join(chars), index


def _fold_char(char: str) -> str:
    lowered = char.casefold()
    out = []
    for piece in unicodedata.normalize("NFD", lowered):
        if unicodedata.category(piece) == "Mn":
            continue
        out.append(piece.translate(_CHAR_FOLD))
    return "".join(out)


def _original(index: list[int], start: int, end: int) -> tuple[int, int]:
    if start >= end or not index:
        return 0, 0
    return index[start], index[end - 1] + 1

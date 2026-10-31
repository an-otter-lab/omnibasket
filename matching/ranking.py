"""Ranking for Open Library search docs, and which ISBN of a work to show.

The catalogue ranks for its whole corpus, not for one shopper in Romania. For
"Matilda Roald Dahl" it lists the Scots translation beside the Puffin book; for
"Harry Potter and the Philosopher's Stone" it lists the third volume, worksheets
and Chinese printings beside the two editions that are sold here. A work's ISBN
list is in no useful order either, so the first one is not the book.

The rules are deterministic and offline (no extra request per result):

- the query's own title words, minus the words that name this record's author;
- the author named in the query must be the record's author;
- the plain book over a marked edition (special, big book, film tie-in);
- a book over a workbook, study guide, bundle, collection or another volume;
- English (978-0, 978-1, 979-8) and Romanian (978-973, 978-606) printings only,
  unless the shopper asked for that ISBN;
- a known imprint (Puffin, Penguin, Viking) over an arbitrary printing;
- the shop index's own title for an ISBN is evidence: a printing whose shop title
  says "in scots" or "big book" is not the plain book.

Display text is never folded: a Romanian title keeps its diacritics.
"""

from __future__ import annotations

import re
import unicodedata

# ISBN registrant groups. English-language publishers and Romanian publishers only:
# 978-89 (Korean), 978-7 (Chinese), 978-84 (Spanish) and friends are not sold here.
EN_PREFIXES = ("9780", "9781", "9798")
RO_PREFIXES = ("978973", "978606")

# Puffin (978-0-14), Penguin (978-0-241) and Viking/Penguin (978-0-67x): the editions
# a Romanian parent actually finds on the shelf, in front of a library binding.
IMPRINT_PREFIXES = ("978014", "978024", "978067")

DIALECT_MARKERS = (
    "in scots", "scots", "in gaelic", "gaelic", "in welsh", "in irish",
    "in french", "in german", "in spanish", "in italian", "in portuguese",
    "in dutch", "in russian", "in polish", "in turkish", "in arabic",
    "in japanese", "in korean", "in chinese", "in latin", "in greek",
    "translated", "translation", "bilingual",
)
OTHER_BOOK_MARKERS = (
    "worksheet", "student workbook", "study guide", "summary of", "sparknotes",
    "cliffsnotes", "book bundle", "books bundle", "boxed set", "collection",
    "3-d movie book", "movie book", "the musical", "how to be a genius",
    "jokes", "quiz book", "colouring book", "coloring book", "sticker book",
    "poster book", "journal", "notebook", "planner",
)
EDITION_MARKERS = (
    "special edition", "deluxe", "anniversary", "illustrated", "colour edition",
    "color edition", "film tie-in", "gift set", "big book", "padded",
    "board book", "mini edition", "slipcase", "signed",
)

# A volume of a set: "Harry Potter and the Philosopher's Stone [1/2]".
VOLUME_RE = re.compile(r"\[\s*\d+\s*/\s*\d+\s*\]")

STOP_WORDS = {
    "si", "și", "de", "din", "la", "cu", "pe", "in", "un", "o", "le", "lui",
    "a", "ale", "ea", "ei", "eu", "tu", "el", "noi", "voi", "ele",
    "the", "an", "and", "or", "of", "for", "on", "at", "to", "by", "with",
}


def fold(text: str | None) -> str:
    """Lowercase, no diacritics, punctuation as single spaces. Comparison only."""
    if not text:
        return ""
    base = unicodedata.normalize("NFKD", str(text))
    base = "".join(ch for ch in base if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", base).split())


_PAREN = re.compile(r"\s*[(\[][^()\[\]]*[)\]]")


def core_title(text: str | None) -> str:
    """The title without a parenthetical aside: the same book, not another one."""
    return _PAREN.sub(" ", text or "")


def words(text: str | None) -> list[str]:
    """Folded words used for matching: no stop words, nothing shorter than two letters."""
    return [w for w in fold(text).split() if len(w) > 1 and w not in STOP_WORDS]


def has_marker(text: str | None, markers: tuple[str, ...]) -> bool:
    folded = " " + fold(text) + " "
    return any((" " + fold(m) + " ") in folded for m in markers)


def is_dialect(title: str | None) -> bool:
    """A translation or dialect printing ("Matilda in Scots")."""
    return has_marker(title, DIALECT_MARKERS)


def is_other_book(title: str | None) -> bool:
    """Not this book: a workbook, a study guide, a bundle, another volume of a set."""
    return has_marker(title, OTHER_BOOK_MARKERS) or bool(VOLUME_RE.search(title or ""))


def is_edition_variant(title: str | None) -> bool:
    """The same book in another package (special, deluxe, illustrated, big book)."""
    return has_marker(title, EDITION_MARKERS)


def is_ro_isbn(isbn: str | None) -> bool:
    return bool(isbn) and str(isbn).startswith(RO_PREFIXES)


def is_allowed_isbn(isbn: str | None) -> bool:
    """An English or Romanian printing. Anything else is not sold in this basket."""
    return bool(isbn) and (str(isbn).startswith(EN_PREFIXES) or str(isbn).startswith(RO_PREFIXES))


def _is_imprint(isbn: str) -> bool:
    return isbn.startswith(IMPRINT_PREFIXES)


def rank_score(query: str, doc: dict) -> float:
    """How well one Open Library work answers the query. Higher is better."""
    qwords = list(dict.fromkeys(words(query)))
    title = doc.get("title") or ""
    authors = doc.get("author_name") or []
    awords = set(words(" ".join(a for a in authors if isinstance(a, str))))

    # Words of the query that name this record's author are not title words.
    asked_title = [w for w in qwords if w not in awords]
    have = words(core_title(title))

    score = 0.0
    if asked_title:
        covered = [w for w in asked_title if w in have]
        missing = [w for w in asked_title if w not in have]
        score += 6.0 * len(covered) / len(asked_title)
        score -= 3.0 * len(missing)
        score -= 0.6 * len([w for w in have if w not in set(asked_title)])
    if fold(title) and fold(title) == fold(query):
        score += 2.0
    # The author the query names must be this record's author.
    extra = [w for w in qwords if w not in have]
    if extra:
        score += 2.5 * len([w for w in extra if w in awords]) / len(extra)

    if is_dialect(title):
        score -= 6.0
    if is_other_book(title):
        score -= 6.0
    if is_edition_variant(title):
        score -= 1.5
    if not authors:
        score -= 0.5
    isbns = [i for i in (doc.get("isbn") or []) if i]
    if any(is_allowed_isbn(i) for i in isbns):
        score += 0.5
    return score


def rank_docs(query: str, docs: list[dict]) -> list[int]:
    """Indices of the docs, best first. A book we can price comes before one we cannot;
    Open Library's own order breaks the remaining ties."""
    scores = [rank_score(query, doc) for doc in docs]
    priced = [any(is_allowed_isbn(str(i)) for i in (doc.get("isbn") or [])) for doc in docs]
    return sorted(range(len(docs)), key=lambda i: (not priced[i], -scores[i], i))


def usable_isbns(isbns: list[str], index_titles: dict[str, str] | None = None) -> list[str]:
    """The printings this shop can sell: English or Romanian, and not a marked edition.

    The shop index's title for an ISBN is evidence: when it says the printing is
    "in scots", a workbook or a multi-book collection, that ISBN is not the book
    the shopper asked for even though the work record lists it.
    """
    titles = index_titles or {}
    out = []
    for isbn in isbns:
        if not is_allowed_isbn(isbn):
            continue
        title = titles.get(isbn)
        if title and (is_dialect(title) or is_other_book(title)):
            continue
        out.append(isbn)
    return out


def _isbn_preference(isbn: str, index_titles: dict[str, str] | None) -> int:
    titles = index_titles or {}
    score = 0
    if _is_imprint(isbn):
        score += 3
    title = titles.get(isbn)
    if title:
        score += 1  # a shop carries it, so it is a real printing here
        if is_edition_variant(title):
            score -= 2
    return score


def pick_isbn(
    isbns: list[str],
    index_titles: dict[str, str] | None = None,
    language: str | None = None,
) -> str | None:
    """The ISBN to show for one work: language "ro" or "en" when asked, else either.

    A plain printing in a known imprint wins; the work's own ISBN order breaks ties.
    """
    pool = usable_isbns(isbns, index_titles)
    if language == "ro":
        pool = [i for i in pool if is_ro_isbn(i)]
    elif language == "en":
        pool = [i for i in pool if not is_ro_isbn(i)]
    if not pool:
        return None
    order = {isbn: pos for pos, isbn in enumerate(pool)}
    return min(pool, key=lambda i: (-_isbn_preference(i, index_titles), order[i]))

"""Elefant product pages, read in plain code (strategy ``elefant-html``).

Elefant pages carry no schema.org JSON-LD, so without this every Elefant page would go
to Muse gap-fill. Nothing here calls a model. What is read (3 Nov shop spike):

- price: the buy box (``js-vendor-price`` > ``current-price``), confirmed by the price
  the page's own product data layer declares (``GTMproductDetail`` ``"price"``). The
  sticky bar repeats the price and can read "N/A"; it is never used.
- currency: the data layer's ``currencyCode`` (or the buy box's ``lei``): RON.
- ISBN-13: the details row "Cod de bare" (EAN-13), else the "ISBN" row when it is an
  ISBN-13 (an ISBN-10 is not promoted, as everywhere in matching.isbn).
- language: the details row "Limba".
- seller: the line "Vândut si livrat de: <b>Elefant</b>".

An offer is ranked only when the buy box and the data layer agree on a price and the
seller line names Elefant. A missing or other seller (a marketplace listing) or an empty
data-layer price leaves the offer unranked, with its reason.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

from api.schema_org import SchemaOrgData
from matching.isbn import normalize_isbn13

SHOP_SELLER = "elefant"
BINDINGS = ("paperback", "hardback", "hardcover", "board book", "board books")

# Why a read page is not ranked. Stable machine strings; the UI maps them.
NO_PRICE = "no_price_extracted"
PRICE_UNCONFIRMED = "price_unconfirmed"
NOT_SOLD_BY_SHOP = "not_sold_by_shop"
CURRENCY_UNKNOWN = "currency_unknown"

_BUY_BOX = re.compile(
    r'class="[^"]*\bjs-vendor-price\b[^"]*"[^>]*>\s*<span[^>]*class="[^"]*\bcurrent-price\b[^"]*"[^>]*>(.*?)</span>',
    re.S,
)
_GTM = re.compile(r"GTMproductDetail\.push\(\s*\{(.*?)\}\s*\)", re.S)
_GTM_PRICE = re.compile(r'"price"\s*:\s*"([^"]*)"')
_CURRENCY_CODE = re.compile(r'"currencyCode"\s*:\s*"([A-Z]{3})"')
_SELLER = re.compile(r'class="[^"]*\bjs-vendor-offer-name\b[^"]*"[^>]*>(.*?)</span>', re.S)
_BOLD = re.compile(r"<b>(.*?)</b>", re.S)
_DETAIL = re.compile(
    r'<dt[^>]*class="[^"]*\bish-ca-type\b[^"]*"[^>]*>(.*?)</dt>\s*<dd[^>]*class="[^"]*\bish-ca-value\b[^"]*"[^>]*>(.*?)</dd>',
    re.S,
)
_TITLE = re.compile(r'<h1[^>]*class="[^"]*\bproduct-title\b[^"]*"[^>]*>(.*?)</h1>', re.S)
_BRAND_AUTHOR = re.compile(
    r'<h2[^>]*class="[^"]*\bproduct-brand\b[^"]*"[^>]*>\s*<a[^>]*href="[^"]*/filters/autor-[^"]*"[^>]*>(.*?)</a>', re.S
)
_TAG = re.compile(r"<[^>]+>")
_PRICE_TEXT = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?\s*(lei|ron)?", re.I)


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return " ".join(_html.unescape(_TAG.sub(" ", fragment)).split())


def _fold(text: str) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in base if not unicodedata.combining(ch)).casefold().strip()


def ron_cents(text: str | None) -> int | None:
    """'61,99 lei' -> 6199, '70,0 lei' -> 7000, '1.234,50 lei' -> 123450. Not a price -> None."""
    m = _PRICE_TEXT.fullmatch(_text(text))
    if not m:
        return None
    lei = int(m.group(1).replace(".", ""))
    frac = (m.group(2) or "0").ljust(2, "0")
    cents = lei * 100 + int(frac)
    return cents if cents > 0 else None


def _decimal_cents(text: str) -> int | None:
    """The data layer's '61.99' -> 6199. Empty -> None."""
    m = re.fullmatch(r"(\d+)(?:\.(\d{1,2}))?", text.strip())
    if not m:
        return None
    cents = int(m.group(1)) * 100 + int((m.group(2) or "0").ljust(2, "0"))
    return cents if cents > 0 else None


def _book_isbn(value: str | None) -> str | None:
    digits = normalize_isbn13(value) if value else None
    return digits if digits and digits[:3] in ("978", "979") else None


def split_binding(name: str) -> tuple[str, str | None]:
    """'Matilda, Paperback' -> ('Matilda', 'Paperback')."""
    head, sep, tail = name.rpartition(",")
    if sep and _fold(tail).replace("-", " ") in BINDINGS:
        return head.strip(), tail.strip()
    return name, None


@dataclass
class ElefantPage:
    """What an Elefant product page says, before any ranking rule."""

    price_cents: int | None = None  # the buy box
    declared_price_cents: int | None = None  # the data layer
    currency: str | None = None
    isbn13: str | None = None
    language: str | None = None
    name: str | None = None
    binding: str | None = None
    authors: list[str] = field(default_factory=list)
    seller: str | None = None

    @property
    def seller_certainty(self) -> str:
        if not self.seller:
            return "unknown"
        return "direct" if _fold(self.seller) == SHOP_SELLER else "marketplace"

    @property
    def not_ranked_reason(self) -> str | None:
        """None when the offer may be ranked, else why not."""
        if self.price_cents is None or self.declared_price_cents is None:
            return NO_PRICE
        if self.price_cents != self.declared_price_cents:
            return PRICE_UNCONFIRMED
        if self.currency != "RON":
            return CURRENCY_UNKNOWN
        if self.seller_certainty != "direct":
            return NOT_SOLD_BY_SHOP
        return None

    def as_schema(self) -> SchemaOrgData:
        """The shape the offer path uses. The price is kept only when the offer may be ranked."""
        ranked = self.not_ranked_reason is None
        return SchemaOrgData(
            price_cents=self.price_cents if ranked else None,
            currency=self.currency,
            availability=None,  # both buttons are hidden in the HTML; a script picks one
            isbn13=self.isbn13,
            name=self.name,
            authors=list(self.authors) or None,
            source="elefant_html",
            # The pasted-link path names the book from raw, as it does from a JSON-LD node.
            raw={"name": self.name, "author": list(self.authors)},
        )


def parse(html: str | None) -> ElefantPage:
    """Read an Elefant product page. Never raises; a field it cannot find stays None."""
    page = ElefantPage()
    if not html or not isinstance(html, str):
        return page

    box = _BUY_BOX.search(html)
    if box:
        page.price_cents = ron_cents(box.group(1))
    gtm = _GTM.search(html)
    if gtm:
        declared = _GTM_PRICE.search(gtm.group(1))
        if declared:
            page.declared_price_cents = _decimal_cents(declared.group(1))

    code = _CURRENCY_CODE.search(html)
    if code:
        page.currency = code.group(1)
    elif box and re.search(r"\blei\b", _text(box.group(1)), re.I):
        page.currency = "RON"

    details: dict[str, str] = {}
    for key, value in _DETAIL.findall(html):
        details.setdefault(_fold(_text(key)), _text(value))
    page.isbn13 = _book_isbn(details.get("cod de bare")) or _book_isbn(details.get("isbn"))
    page.language = details.get("limba") or None

    title = _TITLE.search(html)
    if title:
        page.name, page.binding = split_binding(_text(title.group(1)))
    authors = details.get("autor")
    if authors:
        page.authors = [a.strip() for a in authors.split(",") if a.strip()]
    else:
        brand = _BRAND_AUTHOR.search(html)
        if brand and _text(brand.group(1)):
            page.authors = [_text(brand.group(1))]

    line = _SELLER.search(html)
    if line and "livrat de" in _fold(_text(line.group(1))):
        bold = _BOLD.search(line.group(1))
        if bold and _text(bold.group(1)):
            page.seller = _text(bold.group(1))
    return page

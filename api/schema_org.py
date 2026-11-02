"""Schema.org structured data extraction from HTML pages.

Extracts JSON-LD data from product pages without calling any model.
Focuses on Product and Book schemas for book pricing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from matching.isbn import normalize_isbn13


@dataclass
class SchemaOrgData:
    """Structured data extracted from schema.org JSON-LD."""
    
    price_cents: int | None = None
    currency: str | None = None
    availability: str | None = None
    isbn13: str | None = None
    name: str | None = None
    authors: list | None = None
    source: str = "schema_org"
    raw: dict | None = None
    
    @property
    def has_price(self) -> bool:
        return self.price_cents is not None
    
    @property
    def has_isbn(self) -> bool:
        return self.isbn13 is not None


# Regex to find JSON-LD scripts in HTML
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL
)


def extract_schema_org(html: str) -> SchemaOrgData:
    """Extract schema.org structured data from HTML.
    
    Looks for JSON-LD scripts with @type Product or Book.
    Extracts price, currency, availability, and ISBN.
    Returns empty SchemaOrgData if nothing found.
    """
    result = SchemaOrgData()
    
    if not html or not isinstance(html, str):
        return result
    
    # Find all JSON-LD blocks
    matches = _JSONLD_RE.findall(html)
    if not matches:
        return result
    
    # Try to parse each block and find Product/Book data
    for match in matches:
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        
        # Handle both single objects and arrays
        items = data if isinstance(data, list) else [data]
        flat: list = []
        for entry in items:
            if isinstance(entry, dict) and isinstance(entry.get("@graph"), list):
                flat.extend(entry["@graph"])
            else:
                flat.append(entry)
        items = flat
        
        for item in items:
            if not isinstance(item, dict):
                continue
            
            # Check if this is a Product or Book
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_types = item_type
            else:
                item_types = [item_type]
            
            # Check if this is a Product or Book (case-insensitive)
            item_types_lower = [t.lower() if isinstance(t, str) else t for t in item_types]
            is_product = any(t.lower() in ("product", "book") if isinstance(t, str) else False for t in item_types)
            if not is_product:
                continue
            
            # Extract from offers
            offers = item.get("offers")
            if offers:
                if isinstance(offers, list):
                    # Take first offer
                    offers = offers[0] if offers else None
                
                if isinstance(offers, dict):
                    # Extract price
                    price = offers.get("price")
                    if price is not None:
                        try:
                            price_float = float(price)
                            result.price_cents = int(round(price_float * 100))
                        except (ValueError, TypeError):
                            pass
                    
                    # Extract currency
                    currency = offers.get("priceCurrency")
                    if currency and isinstance(currency, str):
                        result.currency = currency.upper()
                    
                    # Extract availability
                    availability = offers.get("availability")
                    if availability and isinstance(availability, str):
                        result.availability = availability
            
            if isinstance(item.get("name"), str) and result.name is None:
                result.name = item["name"]
            raw_authors = item.get("author")
            if raw_authors is not None and result.authors is None:
                listed = raw_authors if isinstance(raw_authors, list) else [raw_authors]
                names = [a.get("name") if isinstance(a, dict) else a for a in listed]
                result.authors = [n for n in names if isinstance(n, str)]

            # Extract ISBN
            isbn = item.get("isbn")
            if isbn and isinstance(isbn, str):
                normalized = normalize_isbn13(isbn)
                if normalized:
                    result.isbn13 = normalized
            
            # Store raw data for debugging
            if result.raw is None:
                result.raw = item
    
    return result


def schema_from_facts(facts: dict | None) -> SchemaOrgData:
    """Structured page facts a saved read keeps, as the schema.org shape.

    A cache row stores the facts the runtime needs (price, currency, ISBN,
    availability, name, authors) instead of the shop's page text, so this is
    the only way a cache hit reaches ``SchemaOrgData``.
    """
    if not isinstance(facts, dict):
        return SchemaOrgData()
    price_cents = facts.get("price_cents")
    if price_cents is not None:
        try:
            price_cents = int(price_cents)
        except (TypeError, ValueError):
            price_cents = None
    isbn = facts.get("isbn13")
    normalized = normalize_isbn13(isbn) if isbn else None
    authors = facts.get("authors")
    if isinstance(authors, str):
        authors = [authors]
    return SchemaOrgData(
        price_cents=price_cents,
        currency=facts.get("currency"),
        availability=facts.get("availability"),
        isbn13=normalized,
        name=facts.get("title"),
        authors=list(authors) if isinstance(authors, list) else None,
        raw=facts,
    )


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ISBN13_RUN = re.compile(r"97[89](?:[-\s]?\d){10}")
_MAX_CENTS = 10_000_000


def _cents_readings(token: str) -> set[int]:
    """Every price in cents a number printed on a page can mean.

    ``1.234`` is a thousand-separated 1234 or a decimal 1.234; both are kept,
    as the page-text check accepts either spelling.
    """
    parts = re.split(r"[.,]", token)
    if any(len(p) > 9 for p in parts):
        return set()
    readings = {int("".join(parts)) * 100}
    if len(parts) > 1:
        readings.add(int(round(float("".join(parts[:-1]) + "." + parts[-1]) * 100)))
    return {c for c in readings if 0 < c < _MAX_CENTS}


def page_evidence(page_text: str | None) -> dict:
    """The numbers a page prints, captured by plain code from its text.

    A cache row keeps these instead of the text, so a stored Muse read is
    still checked against what the page showed and not against a value Muse
    itself supplied.
    """
    text = page_text or ""
    cents: set[int] = set()
    for token in _NUMBER.findall(text):
        cents |= _cents_readings(token)
    isbns = {n for n in (normalize_isbn13(m) for m in _ISBN13_RUN.findall(text)) if n}
    return {"price_cents": sorted(cents), "isbn13": sorted(isbns)}


def facts_from_extraction(
    schema: SchemaOrgData,
    page_text: str | None,
    fields: dict | None = None,
    currency: str | None = None,
) -> dict:
    """The facts a cache row keeps after a live read: no page text, no raw HTML.

    Prices and ISBN are the page's structured data only, never a value Muse
    supplied, plus the numbers the page printed (``page_evidence``) for the
    stored Muse read to be checked against on a cache hit. ``currency`` is the
    one the offer used, the shop's own when the page named none.
    """

    fields = fields or {}
    return {
        "title": fields.get("title") or schema.name,
        "authors": list(schema.authors or ([] if not fields.get("author") else [fields["author"]])),
        "isbn13": schema.isbn13,
        "price_cents": schema.price_cents,
        "currency": currency or schema.currency,
        "availability": schema.availability,
        "page_evidence": page_evidence(page_text),
    }


def extract_price_from_text(text: str) -> tuple[int | None, str | None]:
    """Extract price from visible text as fallback.
    
    Looks for patterns like:
    - 57.00 Lei
    - 57,00 lei
    - 57.00 RON
    - 57 lei
    
    Returns (price_cents, currency) or (None, None).
    """
    if not text or not isinstance(text, str):
        return None, None
    
    # Match patterns like "57.00 Lei", "57,00 lei", "57 RON", "57 lei"
    # Handles both . and , as decimal separator
    price_pattern = re.compile(
        r'(\d+(?:[.,]\d{2})?)\s*(lei|ron)',
        re.IGNORECASE
    )
    
    match = price_pattern.search(text)
    if not match:
        return None, None
    
    price_str = match.group(1)
    currency = match.group(2).upper()
    
    # Normalize decimal separator
    if ',' in price_str:
        price_str = price_str.replace(',', '.')
    
    try:
        price_float = float(price_str)
        price_cents = int(round(price_float * 100))
        return price_cents, currency
    except ValueError:
        return None, None

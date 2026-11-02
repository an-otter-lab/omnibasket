"""What a saved page read asks Muse Spark for, and the keys it returns.

The demo seed's ``model_json`` rows were produced with this prompt. The prompt
lives here so the rules it states (tri-state seller, selected format only, no
invented check digit) stay testable after the exploration scripts left the
repository.
"""

from __future__ import annotations

SCHEMA = [
    "title",
    "author",
    "format",
    "isbn13",
    "publisher",
    "price",
    "currency",
    "in_stock",
    "sold_by",
    "ships_from",
    "sold_and_shipped_by_store",
    "shipping_note",
    "membership_note",
    "confidence",
    "notes",
]

PROMPT = (
    "You read one online-store product page and return strict JSON only, no commentary, no code fences. "
    "Keys: " + ", ".join(SCHEMA) + ". "
    "price is a number (the selected format only, no symbol) or null. currency is the symbol or code printed with that price. "
    "in_stock is true, false, or null. confidence is high|medium|low. Use null rather than guess. Quote only what is visible. "
    "sold_and_shipped_by_store is tri-state: true, false, or null. "
    "true only when the seller and the fulfiller named on the page are the store itself. "
    "false only when the page names a third-party seller or fulfiller that is not the store. "
    "null when no seller is named. Never answer false just because the seller line is missing. "
    "membership_note is a membership or subscription benefit that applies to the selected format only, or null. "
    "Do not put a points, stamps, or loyalty counter in membership_note (for example Puncte Express). "
    "Do not copy a membership caption that belongs to a different format, such as an audiobook tile. "
    "isbn13 is the ISBN-13 the page labels as an ISBN, or null. "
    "Do not take it from a product code, a URL, or an unlabelled EAN. "
    "Hyphens may be copied; a check digit that is not printed must not be invented."
)

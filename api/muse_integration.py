"""Muse integration for gap-filling and cross-checking.

Calls Muse Spark through meta_budget.py to fill gaps in schema.org data.
Every number from Muse must match the page text or structured data, or it's dropped.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add tools directory to path for meta_budget import
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import meta_budget
from api.schema_org import SchemaOrgData
from matching.isbn import normalize_isbn13
from matching.validate import validate_extraction


@dataclass
class MuseResult:
    """Result from Muse gap-fill and cross-check."""
    
    fields: dict | None = None
    validation: dict | None = None
    accepted: bool = False
    reread_reasons: list[str] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    endpoint: str | None = None
    cross_check_passed: bool = False
    cross_check_mismatches: list[str] | None = None


# Prompt for Muse to extract book data from page text
_MUSE_PROMPT = """You are reading a product page from an online bookstore. Extract the following information as JSON:

{
  "title": "Book title",
  "author": "Author name",
  "format": "Edition format (e.g., paperback, hardcover, board_book)",
  "isbn13": "ISBN-13 if visible",
  "publisher": "Publisher name",
  "price": 123.45,
  "currency": "RON",
  "in_stock": true,
  "sold_by": "Seller name if third-party",
  "ships_from": "Shipper name if third-party",
  "sold_and_shipped_by_store": true,
  "shipping_note": "Delivery information",
  "membership_note": "Membership benefits",
  "confidence": "high",
  "notes": "Any relevant observations"
}

Rules:
- price is a number (no symbol), or null if not visible
- currency is the code or symbol (RON, Lei, EUR, etc.)
- in_stock is true, false, or null
- sold_and_shipped_by_store is tri-state: true, false, or null
  - true only when seller and fulfiller are the store itself
  - false only when a third-party seller or fulfiller is named
  - null when no seller is named
- isbn13 is the ISBN-13 if explicitly labeled as ISBN, not a product code
- Hyphens may be present in ISBN; do not invent a check digit
- Use null for missing values, never guess
- Quote only what is visible on the page

Return ONLY the JSON object, no explanation or code fences."""


def _estimate_cost(text: str) -> float:
    """Estimate cost of a Muse call based on text length."""
    # Rough estimate: 4 chars per token for input, 2500 tokens output
    tokens_in = len(text) // 4 + 200
    tokens_out = 2500
    return meta_budget.compute_cost(tokens_in, tokens_out)


def _extract_muse_json(response: str | None) -> dict | None:
    """Extract JSON from Muse response, handling markdown code blocks."""
    if not response:
        return None
    
    response = response.strip()
    
    # Try direct parse first
    try:
        result = json.loads(response)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    
    # Try to extract from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    # Try to find any JSON object in the response
    json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    
    return None


def _payload_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("output_text"):
        return str(payload["output_text"])
    parts = []
    for block in payload.get("output") or []:
        for piece in block.get("content") or []:
            if piece.get("text"):
                parts.append(piece["text"])
    if parts:
        return "".join(parts)
    choices = payload.get("choices") or []
    if choices:
        return str((choices[0].get("message") or {}).get("content") or "")
    return ""


def _call_muse(page_text: str) -> tuple[dict, int, int, float, int, str]:
    """One Muse call through meta_budget.guarded_post (the spend-window HTTP path).

    spike.extract.call_model is not used: it opens the API on its own.
    """
    estimate = _estimate_cost(page_text)
    body = {
        "model": meta_budget.MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": _MUSE_PROMPT + "\n\nPAGE TEXT:\n" + page_text}],
            }
        ],
        "max_output_tokens": 2500,
    }
    payload, row = meta_budget.guarded_post(body, estimate, note="muse-gap-fill")
    fields = _extract_muse_json(_payload_text(payload))
    return (
        fields,
        int(row.get("tokens_in") or 0),
        int(row.get("tokens_out") or 0),
        float(row.get("cost_usd") or 0),
        int(row.get("latency_ms") or 0),
        str(row.get("endpoint") or ""),
    )


def adopt_muse_fields(model_json: dict | None, page_text: str, schema_org: SchemaOrgData) -> dict:
    """Return Muse fields with every mismatching number removed.

    This is the production check. A price that is not on the page or in
    schema.org does not come back.
    """
    if not isinstance(model_json, dict):
        return {}
    fields = dict(model_json)
    _passed, mismatches = cross_check_muse_fields(fields, page_text or "", schema_org)
    for name in mismatches:
        fields[name] = None
    return fields


def adopt_muse_fields_from_facts(model_json: dict | None, facts: dict | None, schema_org: SchemaOrgData) -> dict:
    """The same check for a cache row, which keeps facts instead of page text.

    A number from Muse must match the structured fact the read stored: the
    price in cents and the page's own ISBN. Anything else is dropped, exactly
    as a number missing from the page was dropped before.
    """
    fields = dict(model_json)
    _passed, mismatches = cross_check_muse_fields_against_facts(fields, facts, schema_org)
    for name in mismatches:
        fields[name] = None
    return fields


def cross_check_muse_fields_against_facts(
    fields: dict,
    facts: dict | None,
    schema_org: SchemaOrgData,
) -> tuple[bool, list[str]]:
    """Cross-check Muse numbers against structured facts, not page text."""
    if not fields:
        return True, []
    mismatches: list[str] = []
    price = fields.get("price")
    if price is not None:
        try:
            cents = int(round(float(price) * 100))
        except (TypeError, ValueError):
            cents = None
        if schema_org.price_cents is None or cents != schema_org.price_cents:
            mismatches.append("price")
    isbn = fields.get("isbn13")
    if isbn is not None:
        normalized = normalize_isbn13(isbn)
        if normalized is None or not schema_org.isbn13 or normalized != schema_org.isbn13:
            mismatches.append("isbn13")
    return len(mismatches) == 0, mismatches


def _cross_check_number(value: Any, page_text: str, field_name: str) -> bool:
    """Check if a number from Muse appears in the page text.
    
    Returns True if the number is found or if it's null/not a number.
    Returns False if it's a number that doesn't appear in the text.
    """
    if value is None:
        return True
    
    if isinstance(value, bool):
        return True
    
    if isinstance(value, (int, float)):
        # Check if the number appears in the text
        # Handle both . and , as decimal separator
        num_str = str(value)
        
        # Check exact match
        if num_str in page_text:
            return True
        
        # Check with comma instead of dot
        if "." in num_str:
            comma_version = num_str.replace(".", ",")
            if comma_version in page_text:
                return True
        
        # Check with different formatting (e.g., 57.00 vs 57)
        if isinstance(value, float) and value.is_integer():
            int_version = str(int(value))
            if int_version in page_text:
                return True
        
        # Check with thousand separators
        if isinstance(value, (int, float)):
            formatted = f"{value:,.2f}"
            if formatted in page_text or formatted.replace(",", ".") in page_text:
                return True
            formatted_no_decimal = f"{value:,.0f}"
            if formatted_no_decimal in page_text or formatted_no_decimal.replace(",", ".") in page_text:
                return True
        
        # Number not found
        return False
    
    return True


def _cross_check_isbn(isbn: str | None, page_text: str, schema_isbn: str | None) -> bool:
    """Check if ISBN from Muse matches schema.org or appears in page text."""
    if isbn is None:
        return True
    
    normalized = normalize_isbn13(isbn)
    if normalized is None:
        return False
    
    # Check against schema.org ISBN
    if schema_isbn and normalized == schema_isbn:
        return True
    
    # Check if ISBN appears in page text (with or without hyphens)
    # First check normalized (no hyphens)
    if normalized in page_text:
        return True
    
    # Check if original hyphenated version appears
    if isbn != normalized and isbn in page_text:
        return True
    
    # Try common hyphenation patterns
    # Standard ISBN-13: XXX-X-XXXX-XXXX-X (but actual grouping varies by country)
    # For Romanian (606): 978-606-XXX-XXX-X
    if len(normalized) == 13:
        # Try 3-3-3-3-1 pattern (common for some countries)
        isbn_3_3_3_3_1 = f"{normalized[:3]}-{normalized[3:6]}-{normalized[6:9]}-{normalized[9:12]}-{normalized[12]}"
        if isbn_3_3_3_3_1 in page_text:
            return True
        
        # Try 3-3-5-1-1 pattern (another common pattern)
        isbn_3_3_5_1_1 = f"{normalized[:3]}-{normalized[3:6]}-{normalized[6:11]}-{normalized[11:12]}-{normalized[12]}"
        if isbn_3_3_5_1_1 in page_text:
            return True
    
    return False


def cross_check_muse_fields(
    fields: dict,
    page_text: str,
    schema_org: SchemaOrgData,
) -> tuple[bool, list[str]]:
    """Cross-check all numbers from Muse against page text and schema.org.
    
    Returns (passed, mismatches) where mismatches is a list of field names
    that failed the cross-check.
    """
    if not fields:
        return True, []
    
    mismatches = []
    
    # Cross-check price
    if "price" in fields:
        if not _cross_check_number(fields["price"], page_text, "price"):
            # Also check against schema.org price
            if schema_org.price_cents is not None:
                muse_price_cents = int(round(float(fields["price"]) * 100))
                if muse_price_cents != schema_org.price_cents:
                    mismatches.append("price")
            else:
                mismatches.append("price")
    
    # Cross-check ISBN
    if "isbn13" in fields:
        if not _cross_check_isbn(fields["isbn13"], page_text, schema_org.isbn13):
            mismatches.append("isbn13")
    
    return len(mismatches) == 0, mismatches


def gap_fill_with_muse(
    page_text: str,
    schema_org: SchemaOrgData,
) -> MuseResult:
    """Use Muse to fill gaps in schema.org data, with cross-checking.
    
    Every number from Muse must match the page text or structured data.
    Numbers that don't match are dropped.
    
    Returns MuseResult with fields, validation, and cross-check status.
    """
    result = MuseResult()
    
    if not page_text or not page_text.strip():
        return result
    
    try:
        # Call Muse
        fields, tokens_in, tokens_out, cost, latency, endpoint = _call_muse(page_text)
        
        result.tokens_in = tokens_in
        result.tokens_out = tokens_out
        result.cost_usd = cost
        result.latency_ms = latency
        result.endpoint = endpoint
        
        if fields is None:
            result.accepted = False
            result.reread_reasons = ["muse_parse_failed"]
            return result
        
        # Validate extraction using existing validation
        validated, validation = validate_extraction(fields)
        result.fields = validated
        result.validation = validation
        
        if not validation["accepted"]:
            result.accepted = False
            result.reread_reasons = validation["reasons"]
            return result
        
        # Cross-check numbers against page text
        passed, mismatches = cross_check_muse_fields(validated, page_text, schema_org)
        result.cross_check_passed = passed
        result.cross_check_mismatches = mismatches
        
        if not passed:
            # Drop mismatched numbers
            for field in mismatches:
                if field in validated:
                    validated[field] = None
            
            result.fields = validated
            result.accepted = True  # Accepted after dropping mismatches
        else:
            result.accepted = True
        
        return result
    
    except Exception as e:
        # Budget exceeded or other error
        result.accepted = False
        result.reread_reasons = [f"muse_error: {type(e).__name__}"]
        return result

"""Tests for Muse integration and cross-checking.

Tests that Muse fills gaps in schema.org data and that every number
from Muse matches the page text or structured data.
"""

import pytest
from unittest.mock import patch, MagicMock
from api.muse_integration import (
    gap_fill_with_muse,
    cross_check_muse_fields,
    _cross_check_number,
    _cross_check_isbn,
    _extract_muse_json,
)
from api.schema_org import SchemaOrgData


def test_cross_check_number_exact_match():
    """Test that a number matching the page text passes cross-check."""
    assert _cross_check_number(57.00, "Price: 57.00 Lei", "price") is True


def test_cross_check_number_with_comma():
    """Test that a number with comma decimal separator passes cross-check."""
    assert _cross_check_number(116.53, "Price: 116,53 lei", "price") is True


def test_cross_check_number_no_match():
    """Test that a number not in the page text fails cross-check."""
    assert _cross_check_number(99.99, "Price: 57.00 Lei", "price") is False


def test_cross_check_number_null():
    """Test that null values pass cross-check (not required)."""
    assert _cross_check_number(None, "Some text", "price") is True


def test_cross_check_number_boolean():
    """Test that boolean values pass cross-check."""
    assert _cross_check_number(True, "In stock", "in_stock") is True


def test_cross_check_number_with_thousand_separator():
    """Test that numbers with thousand separators pass cross-check."""
    assert _cross_check_number(1234.56, "Price: 1,234.56 RON", "price") is True


def test_cross_check_isbn_match():
    """Test that ISBN matching schema.org passes cross-check."""
    schema_org = SchemaOrgData(isbn13="9786068996011")
    assert _cross_check_isbn("9786068996011", "ISBN 9786068996011", schema_org) is True


def test_cross_check_isbn_with_hyphens():
    """Test that ISBN with hyphens passes cross-check."""
    schema_org = SchemaOrgData(isbn13="9786068996011")
    assert _cross_check_isbn("978-606-899-601-1", "ISBN 978-606-899-601-1", schema_org) is True


def test_cross_check_isbn_no_match():
    """Test that ISBN not in page text fails cross-check."""
    schema_org = SchemaOrgData(isbn13="9786068996011")
    assert _cross_check_isbn("9781234567890", "ISBN 9786068996011", schema_org) is False


def test_cross_check_isbn_null():
    """Test that null ISBN passes cross-check."""
    schema_org = SchemaOrgData(isbn13="9786068996011")
    assert _cross_check_isbn(None, "No ISBN here", schema_org) is True


def test_cross_check_isbn_invalid_check_digit():
    """Test that ISBN with invalid check digit fails cross-check."""
    schema_org = SchemaOrgData(isbn13="9786068996011")
    # Invalid check digit (last digit should be 1, not 0)
    assert _cross_check_isbn("9786068996010", "ISBN 9786068996010", schema_org) is False


def test_cross_check_muse_fields_all_match():
    """Test cross-check when all Muse numbers match page text."""
    fields = {
        "price": 57.00,
        "isbn13": "9786068996011",
        "in_stock": True,
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011, In Stock"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is True
    assert mismatches == []


def test_cross_check_muse_fields_price_mismatch():
    """Test cross-check when Muse price doesn't match page text."""
    fields = {
        "price": 99.99,  # Wrong price
        "isbn13": "9786068996011",
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is False
    assert "price" in mismatches


def test_cross_check_muse_fields_isbn_mismatch():
    """Test cross-check when Muse ISBN doesn't match page text."""
    fields = {
        "price": 57.00,
        "isbn13": "9781234567890",  # Wrong ISBN
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is False
    assert "isbn13" in mismatches


def test_cross_check_muse_fields_no_numbers():
    """Test cross-check when Muse returns no numbers."""
    fields = {
        "title": "Test Book",
        "author": "Test Author",
        "format": "paperback",
    }
    page_text = "Test Book by Test Author, paperback edition"
    schema_org = SchemaOrgData()
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is True
    assert mismatches == []


def test_extract_muse_json_valid():
    """Test extraction of valid JSON from Muse response."""
    response = '{"price": 57.00, "isbn13": "9786068996011"}'
    result = _extract_muse_json(response)
    
    assert result is not None
    assert result["price"] == 57.00
    assert result["isbn13"] == "9786068996011"


def test_extract_muse_json_with_markdown():
    """Test extraction of JSON from markdown code block."""
    response = """
    ```json
    {
        "price": 57.00,
        "isbn13": "9786068996011"
    }
    ```
    """
    result = _extract_muse_json(response)
    
    assert result is not None
    assert result["price"] == 57.00
    assert result["isbn13"] == "9786068996011"


def test_extract_muse_json_with_text():
    """Test extraction of JSON from response with surrounding text."""
    response = """
    Here's the data:
    {
        "price": 57.00,
        "isbn13": "9786068996011"
    }
    That's all.
    """
    result = _extract_muse_json(response)
    
    assert result is not None
    assert result["price"] == 57.00


def test_extract_muse_json_invalid():
    """Test extraction returns None for invalid JSON."""
    response = "This is not JSON at all"
    result = _extract_muse_json(response)
    
    assert result is None


def test_extract_muse_json_empty():
    """Test extraction returns None for empty response."""
    result = _extract_muse_json("")
    assert result is None
    
    result = _extract_muse_json(None)
    assert result is None


def test_cross_check_drops_mismatched_numbers():
    """Test that mismatched numbers are dropped from Muse output."""
    fields = {
        "price": 99.99,  # Wrong price
        "isbn13": "9781234567890",  # Wrong ISBN
        "title": "Test Book",  # Non-number, should stay
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    # After cross-check, mismatched numbers should be dropped
    assert "price" in mismatches
    assert "isbn13" in mismatches
    
    # Simulate dropping mismatched numbers (as done in gap_fill_with_muse)
    for field in mismatches:
        if field in fields:
            fields[field] = None
    
    assert fields["price"] is None
    assert fields["isbn13"] is None
    assert fields["title"] == "Test Book"  # Non-number stays


def test_cross_check_preserves_matching_numbers():
    """Test that matching numbers are preserved."""
    fields = {
        "price": 57.00,  # Correct price
        "isbn13": "9786068996011",  # Correct ISBN
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is True
    assert mismatches == []
    
    # No fields should be dropped
    assert fields["price"] == 57.00
    assert fields["isbn13"] == "9786068996011"


def test_cross_check_multiple_mismatches():
    """Test cross-check with multiple mismatched numbers."""
    fields = {
        "price": 99.99,
        "isbn13": "9781234567890",
        "in_stock": False,  # Non-number, should pass
    }
    page_text = "Price: 57.00 Lei, ISBN: 9786068996011, Out of Stock"
    schema_org = SchemaOrgData(price_cents=5700, isbn13="9786068996011")
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    assert passed is False
    assert len(mismatches) == 2
    assert "price" in mismatches
    assert "isbn13" in mismatches


def test_cross_check_schema_org_fallback():
    """Test cross-check falls back to schema.org when number not in text."""
    fields = {
        "price": 57.00,
    }
    # Price not in page text, but matches schema.org
    page_text = "Some book description without explicit price"
    schema_org = SchemaOrgData(price_cents=5700)
    
    passed, mismatches = cross_check_muse_fields(fields, page_text, schema_org)
    
    # Should pass because it matches schema.org
    assert passed is True
    assert mismatches == []

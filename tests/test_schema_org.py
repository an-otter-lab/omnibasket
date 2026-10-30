"""Tests for schema.org structured data extraction.

Tests extraction of price, currency, availability, and ISBN from HTML pages
with JSON-LD structured data.
"""

import pytest
from api.schema_org import extract_schema_org, extract_price_from_text


def test_extract_schema_org_with_product_schema():
    """Test extraction from Product schema with offers."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Test Book",
            "isbn": "9786068996011",
            "offers": {
                "@type": "Offer",
                "price": "59.99",
                "priceCurrency": "RON",
                "availability": "https://schema.org/InStock"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    assert result.price_cents == 5999
    assert result.currency == "RON"
    assert result.availability == "https://schema.org/InStock"
    assert result.isbn13 == "9786068996011"
    assert result.has_price is True
    assert result.has_isbn is True
    assert result.source == "schema_org"


def test_extract_schema_org_with_book_schema():
    """Test extraction from Book schema."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Book",
            "name": "Test Book",
            "isbn": "9780763666873",
            "offers": {
                "@type": "Offer",
                "price": 45.50,
                "priceCurrency": "EUR"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    assert result.price_cents == 4550
    assert result.currency == "EUR"
    assert result.isbn13 == "9780763666873"
    assert result.has_price is True
    assert result.has_isbn is True


def test_extract_schema_org_with_multiple_offers():
    """Test extraction when there are multiple offers (takes first)."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "offers": [
                {
                    "@type": "Offer",
                    "price": "100.00",
                    "priceCurrency": "RON",
                    "availability": "https://schema.org/InStock"
                },
                {
                    "@type": "Offer",
                    "price": "120.00",
                    "priceCurrency": "RON",
                    "availability": "https://schema.org/OutOfStock"
                }
            ]
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    # Should take first offer
    assert result.price_cents == 10000
    assert result.currency == "RON"
    assert result.availability == "https://schema.org/InStock"


def test_extract_schema_org_with_invalid_isbn():
    """Test that invalid ISBN is rejected."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "isbn": "9781234567890",
            "offers": {
                "@type": "Offer",
                "price": "50.00",
                "priceCurrency": "RON"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    # ISBN with invalid check digit should be None
    assert result.isbn13 is None
    assert result.has_isbn is False


def test_extract_schema_org_with_valid_isbn():
    """Test that valid ISBN is accepted."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "isbn": "9786068996011",
            "offers": {
                "@type": "Offer",
                "price": "57.00",
                "priceCurrency": "RON"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    assert result.isbn13 == "9786068996011"
    assert result.has_isbn is True


def test_extract_schema_org_no_json_ld():
    """Test extraction when there's no JSON-LD."""
    html = """
    <!DOCTYPE html>
    <html>
    <body>
        <p>Price: 50.00 Lei</p>
    </body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    assert result.price_cents is None
    assert result.currency is None
    assert result.availability is None
    assert result.isbn13 is None
    assert result.has_price is False
    assert result.has_isbn is False


def test_extract_schema_org_invalid_json():
    """Test extraction when JSON-LD is malformed."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {invalid json}
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    assert result.price_cents is None
    assert result.currency is None


def test_extract_schema_org_empty_html():
    """Test extraction with empty HTML."""
    result = extract_schema_org("")
    
    assert result.price_cents is None
    assert result.currency is None
    assert result.availability is None
    assert result.isbn13 is None


def test_extract_price_from_text_lei():
    """Test price extraction from text with 'lei'."""
    text = "Preț: 57.00 Lei"
    price_cents, currency = extract_price_from_text(text)
    
    assert price_cents == 5700
    assert currency == "LEI"


def test_extract_price_from_text_ron():
    """Test price extraction from text with 'RON'."""
    text = "51.78 RON"
    price_cents, currency = extract_price_from_text(text)
    
    assert price_cents == 5178
    assert currency == "RON"


def test_extract_price_from_text_comma_decimal():
    """Test price extraction with comma as decimal separator."""
    text = "116,53 lei"
    price_cents, currency = extract_price_from_text(text)
    
    assert price_cents == 11653
    assert currency == "LEI"


def test_extract_price_from_text_no_price():
    """Test price extraction when no price is present."""
    text = "This is a book about programming."
    price_cents, currency = extract_price_from_text(text)
    
    assert price_cents is None
    assert currency is None


def test_extract_price_from_text_empty():
    """Test price extraction with empty text."""
    price_cents, currency = extract_price_from_text("")
    
    assert price_cents is None
    assert currency is None


def test_extract_schema_org_case_insensitive_type():
    """Test that schema type matching is case-insensitive."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "product",
            "offers": {
                "@type": "Offer",
                "price": "50.00",
                "priceCurrency": "RON"
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    
    result = extract_schema_org(html)
    
    # Should still extract even with lowercase type
    assert result.price_cents == 5000
    assert result.currency == "RON"

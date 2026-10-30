"""Test fixtures for offer reading tests.

Contains sample HTML pages with schema.org data and expected extractions.
"""

# Sample HTML with Product schema.org data
PRODUCT_PAGE_WITH_SCHEMA = """
<!DOCTYPE html>
<html>
<head>
    <title>Sample Book</title>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "The Very Hungry Caterpillar",
        "isbn": "9780241003008",
        "offers": {
            "@type": "Offer",
            "price": "61.33",
            "priceCurrency": "RON",
            "availability": "https://schema.org/InStock"
        }
    }
    </script>
</head>
<body>
    <h1>The Very Hungry Caterpillar</h1>
    <p>Author: Eric Carle</p>
    <div class="price">61.33 Lei</div>
    <div class="availability">In Stock</div>
</body>
</html>
"""

# Sample HTML with Book schema.org data
BOOK_PAGE_WITH_SCHEMA = """
<!DOCTYPE html>
<html>
<head>
    <title>Sample Book</title>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": "Owl Babies",
        "isbn": "9780763666873",
        "author": "Martin Waddell",
        "offers": {
            "@type": "Offer",
            "price": "51.78",
            "priceCurrency": "RON",
            "availability": "https://schema.org/InStock"
        }
    }
    </script>
</head>
<body>
    <h1>Owl Babies</h1>
    <p>Author: Martin Waddell</p>
    <div class="price">51.78 RON</div>
</body>
</html>
"""

# Sample HTML with multiple offers
PAGE_WITH_MULTIPLE_OFFERS = """
<!DOCTYPE html>
<html>
<head>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Sample Book",
        "isbn": "9786068996011",
        "offers": [
            {
                "@type": "Offer",
                "price": "57.00",
                "priceCurrency": "RON",
                "availability": "https://schema.org/InStock"
            },
            {
                "@type": "Offer",
                "price": "59.00",
                "priceCurrency": "RON",
                "availability": "https://schema.org/OutOfStock"
            }
        ]
    }
    </script>
</head>
<body>
    <div class="price">57.00 lei</div>
</body>
</html>
"""

# Sample HTML without schema.org data
PAGE_WITHOUT_SCHEMA = """
<!DOCTYPE html>
<html>
<head>
    <title>Sample Book</title>
</head>
<body>
    <h1>Ghici cat de mult te iubesc</h1>
    <p>Author: Sam McBratney</p>
    <div class="price">57.00 Lei</div>
    <div class="availability">În stoc</div>
    <p>ISBN: 9786068996011</p>
</body>
</html>
"""

# Sample HTML with price in text but no schema.org
PAGE_WITH_PRICE_ONLY = """
<!DOCTYPE html>
<html>
<body>
    <h1>Test Book</h1>
    <p>Price: 116.53 lei</p>
    <p>ISBN: 9781529105100</p>
</body>
</html>
"""

# Sample HTML with invalid ISBN (bad check digit)
PAGE_WITH_INVALID_ISBN = """
<!DOCTYPE html>
<html>
<head>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Invalid ISBN Book",
        "isbn": "9781234567890",
        "offers": {
            "@type": "Offer",
            "price": "50.00",
            "priceCurrency": "RON",
            "availability": "https://schema.org/InStock"
        }
    }
    </script>
</head>
<body>
    <div class="price">50.00 Lei</div>
</body>
</html>
"""

# Expected extraction results
EXPECTED_EXTRACTIONS = {
    "product_page": {
        "price_cents": 6133,
        "currency": "RON",
        "isbn13": "9780241003008",
        "availability": "https://schema.org/InStock",
    },
    "book_page": {
        "price_cents": 5178,
        "currency": "RON",
        "isbn13": "9780763666873",
        "availability": "https://schema.org/InStock",
    },
    "multiple_offers": {
        "price_cents": 5700,  # First offer
        "currency": "RON",
        "isbn13": "9786068996011",
        "availability": "https://schema.org/InStock",
    },
    "no_schema": {
        "price_cents": None,  # Schema.org extraction fails
        "currency": None,
        "isbn13": None,
        "availability": None,
    },
}

# Mock Muse responses for gap-fill tests
MOCK_MUSE_RESPONSE_MATCHING = """
{
    "title": "Ghici cat de mult te iubesc",
    "author": "Sam McBratney",
    "format": "board_book",
    "isbn13": "9786068996011",
    "publisher": "Cartea Copiilor",
    "price": 57.00,
    "currency": "RON",
    "in_stock": true,
    "sold_by": null,
    "ships_from": null,
    "sold_and_shipped_by_store": true,
    "shipping_note": "Livrare în 1-5 zile",
    "membership_note": null,
    "confidence": "high",
    "notes": null
}
"""

MOCK_MUSE_RESPONSE_MISMATCH = """
{
    "title": "Ghici cat de mult te iubesc",
    "author": "Sam McBratney",
    "format": "board_book",
    "isbn13": "9786068996011",
    "publisher": "Cartea Copiilor",
    "price": 99.99,
    "currency": "RON",
    "in_stock": true,
    "sold_by": null,
    "ships_from": null,
    "sold_and_shipped_by_store": true,
    "shipping_note": "Livrare în 1-5 zile",
    "membership_note": null,
    "confidence": "high",
    "notes": "Price doesn't match page"
}
"""

# Test page for Muse cross-check (price 57.00 in text)
PAGE_FOR_MUSE_CROSSCHECK = """
<!DOCTYPE html>
<html>
<body>
    <h1>Ghici cat de mult te iubesc</h1>
    <p>Author: Sam McBratney</p>
    <div class="price">57.00 Lei</div>
    <p>ISBN: 9786068996011</p>
    <p>Format: Carte cartonată</p>
    <p>Editura: Cartea Copiilor</p>
</body>
</html>
"""

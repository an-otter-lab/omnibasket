"""S4b: a 13-digit number that does not start 978 or 979 is never an ISBN-13, at every check."""

from api.input_understanding import to_isbn13 as input_to_isbn13
from api.muse_integration import _cross_check_isbn
from index.search import to_isbn13 as search_to_isbn13, validate_isbn
from matching.isbn import normalize_isbn13

# Check digits that work out, so only the prefix rule can turn them away.
BARCODES = ["6421234567895", "5012345678900", "642-1234567895"]
GOOD = {"9780142402535": "9780142402535", "979-10-90636-07-1": "9791090636071"}


def test_normalize_isbn13_rejects_barcodes():
    for code in BARCODES:
        assert normalize_isbn13(code) is None, code
    for raw, isbn in GOOD.items():
        assert normalize_isbn13(raw) == isbn


def test_input_understanding_rejects_barcodes():
    for code in BARCODES:
        assert input_to_isbn13(code) is None, code
    for raw, isbn in GOOD.items():
        assert input_to_isbn13(raw) == isbn
    assert input_to_isbn13("0306406152") == "9780306406157"


def test_index_search_rejects_barcodes():
    for code in BARCODES:
        assert not validate_isbn(code), code
        assert search_to_isbn13(code) is None, code
    for raw, isbn in GOOD.items():
        assert validate_isbn(raw)
        assert search_to_isbn13(raw) == isbn


def test_muse_cross_check_rejects_a_barcode_even_on_the_page():
    assert _cross_check_isbn("6421234567895", "EAN 6421234567895", None) is False
    assert _cross_check_isbn("9780142402535", "ISBN 9780142402535", None) is True

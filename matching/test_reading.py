"""Spike defects and edition modes. Run: python3 -m unittest matching.test_reading"""

from __future__ import annotations

import unittest

from matching.editions import cross_edition_average, match_offers
from matching.isbn import normalize_isbn13
from matching.validate import compare_read_to_capture, validate_extraction


def _base(**kw):
    row = {
        "title": "The Very Hungry Caterpillar",
        "author": "Eric Carle",
        "format": "Board book",
        "isbn13": "9780399226908",
        "publisher": "World of Eric Carle",
        "price": 27.53,
        "currency": "RON",
        "in_stock": True,
        "sold_by": None,
        "ships_from": None,
        "sold_and_shipped_by_store": None,
        "shipping_note": None,
        "membership_note": None,
    }
    row.update(kw)
    return row


class IsbnTests(unittest.TestCase):
    def test_hyphen_stripped_amazon_grouping(self):
        # Page printed 978-0399226908. Check digit is valid. Digits only.
        self.assertEqual(normalize_isbn13("978-0399226908"), "9780399226908")
        self.assertEqual(normalize_isbn13("978-0-399-22690-8"), "9780399226908")

    def test_bad_check_digit_is_null(self):
        self.assertIsNone(normalize_isbn13("9780399226900"))
        self.assertIsNone(normalize_isbn13(""))
        self.assertIsNone(normalize_isbn13(None))

    def test_product_code_prefix_is_not_kept(self):
        # 16 digits after stripping: not an ISBN-13.
        self.assertIsNone(normalize_isbn13("BRT9780241003008"))


class ValidatorTests(unittest.TestCase):
    def test_false_without_named_seller_is_reread(self):
        # Barnes & Noble and the Romanian text runs: false, sold_by null.
        out, verdict = validate_extraction(_base(sold_and_shipped_by_store=False))
        self.assertFalse(verdict["accepted"])
        self.assertTrue(verdict["reread"])
        self.assertIn("false_without_named_seller", verdict["reasons"])
        self.assertFalse(out["sold_and_shipped_by_store"])

    def test_false_with_named_third_party_stands(self):
        out, verdict = validate_extraction(
            _base(
                sold_by="Libris English SRL",
                ships_from="Libris English SRL",
                sold_and_shipped_by_store=False,
                isbn13=None,
            )
        )
        self.assertTrue(verdict["accepted"])
        self.assertEqual(out["sold_by"], "Libris English SRL")

    def test_null_without_seller_stands(self):
        _, verdict = validate_extraction(_base(sold_and_shipped_by_store=None))
        self.assertTrue(verdict["accepted"])

    def test_points_counter_is_not_a_membership(self):
        _, verdict = validate_extraction(_base(membership_note="Puncte Express: 94"))
        self.assertIn("membership_is_points_counter", verdict["reasons"])
        self.assertTrue(verdict["reread"])

    def test_real_membership_line_stands(self):
        _, verdict = validate_extraction(
            _base(membership_note="Premium Members save an extra 10%")
        )
        self.assertTrue(verdict["accepted"])

    def test_invalid_isbn_marked_and_nulled(self):
        out, verdict = validate_extraction(_base(isbn13="978-0399226900"))
        self.assertIsNone(out["isbn13"])
        self.assertIn("isbn_invalid", verdict["reasons"])

    def test_hyphenated_valid_isbn_normalised_quietly(self):
        out, verdict = validate_extraction(_base(isbn13="978-1509804757"))
        self.assertEqual(out["isbn13"], "9781509804757")
        self.assertTrue(verdict["accepted"])


class ReadCheckTests(unittest.TestCase):
    """A model read is compared with the capture. It never rewrites it."""

    @staticmethod
    def _read(**fields):
        base = {
            "title": "Owl Babies",
            "isbn13": None,
            "price": 51.78,
            "currency": "Lei",
            "in_stock": True,
        }
        base.update(fields)
        return {"status": "OK", "fields": base}

    def test_matching_read(self):
        check = compare_read_to_capture(self._read(), price_cents=5178)
        self.assertEqual(check["status"], "match")
        self.assertEqual(check["mismatch_fields"], [])

    def test_lei_and_ron_are_the_same_currency(self):
        for currency in ("Lei", "RON", "lei"):
            check = compare_read_to_capture(self._read(currency=currency), price_cents=5178)
            self.assertEqual(check["status"], "match", currency)

    def test_different_price_names_the_price_field(self):
        check = compare_read_to_capture(self._read(price=57.0), price_cents=5178)
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["mismatch_fields"], ["price"])

    def test_different_isbn_names_the_isbn_field(self):
        check = compare_read_to_capture(
            self._read(isbn13="978-6068996011"), price_cents=5178, isbn13="9781529105100"
        )
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["mismatch_fields"], ["isbn13"])

    def test_unprinted_isbn_is_not_a_mismatch(self):
        check = compare_read_to_capture(self._read(isbn13=None), price_cents=5178, isbn13="9781529105100")
        self.assertEqual(check["status"], "match")

    def test_missing_read_says_why(self):
        self.assertEqual(compare_read_to_capture(None, price_cents=5178)["status"], "not_read")
        failed = compare_read_to_capture({"status": "MODEL_ERROR"}, price_cents=5178)
        self.assertEqual(failed["status"], "not_read")
        self.assertEqual(failed["reason"], "read_failed")
        no_price = compare_read_to_capture(self._read(price=None), price_cents=5178)
        self.assertEqual(no_price["status"], "not_read")
        self.assertEqual(no_price["reason"], "price_not_printed")


class EditionTests(unittest.TestCase):
    def test_strict_does_not_mix_isbns_or_average(self):
        offers = [
            {"offer_id": "a", "store": "bookzone", "title": "Ghici", "isbn13": "978-6068996011", "edition": "cartonată", "price": 46.5},
            {"offer_id": "b", "store": "emag", "title": "Ghici cat de mult te iubesc", "isbn13": "9786068996011", "edition": "cartonată", "price": 56.0},
            {"offer_id": "c", "store": "libris", "title": "Ghici", "isbn13": "9781406358780", "edition": "paperback", "price": 30.0},
            {"offer_id": "d", "store": "amazon", "title": "Ghici", "isbn13": None, "edition": "unknown", "price": 10.0},
        ]
        result = match_offers(offers, "strict_isbn", primary_isbn="9786068996011")
        self.assertFalse(result["averaged"])
        keys = sorted(g["key"] for g in result["groups"])
        self.assertEqual(keys, ["9781406358780", "9786068996011"])
        primary = next(g for g in result["groups"] if g["key"] == "9786068996011")
        self.assertIsNone(primary["price"])
        self.assertEqual(primary["editions"][0]["price"]["min"], 46.5)
        self.assertEqual(primary["editions"][0]["price"]["max"], 56.0)
        self.assertNotIn("mean", primary["editions"][0]["price"])
        other = next(g for g in result["groups"] if g["key"] == "9781406358780")
        self.assertTrue(other["editions"][0]["differs"])
        self.assertEqual(len(result["unmatched"]), 1)
        self.assertIsNone(cross_edition_average(primary))

    def test_same_story_keeps_editions_apart(self):
        offers = [
            {"offer_id": "a", "store": "amazon.de", "title": "Guess How Much I Love You", "isbn13": "9781406358780", "edition": "Pappband", "price": 46.44},
            {"offer_id": "b", "store": "bookzone", "title": "Guess How Much I Love You board book", "isbn13": "9780744523232", "edition": "Board book", "price": 20.0},
        ]
        result = match_offers(offers, "same_story", primary_isbn="9781406358780")
        self.assertEqual(len(result["groups"]), 1)
        group = result["groups"][0]
        self.assertIsNone(group["price"])
        self.assertEqual(len(group["editions"]), 2)
        prices = sorted(e["price"]["min"] for e in group["editions"])
        self.assertEqual(prices, [20.0, 46.44])
        self.assertNotEqual(prices[0], 33.22)
        differed = [e for e in group["editions"] if e["differs"]]
        self.assertEqual(len(differed), 1)
        self.assertEqual(differed[0]["isbn13"], "9780744523232")
        self.assertIsNone(cross_edition_average(group))


class PromptTests(unittest.TestCase):
    def test_prompt_states_the_three_rules(self):
        from api.extraction_prompt import PROMPT

        self.assertIn("tri-state", PROMPT)
        self.assertIn("false only when", PROMPT)
        self.assertIn("selected format", PROMPT)
        self.assertIn("Puncte Express", PROMPT)
        self.assertIn("check digit", PROMPT.lower())

    def test_the_live_gap_fill_sends_this_prompt(self):
        from unittest.mock import patch

        from api import muse_integration
        from api.extraction_prompt import PROMPT

        sent = []

        def post(body, estimate, note, provider="meta", timeout=120):
            sent.append(body["input"][0]["content"][0]["text"])
            return {"output_text": "{}"}, {}

        with patch.object(muse_integration.meta_budget, "guarded_post", post):
            muse_integration._call_muse("page")
        self.assertEqual(sent, [PROMPT + "\n\nPAGE TEXT:\npage"])


if __name__ == "__main__":
    unittest.main()

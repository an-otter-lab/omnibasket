"""Containment rule: short book title matches a longer shop title with subtitle."""

from api.title_match import strong_match, core_title, surname


# Sapiens by Yuval Noah Harari: Open Library title is just "Sapiens".
SAPIENS_OL_TITLE = "Sapiens"
SAPIENS_OL_AUTHOR = "Yuval Noah Harari"


def test_sapiens_short_vs_libris_subtitle_matches():
    """Libris sells it as 'Sapiens: Scurtă istorie a omenirii' (subtitle added)."""
    libris_page = "Sapiens: Scurtă istorie a omenirii"
    libris_authors = ["Yuval Noah Harari"]
    assert strong_match(SAPIENS_OL_TITLE, SAPIENS_OL_AUTHOR, libris_page, libris_authors)


def test_sapiens_graphic_volume_does_not_match():
    """A graphic-novel volume is a different work by the same author."""
    graphic_page = "Sapiens: O istorie grafică. Vol. 1. Nașterea omenirii"
    graphic_authors = ["Yuval Noah Harari", "David Vandermeulen"]
    assert not strong_match(
        SAPIENS_OL_TITLE, SAPIENS_OL_AUTHOR, graphic_page, graphic_authors
    )


def test_sapiens_different_author_does_not_match():
    """A different book titled 'Sapiens...' by different authors."""
    other_page = "Sapiens: Cele mai recente descoperiri"
    other_authors = ["François Savatier", "Silvana Condemi"]
    assert not strong_match(
        SAPIENS_OL_TITLE, SAPIENS_OL_AUTHOR, other_page, other_authors
    )


def test_sapiens_same_author_surname_still_gate():
    """Different author surname, even if title contains the core."""
    assert not strong_match(
        SAPIENS_OL_TITLE, SAPIENS_OL_AUTHOR,
        "Sapiens: Scurtă istorie a omenirii", ["Alt Autor"],
    )


# The numbers gate is tested in test_title_match_parenthetical.py
# test_numbers_gate_kept: "Harry Potter (Vol. 1)" vs "Harry Potter 2"
# (parentheticals are stripped from core_title, so numbers only matter
# when they appear outside parentheticals in the title)


# Existing cases must still pass.
def test_micul_print_parenthetical_still_matches():
    ol_title = "Micul prinț (Cu explicații pentru copii și recenzie pentru adulți)"
    author = "Antoine de Saint-Exupéry"
    page = "Micul print Antoine de Saint-Exupery editie bilingva"
    page_authors = ["Antoine de Saint-Exupery"]
    assert strong_match(ol_title, author, page, page_authors)


def test_harry_potter_same_isbn_still_strict():
    """Core_title + numbers gate still rejects a different HP book."""
    assert not strong_match(
        "Harry Potter și piatra filozofală", "J. K. Rowling",
        "Harry Potter si camera secretelor", ["J.K. Rowling"],
    )


def test_harry_potter_same_book_still_matches():
    assert strong_match(
        "Harry Potter și piatra filozofală", "J. K. Rowling",
        "Harry Potter si piatra filosofala - J.K. Rowling", ["J.K. Rowling"],
    )


# Edge cases for the containment rule itself.
def test_core_title_contains_substring_match():
    """Core-title containment works for short vs long titles."""
    want = core_title("Sapiens")
    have = core_title("Sapiens: Scurtă istorie a omenirii")
    assert want in have


def test_core_title_does_not_contain_different_work():
    want = core_title("Sapiens")
    have = core_title("Sapiens: Cele mai recente descoperiri")
    # containment alone is true, but author gate rejects (checked in strong_match)
    assert want in have


def test_surname_last_token():
    assert surname("Yuval Noah Harari") == "harari"
    assert surname("François Savatier") == "savatier"

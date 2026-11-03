"""Elefant (3 Nov): pages read in plain code, never by a model; ranked only when sold by Elefant.

Every page here is synthetic: the markup has the shape of an Elefant product page (the class
names and field labels the parser keys on), with made-up books, names and prices.
"""

import asyncio
import sqlite3
from unittest.mock import patch

import pytest

from api import elefant_page
from api.cache import PageCache
from api.fetch_guard import GuardedFetch
from api.offers import live_offer_row, lookup_elefant_urls, read_offers_parallel, store_from_profile

ISBN = "9780000000002"
OTHER_ISBN = "9781111111113"
UUID = "0f0f0f0f-1111-4222-8333-444455556666"
URL_PB = f"https://www.elefant.ro/the-sample-book-paperback_{UUID}"
URL_HB = f"https://www.elefant.ro/the-sample-book-hardback_{UUID[:-1]}7"
URL_OTHER = f"https://www.elefant.ro/sample-book-paperback_{UUID[:-1]}8"
TITLE = "The Sample Book"
AUTHOR = "Ana Example"


def html(
    name="The Sample Book, Paperback",
    author="Ana Example",
    price="42,50&nbsp;lei",
    declared="42.50",
    sticky="42,50 lei",
    sticky_currency="RON",
    barcode=ISBN,
    isbn10="0000000000",
    language="Engleza",
    seller="Elefant",
):
    seller_line = (
        '<div class="product-vendor vendor-offer-data">\n<span class="js-vendor-offer-name">'
        f'V&acirc;ndut si livrat de:&nbsp;\n<!-- c --><b>{seller}</b></span>\n</div>'
        if seller is not None else ""
    )
    details = f'<dt class="ish-ca-type">Autor</dt><dd class="ish-ca-value">{author}</dd>' if author else ""
    if isbn10:
        details += f'<dt class="ish-ca-type">ISBN</dt><dd class="ish-ca-value">{isbn10}</dd>'
    if barcode:
        details += f'<dt class="ish-ca-type">Cod de bare</dt><dd class="ish-ca-value">{barcode}</dd>'
    if language:
        details += f'<dt class="ish-ca-type">Limba</dt><dd class="ish-ca-value">{language}</dd>'
    return f"""<!DOCTYPE html><html lang="ro"><head><title>{author} - {name} - shop</title></head><body>
<div class="product-info js-product-info"><h2 class="product-brand"><a href="https://www.elefant.ro/list/carti/filters/autor-x">{author}</a>
</h2><h1 class="product-title">{name}</h1>
{seller_line}
<table class="pdp-table"><tr class="row-pdp"><th class="pdp-table-th price-container-pdp"><div class="product-price vendor-offer-data js-vendor-price"><span class="current-price">{price}</span>
<span class="hidden bonus-points js-bonus-points">+1 puncte</span></div></th></tr></table></div>
<div class="price-container"><div class="current-price " data-testing-id="current-price" data-price-currencymnemonic="{sticky_currency}">{sticky}</div></div>
<button name="StickyAddProduct" style="display: none;">Adaugă</button><button name="StickyNotAvailable" style="display: none;">Indisponibil</button>
<dl class="ish-productAttributes">{details}</dl>
<script>window.ish.GTMproductDetail.push(
{{
"id": "{UUID}",
"name": "{name}",
"price": "{declared}",
"brand": "Sample Press"
}});</script>
<script>dataLayer.push({{"ecommerce": {{"currencyCode": "RON"}}}});</script>
</body></html>"""


def fetched(text, url=URL_PB, status=200):
    return GuardedFetch(final_url=url, status=status, content_type="text/html", body=text.encode(), text=text, hops=0)


# ---------------------------------------------------------------- the parser


def test_ranked_page_fields():
    page = elefant_page.parse(html())
    assert page.price_cents == 4250 and page.declared_price_cents == 4250 and page.currency == "RON"
    assert page.isbn13 == ISBN and page.language == "Engleza"
    assert page.name == "The Sample Book" and page.binding == "Paperback" and page.authors == ["Ana Example"]
    assert page.seller == "Elefant" and page.seller_certainty == "direct"
    assert page.not_ranked_reason is None
    data = page.as_schema()
    assert data.price_cents == 4250 and data.isbn13 == ISBN and data.source == "elefant_html"


def test_sticky_bar_na_is_ignored():
    page = elefant_page.parse(html(sticky="N&#47;A", sticky_currency="N&#47;A"))
    assert page.price_cents == 4250 and page.currency == "RON" and page.not_ranked_reason is None


def test_marketplace_listing_with_empty_declared_price_is_not_ranked():
    """No seller line and an empty data-layer price: the shape of a marketplace listing."""
    page = elefant_page.parse(html(seller=None, declared="", sticky="N&#47;A", sticky_currency="N&#47;A", isbn10=None, language=None))
    assert page.price_cents == 4250 and page.declared_price_cents is None
    assert page.not_ranked_reason == "no_price_extracted" and page.as_schema().price_cents is None


def test_missing_or_other_seller_is_not_ranked():
    assert elefant_page.parse(html(seller=None)).not_ranked_reason == "not_sold_by_shop"
    other = elefant_page.parse(html(seller="Sample Trading SRL"))
    assert other.seller_certainty == "marketplace" and other.not_ranked_reason == "not_sold_by_shop"
    assert other.as_schema().price_cents is None


def test_buy_box_and_declared_price_must_agree():
    assert elefant_page.parse(html(declared="39.99")).not_ranked_reason == "price_unconfirmed"


def test_isbn_from_barcode_else_isbn_row():
    assert elefant_page.parse(html(barcode=None, isbn10="9780306406157")).isbn13 == "9780306406157"
    # An ISBN-10 is not promoted (matching.isbn): with no barcode the page has no usable ISBN.
    assert elefant_page.parse(html(barcode=None, isbn10="0306406152")).isbn13 is None
    # A product barcode that is not a book number is not an ISBN.
    assert elefant_page.parse(html(barcode="5941234567890", isbn10=None)).isbn13 is None


def test_ron_cents():
    assert elefant_page.ron_cents("61,99&nbsp;lei") == 6199
    assert elefant_page.ron_cents("70,0 lei") == 7000
    assert elefant_page.ron_cents("1.234,50 lei") == 123450
    assert elefant_page.ron_cents("N/A") is None and elefant_page.ron_cents("") is None


def test_empty_page_never_raises():
    page = elefant_page.parse("<html></html>")
    assert page.price_cents is None and page.not_ranked_reason == "no_price_extracted"


# ---------------------------------------------------------------- reading offers


@pytest.fixture
def elefant_db(tmp_path, monkeypatch):
    import api.offers as offers
    from functools import partial

    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES('elefant',?,?,NULL,NULL,'2026-11-03')", [
            (URL_HB, "the sample book"), (URL_OTHER, "sample book"), (URL_PB, "the sample book"),
            (f"https://www.elefant.ro/the-sample-book-two-paperback_{UUID}", "the sample book two"),
        ])
    monkeypatch.setattr(offers, "lookup_elefant_urls", partial(offers.lookup_elefant_urls, db_path=path))
    monkeypatch.setattr(offers, "shop_is_indexed", partial(offers.shop_is_indexed, db_path=path))
    return path


@pytest.fixture
def cache(tmp_path):
    return PageCache(tmp_path / "c.sqlite")


@pytest.fixture(autouse=True)
def no_muse():
    with patch("api.offers.gap_fill_with_muse", side_effect=AssertionError("an Elefant page reached Muse")):
        yield


def read(cache, isbn=ISBN, title=TITLE, author=AUTHOR):
    return asyncio.run(read_offers_parallel(["elefant"], isbn, "book-x", cache, title=title, author=author))[0]


def test_candidates_paperback_first_and_article_variants(elefant_db):
    assert lookup_elefant_urls(TITLE, db_path=elefant_db) == [URL_PB, URL_OTHER, URL_HB]
    assert lookup_elefant_urls("Sample Book", db_path=elefant_db)[:2] == [URL_OTHER, URL_PB]
    assert lookup_elefant_urls("", db_path=elefant_db) == []


def test_same_isbn_is_ranked_direct_and_read_once(elefant_db, cache):
    with patch("api.offers.fetch", return_value=fetched(html())) as f:
        first = read(cache)
        second = read(cache)
    assert f.call_count == 1
    assert first.status == "ok" and first.price_cents == 4250 and first.currency == "RON"
    assert first.seller_certainty == "direct" and not first.other_printing and first.edition == "Paperback"
    assert first.listing_url == URL_PB and first.cache == "live"
    assert second.cache == "hit" and second.price_cents == 4250
    assert live_offer_row(first, {"elefant"}, set())["ranked"] is True


def test_another_book_under_the_title_is_skipped_for_the_next_candidate(elefant_db, cache):
    pages = {
        URL_PB: html(name="The Sample Book, Paperback", author="Someone Else", barcode=OTHER_ISBN),
        URL_OTHER: html(barcode="9783333333335", price="30,00&nbsp;lei", declared="30.00"),
        URL_HB: html(author="Someone Else", barcode="9782222222224"),
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)) as f:
        offer = read(cache)
    assert [c.args[0] for c in f.call_args_list] == [URL_PB, URL_OTHER, URL_HB]
    assert offer.status == "ok" and offer.price_cents == 3000 and offer.other_printing
    assert offer.isbn13 == "9783333333335" and offer.listing_url == URL_OTHER
    # The page known to be another book is not read again for the next book under that title.
    with patch("api.offers.fetch", side_effect=AssertionError("read again")):
        again = read(cache, isbn="9783333333335", title="Sample Book")
    assert again.status == "ok" and again.listing_url == URL_OTHER


def test_reads_stop_at_the_cap(elefant_db, cache, monkeypatch):
    monkeypatch.setattr("api.offers.ELEFANT_READS", 2)
    stranger = html(author="Someone Else", barcode=OTHER_ISBN)
    with patch("api.offers.fetch", side_effect=lambda url: fetched(stranger, url)) as f:
        offer = read(cache)
    assert f.call_count == 2 and offer.status == "skipped" and offer.reason == "no_match_in_index"
    with patch("api.offers.fetch", side_effect=AssertionError("read again")):
        assert read(cache).status == "skipped"


def test_marketplace_offer_is_listed_not_ranked(elefant_db, cache):
    with patch("api.offers.fetch", return_value=fetched(html(seller=None, declared=""))):
        offer = read(cache)
    assert offer.status == "failed" and offer.reason == "no_price_extracted" and offer.price_cents is None
    assert offer.listing_url == URL_PB
    row = live_offer_row(offer, {"elefant"}, set())
    assert row["ranked"] is False and row["not_ranked_reason"] == "no_price_extracted"
    with patch("api.offers.fetch", return_value=fetched(html(seller="Sample Trading SRL"))):
        other = read(PageCache(elefant_db.parent / "c2.sqlite"))
    assert live_offer_row(other, {"elefant"}, set())["not_ranked_reason"] == "not_sold_by_shop"


def test_503_maintenance_page_is_a_failed_load(elefant_db, cache, monkeypatch):
    monkeypatch.setattr("api.offers.ELEFANT_READS", 1)
    with patch("api.offers.fetch", return_value=fetched("<html>maintenance</html>", status=503)) as f:
        offer = read(cache)
    assert f.call_count == 1 and offer.status == "failed" and offer.reason == "fetch_refused: http_503"
    assert live_offer_row(offer, {"elefant"}, set())["not_ranked_reason"] == "fetch_refused"


def test_no_candidate_is_no_offer(elefant_db, cache):
    with patch("api.offers.fetch", side_effect=AssertionError("nothing to read")):
        offer = read(cache, title="A Book Nobody Sells")
    assert offer.status == "skipped" and offer.reason == "no_match_in_index"


def test_pasted_elefant_page_is_read_directly(elefant_db, cache):
    url = f"https://www.elefant.ro/anything_{UUID}"
    with patch("api.offers.fetch", return_value=fetched(html(), url)) as f:
        offer = asyncio.run(read_offers_parallel(
            ["elefant"], ISBN, "book-x", cache, title=TITLE, author=AUTHOR, listing_urls={"elefant": url}))[0]
    assert [c.args[0] for c in f.call_args_list] == [url]
    assert offer.status == "ok" and offer.listing_url == url


def test_elefant_store_fees_from_profile():
    store = store_from_profile("elefant")
    assert store.free_shipping_threshold_cents == 19900
    assert store.shipping_fee_cents == 1699 and store.per_order_fee_cents == 999


def test_explain_check_accepts_elefant_when_it_is_in_the_payload():
    from api.explain_check import check_explanation

    payload = {"cheapest": {"total_cents": 9000, "orders": [
        {"store_id": "elefant", "order_total_cents": 9000, "books": [{"price_cents": 4250}]}]},
        "shops": [{"store_id": "elefant"}]}
    assert check_explanation("Elefant has the book for 90,00 lei in 1 order.", payload).ok


def test_pasted_elefant_link_names_the_book_from_the_page(tmp_path):
    from api import input_understanding

    url = f"https://www.elefant.ro/the-sample-book-paperback_{UUID}"
    with patch("api.input_understanding.fetch", return_value=fetched(html(), url)) as f:
        out = input_understanding.understand(url, index_db=tmp_path / "none.sqlite3")
    assert f.call_count == 1
    assert out["isbn13"] == ISBN and out["shop_context"] == {"shop_id": "elefant", "product_url": url}
    assert out["structured_query"]["title"] == "The Sample Book" and out["structured_query"]["author"] == "Ana Example"


def test_a_printing_in_another_language_is_only_a_fallback(elefant_db, cache):
    """A cheap French Matilda-like printing first, two English ones after: the cheaper English one is the offer."""
    pages = {
        URL_PB: html(barcode="9782070000005", price="30,99&nbsp;lei", declared="30.99", language="Franceza"),
        URL_OTHER: html(barcode=OTHER_ISBN, price="61,99&nbsp;lei", declared="61.99"),
        URL_HB: html(barcode="9781222222227", price="58,00&nbsp;lei", declared="58.00"),
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)) as f:
        offer = read(cache)
    assert [c.args[0] for c in f.call_args_list] == [URL_PB, URL_OTHER, URL_HB]
    assert offer.isbn13 == "9781222222227" and offer.price_cents == 5800 and offer.other_printing


def test_another_language_is_used_when_nothing_better_is_found(elefant_db, cache):
    french = html(barcode="9782070000005", price="145,99&nbsp;lei", declared="145.99")
    stranger = html(author="Someone Else", barcode="9781222222227")
    with patch("api.offers.fetch", side_effect=lambda url: fetched(french if url == URL_PB else stranger, url)) as f:
        offer = read(cache)
    assert f.call_count == 3 and offer.isbn13 == "9782070000005" and offer.price_cents == 14599


def test_a_ranked_page_is_preferred_to_an_unranked_one(elefant_db, cache):
    pages = {
        URL_PB: html(seller=None, declared=""),
        URL_OTHER: html(barcode=OTHER_ISBN),
        URL_HB: html(barcode="9781222222227"),
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)) as f:
        offer = read(cache)
    # Same price on two ranked pages: the first one read stays the offer.
    assert f.call_count == 3 and offer.status == "ok" and offer.isbn13 == OTHER_ISBN


# ---------------------------------------------------------------- the cheapest printing (3 Nov)


def _url(slug, n):
    return f"https://www.elefant.ro/{slug}_{UUID[:-2]}{n:02d}"


@pytest.fixture
def many_db(tmp_path, monkeypatch):
    """Owl-Babies-like: several printings under one title, a board book among them."""
    import api.offers as offers
    from functools import partial

    rows = [
        (_url("the-sample-book-paperback", 1), "the sample book"),
        (_url("the-sample-book-board-book", 2), "the sample book"),
        (_url("the-sample-book-hardcover", 3), "the sample book"),
        (_url("the-sample-book-paperback", 4), "the sample book"),
        (_url("sample-book-paperback", 5), "sample book"),
        (_url("the-sample-book-hardcover", 6), "the sample book"),
        (_url("the-sample-book-paperback", 7), "the sample book"),
        (_url("the-sample-book-hardback", 8), "the sample book"),
        (_url("the-sample-book-paperback", 9), "the sample book"),
    ]
    path = tmp_path / "many.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany("INSERT INTO books VALUES('elefant',?,?,NULL,NULL,'2026-11-03')", rows)
    monkeypatch.setattr(offers, "lookup_elefant_urls", partial(offers.lookup_elefant_urls, db_path=path))
    monkeypatch.setattr(offers, "shop_is_indexed", partial(offers.shop_is_indexed, db_path=path))
    return [u for u, _ in rows]


def priced(lei, barcode, **kw):
    return html(price=f"{lei:.2f}".replace(".", ",") + "&nbsp;lei", declared=f"{lei:.2f}", barcode=barcode, **kw)


def test_board_books_are_not_candidates_unless_asked(many_db):
    from api.offers import lookup_elefant_urls as lookup

    found = lookup(TITLE)
    assert many_db[1] not in found and len(found) == 8
    # Paperbacks first, the exact title before the article variant, then hardcovers.
    assert found[:5] == [many_db[0], many_db[3], many_db[6], many_db[8], many_db[4]]


def test_the_cheapest_same_language_printing_wins(many_db, cache):
    """A big-book-priced paperback first, the cheap paperback further down: the cheap one is the offer."""
    pages = {
        many_db[0]: priced(189.99, "9781000000009"),
        many_db[3]: priced(64.99, "9781000000016"),
        many_db[6]: priced(57.99, "9781000000023"),
        many_db[8]: priced(39.99, "9782000000006", language="Franceza"),  # cheaper, but French
        many_db[4]: priced(134.99, "9781000000030"),
        many_db[7]: priced(99.00, "9781000000047"),  # the hardback, read sixth
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)) as f:
        offer = read(cache, isbn="9780999999998")
    assert f.call_count == 6
    assert offer.status == "ok" and offer.price_cents == 5799 and offer.isbn13 == "9781000000023"
    assert offer.listing_url == many_db[6] and offer.other_printing
    with patch("api.offers.fetch", side_effect=AssertionError("read again")):
        assert read(cache, isbn="9780999999998").price_cents == 5799


def test_the_asked_isbn_still_ends_the_walk(many_db, cache):
    pages = {
        many_db[0]: priced(64.99, "9781000000009"),
        many_db[3]: priced(89.99, ISBN),
        many_db[6]: priced(19.99, "9781000000023"),
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)) as f:
        offer = read(cache)
    assert [c.args[0] for c in f.call_args_list] == [many_db[0], many_db[3]]
    assert offer.isbn13 == ISBN and offer.price_cents == 8999 and not offer.other_printing


def test_a_special_format_is_skipped_unless_it_is_the_asked_book(many_db, cache, tmp_path):
    big = priced(19.99, "9781000000009", name="The Sample Book Big Book, Paperback")
    plain = priced(49.99, "9781000000016")
    pages = {many_db[0]: big, many_db[3]: plain}
    stranger = html(author="Someone Else", barcode=OTHER_ISBN)
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages.get(url, stranger), url)):
        offer = read(cache, isbn="9780999999998")
    assert offer.isbn13 == "9781000000016" and offer.price_cents == 4999
    # Asked by its own ISBN, the big book is the book.
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages.get(url, stranger), url)):
        offer = read(PageCache(tmp_path / "c3.sqlite"), isbn="9781000000009")
    assert offer.isbn13 == "9781000000009" and offer.price_cents == 1999 and not offer.other_printing


def test_the_cap_holds_with_many_printings(many_db, cache):
    from api.offers import ELEFANT_READS

    with patch("api.offers.fetch", side_effect=lambda url: fetched(priced(50.0, "9781000000009"), url)) as f:
        read(cache, isbn="9780999999998")
    assert f.call_count == ELEFANT_READS == 6
    assert many_db[1] not in [c.args[0] for c in f.call_args_list]


def test_a_503_candidate_is_skipped_once_and_the_rest_still_compared(many_db, cache):
    def answer(url):
        if url == many_db[3]:
            return fetched("<html>maintenance</html>", url, status=503)
        return fetched(priced(70.0 if url == many_db[0] else 55.0, "9781000000009" if url == many_db[0] else "9781000000016"), url)

    with patch("api.offers.fetch", side_effect=answer) as f:
        offer = read(cache, isbn="9780999999998")
    urls = [c.args[0] for c in f.call_args_list]
    assert urls.count(many_db[3]) == 1 and len(urls) == 6
    assert offer.status == "ok" and offer.price_cents == 5500


def test_a_page_named_without_the_article_is_the_same_book(elefant_db, cache):
    """Elefant names The Gruffalo 'Gruffalo': the cheaper page under that name is not passed over."""
    pages = {
        URL_PB: priced(57.99, OTHER_ISBN, name="Sample Book, Paperback"),
        URL_OTHER: priced(64.99, "9781222222227", name="Sample Book, Paperback"),
        URL_HB: priced(134.99, "9780333333334", name="The Sample Book, Hardcover"),
    }
    with patch("api.offers.fetch", side_effect=lambda url: fetched(pages[url], url)):
        offer = read(cache, isbn="9780999999998")
    assert offer.price_cents == 5799 and offer.isbn13 == OTHER_ISBN

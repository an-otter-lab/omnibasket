"""BNR conversion. The fixture is local. Nothing here opens a socket."""

from __future__ import annotations

import urllib.request
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import pytest

from matching.fx import (
    BNR_DAILY_URL,
    USER_AGENT,
    BnrFetchError,
    BnrRate,
    BnrXmlError,
    RateDisplay,
    RateTable,
    convert_to_ron_cents,
    fetch_bnr_xml,
    parse_bnr_xml,
    rate_display,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nbrfxrates.xml"
FRIDAY = date(2026, 10, 30)
THURSDAY = date(2026, 10, 29)
SATURDAY = date(2026, 10, 31)


@pytest.fixture(scope="module")
def rates() -> RateTable:
    return parse_bnr_xml(FIXTURE.read_bytes())


def _one(currency: str, rate: str, multiplier: int, day: date = FRIDAY) -> RateTable:
    return RateTable(rates=(BnrRate(currency, Decimal(rate), multiplier, day),))


class _Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self.payload
        return self.payload[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.request = None
        self.timeout = None
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        self.request = request
        self.timeout = timeout
        return _Body(self.payload)


def test_fixture_keeps_each_cube_and_the_multiplier(rates: RateTable) -> None:
    assert rates.orig_currency == "RON"
    assert rates.publishing_date == FRIDAY
    assert rates.published_dates() == (THURSDAY, FRIDAY)
    same = parse_bnr_xml(FIXTURE.read_text(encoding="utf-8"))
    assert same.published_dates() == rates.published_dates()
    eur, eur_reason = rates.quote("EUR", FRIDAY)
    huf, huf_reason = rates.quote("HUF", FRIDAY)
    assert eur_reason is None and huf_reason is None
    assert eur is not None and eur.multiplier == 1 and eur.rate == Decimal("5.0891")
    assert huf is not None and huf.multiplier == 100 and huf.rate == Decimal("1.3084")


def test_a_single_cube_is_enough() -> None:
    # The daily file publishes one Cube. The ten-day file publishes several.
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<DataSet xmlns="http://www.bnr.ro/xsd">
  <Header>
    <Publisher>National Bank of Romania</Publisher>
    <PublishingDate>2026-10-30</PublishingDate>
    <MessageType>DR</MessageType>
  </Header>
  <Body>
    <Subject>Reference rates</Subject>
    <OrigCurrency>RON</OrigCurrency>
    <Cube date="2026-10-30">
      <Rate currency="EUR">5.0891</Rate>
    </Cube>
  </Body>
</DataSet>
"""
    table = parse_bnr_xml(xml)
    result = convert_to_ron_cents(100, "EUR", table, FRIDAY)
    assert result.ron_cents == 509


def test_eur_usd_and_gbp_use_that_days_rate(rates: RateTable) -> None:
    eur = convert_to_ron_cents(100, "eur", rates, FRIDAY)
    assert eur.status == "converted"
    assert eur.ron_cents == 509
    assert eur.rate == Decimal("5.0891")
    assert eur.multiplier == 1
    assert eur.rate_date == FRIDAY
    assert eur.currency == "EUR"
    assert eur.reason is None

    usd = convert_to_ron_cents(100, "USD", rates, FRIDAY)
    assert usd.ron_cents == 438
    assert usd.rate == Decimal("4.3752")
    assert usd.multiplier == 1
    assert usd.rate_date == FRIDAY

    gbp = convert_to_ron_cents(100, "GBP", rates, FRIDAY)
    assert gbp.ron_cents == 581
    assert gbp.rate == Decimal("5.8126")
    assert gbp.multiplier == 1

    earlier = convert_to_ron_cents(100, "EUR", rates, THURSDAY)
    assert earlier.ron_cents == 508
    assert earlier.rate == Decimal("5.0800")
    assert earlier.rate_date == THURSDAY


def test_huf_uses_the_multiplier(rates: RateTable) -> None:
    # 100 forint is 10000 fillér. The quote is RON for 100 forint.
    result = convert_to_ron_cents(10_000, "HUF", rates, FRIDAY)
    assert result.status == "converted"
    assert result.ron_cents == 131
    assert result.rate == Decimal("1.3084")
    assert result.multiplier == 100
    assert result.rate_date == FRIDAY
    assert result.currency == "HUF"


def test_jpy_is_zero_decimal_and_quoted_per_hundred(rates: RateTable) -> None:
    # 100 yen. 2.9147 RON per 100 yen is 291.47 bani.
    result = convert_to_ron_cents(100, "JPY", rates, FRIDAY)
    assert result.ron_cents == 291
    assert result.multiplier == 100
    assert result.rate == Decimal("2.9147")


def test_missing_currency_is_not_ranked(rates: RateTable) -> None:
    result = convert_to_ron_cents(1999, "CHF", rates, FRIDAY)
    assert result.status == "not_ranked"
    assert result.reason == "missing_currency"
    assert result.currency == "CHF"
    assert result.ron_cents is None
    assert result.rate is None
    assert result.multiplier is None
    assert result.rate_date is None
    assert rate_display(result) is None


def test_missing_date_does_not_reuse_another_cube(rates: RateTable) -> None:
    result = convert_to_ron_cents(100, "EUR", rates, SATURDAY)
    assert result.status == "not_ranked"
    assert result.reason == "missing_date"
    assert result.ron_cents is None
    assert result.rate is None
    friday = convert_to_ron_cents(100, "EUR", rates, FRIDAY)
    assert friday.ron_cents == 509


def test_previous_banking_day_is_opt_in(rates: RateTable) -> None:
    used = convert_to_ron_cents(100, "EUR", rates, SATURDAY, allow_previous_banking_day=True)
    assert used.status == "converted"
    assert used.rate_date == FRIDAY
    assert used.ron_cents == 509
    assert used.rate == Decimal("5.0891")
    pieces = rate_display(used)
    assert pieces is not None
    assert pieces.date == "2026-10-30"

    sunday = convert_to_ron_cents(
        100, "EUR", rates, date(2026, 11, 1), allow_previous_banking_day=True
    )
    assert sunday.rate_date == FRIDAY

    before = convert_to_ron_cents(
        100, "EUR", rates, date(2026, 10, 28), allow_previous_banking_day=True
    )
    assert before.status == "not_ranked"
    assert before.reason == "missing_date"
    assert before.ron_cents is None

    exact = convert_to_ron_cents(100, "EUR", rates, FRIDAY, allow_previous_banking_day=True)
    assert exact.rate_date == FRIDAY


def test_previous_banking_day_does_not_hunt_for_the_currency(rates: RateTable) -> None:
    # KRW is on Thursday only. Saturday's previous banking day is Friday.
    thursday = convert_to_ron_cents(100, "KRW", rates, THURSDAY)
    assert thursday.status == "converted"
    assert thursday.ron_cents == 31
    saturday = convert_to_ron_cents(100, "KRW", rates, SATURDAY, allow_previous_banking_day=True)
    assert saturday.status == "not_ranked"
    assert saturday.reason == "missing_currency"
    assert saturday.ron_cents is None


def test_rounding_half_up() -> None:
    # 1.00 EUR at 2.0050 is 200.5 bani. Half-even would keep 200.
    assert convert_to_ron_cents(100, "EUR", _one("EUR", "2.0050", 1), FRIDAY).ron_cents == 201
    assert convert_to_ron_cents(100, "EUR", _one("EUR", "2.0049", 1), FRIDAY).ron_cents == 200
    assert convert_to_ron_cents(100, "EUR", _one("EUR", "2.0051", 1), FRIDAY).ron_cents == 201
    assert convert_to_ron_cents(1, "EUR", _one("EUR", "0.5000", 1), FRIDAY).ron_cents == 1
    assert convert_to_ron_cents(100, "EUR", _one("EUR", "5.0000", 1), FRIDAY).ron_cents == 500
    # 40 fillér at 1.2500 RON per 100 forint is 0.5 bani.
    assert convert_to_ron_cents(40, "HUF", _one("HUF", "1.2500", 100), FRIDAY).ron_cents == 1
    assert convert_to_ron_cents(39, "HUF", _one("HUF", "1.2500", 100), FRIDAY).ron_cents == 0


def test_half_up_ignores_a_half_even_context() -> None:
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_EVEN
        result = convert_to_ron_cents(100, "EUR", _one("EUR", "2.0050", 1), FRIDAY)
    assert result.ron_cents == 201


def test_ron_passes_through_without_a_cube() -> None:
    sunday = date(2026, 11, 1)
    empty = RateTable(rates=())
    result = convert_to_ron_cents(12345, "RON", empty, sunday)
    assert result.status == "converted"
    assert result.ron_cents == 12345
    assert result.rate == Decimal("1")
    assert result.multiplier == 1
    assert result.rate_date == sunday
    assert result.currency == "RON"
    assert result.reason is None
    assert rate_display(result) is None
    for name in ("Lei", "leu", "lei românești", "lei romanești", "  RON  "):
        same = convert_to_ron_cents(50, name, empty, sunday)
        assert same.ron_cents == 50
        assert same.currency == "RON"


def test_a_rate_with_no_known_minor_unit_is_not_ranked() -> None:
    # XAU in the BNR file is RON per gram of gold, not a book price.
    table = RateTable(rates=(BnrRate("XAU", Decimal("400.0000"), 1, FRIDAY),))
    result = convert_to_ron_cents(100, "XAU", table, FRIDAY)
    assert result.status == "not_ranked"
    assert result.reason == "unknown_minor_unit"
    assert result.ron_cents is None


@pytest.mark.parametrize(
    ("currency", "amount", "units", "shown"),
    [
        ("EUR", 100, "1", "5,0891"),
        ("USD", 100, "1", "4,3752"),
        ("GBP", 100, "1", "5,8126"),
        ("HUF", 10_000, "100", "1,3084"),
    ],
)
def test_display_pieces(
    rates: RateTable, currency: str, amount: int, units: str, shown: str
) -> None:
    pieces = rate_display(convert_to_ron_cents(amount, currency, rates, FRIDAY))
    assert pieces == RateDisplay(date="2026-10-30", units=units, currency=currency, rate=shown)


def test_eur_pieces_fill_the_offer_line(rates: RateTable) -> None:
    pieces = rate_display(convert_to_ron_cents(100, "EUR", rates, FRIDAY))
    assert pieces is not None
    line = (
        f"converted at the BNR rate of {pieces.date}: "
        f"{pieces.units} {pieces.currency} = {pieces.rate} lei"
    )
    assert line == "converted at the BNR rate of 2026-10-30: 1 EUR = 5,0891 lei"


def test_amount_must_be_a_non_negative_int(rates: RateTable) -> None:
    with pytest.raises(TypeError):
        convert_to_ron_cents(1.5, "EUR", rates, FRIDAY)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        convert_to_ron_cents(True, "EUR", rates, FRIDAY)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        convert_to_ron_cents(-1, "EUR", rates, FRIDAY)
    with pytest.raises(TypeError):
        convert_to_ron_cents(100, "EUR", rates, datetime(2026, 10, 30))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        convert_to_ron_cents(100, "€", rates, FRIDAY)


def test_parse_rejects_a_document_that_is_not_bnr() -> None:
    with pytest.raises(BnrXmlError):
        parse_bnr_xml("<rates></rates>")
    with pytest.raises(BnrXmlError):
        parse_bnr_xml(b"not xml")
    foreign = """<?xml version="1.0"?>
<DataSet xmlns="http://www.bnr.ro/xsd">
  <Header><PublishingDate>2026-10-30</PublishingDate></Header>
  <Body>
    <OrigCurrency>USD</OrigCurrency>
    <Cube date="2026-10-30"><Rate currency="EUR">1.1000</Rate></Cube>
  </Body>
</DataSet>
"""
    with pytest.raises(BnrXmlError):
        parse_bnr_xml(foreign)
    duplicate = """<?xml version="1.0"?>
<DataSet xmlns="http://www.bnr.ro/xsd">
  <Header><PublishingDate>2026-10-30</PublishingDate></Header>
  <Body>
    <OrigCurrency>RON</OrigCurrency>
    <Cube date="2026-10-30">
      <Rate currency="EUR">5.0891</Rate>
      <Rate currency="EUR">5.0800</Rate>
    </Cube>
  </Body>
</DataSet>
"""
    with pytest.raises(BnrXmlError):
        parse_bnr_xml(duplicate)


def test_fetch_is_one_https_get_with_the_omnibasket_agent() -> None:
    opener = _Opener(FIXTURE.read_bytes())
    body = fetch_bnr_xml(opener=opener)
    assert opener.calls == 1
    assert opener.timeout == 20
    request = opener.request
    assert request is not None
    assert request.full_url == BNR_DAILY_URL
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == USER_AGENT
    assert USER_AGENT == "Omnibasket/0.1 (+https://omnibasket.anottersolution.com)"
    folded = USER_AGENT.lower()
    assert "spider" not in folded
    assert "crawler" not in folded
    parsed = parse_bnr_xml(body)
    assert convert_to_ron_cents(100, "EUR", parsed, FRIDAY).ron_cents == 509

    refused = _Opener(b"")
    with pytest.raises(BnrFetchError):
        fetch_bnr_xml("http://curs.bnr.ro/nbrfxrates.xml", opener=refused)
    assert refused.calls == 0

    huge = _Opener(b"x" * (2_000_000 + 1))
    with pytest.raises(BnrFetchError):
        fetch_bnr_xml(opener=huge)
    assert huge.calls == 1


def test_parse_and_convert_do_not_touch_the_network(monkeypatch, rates: RateTable) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("fx tests must not open a socket")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    again = parse_bnr_xml(FIXTURE.read_bytes())
    assert again.published_dates() == rates.published_dates()
    assert convert_to_ron_cents(100, "EUR", again, FRIDAY).ron_cents == 509

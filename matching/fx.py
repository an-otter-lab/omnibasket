"""BNR reference rates, and one offer converted into RON cents.

The daily job fetches the XML once. Parsing and conversion take the
document they are given and do not use the network. A missing rate is
``not_ranked``: nothing is estimated, and an older cube is not used
unless ``allow_previous_banking_day`` is passed.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Literal

# Last banking day's file. On 6 Aug 2026 BNR moved these files from
# www.bnr.ro to curs.bnr.ro. The names and the schema are unchanged.
# The ten-day file is the same schema with more than one Cube.
BNR_DAILY_URL = "https://curs.bnr.ro/nbrfxrates.xml"
BNR_TEN_DAY_URL = "https://curs.bnr.ro/nbrfxrates10days.xml"
USER_AGENT = "Omnibasket/0.1 (+https://omnibasket.anottersolution.com)"

_NS = "http://www.bnr.ro/xsd"
_MAX_BYTES = 2_000_000

# ISO 4217 minor-unit exponent. ``amount_minor`` counts these.
# JPY and KRW have no smaller unit. HUF's fillér is still exponent 2,
# which is how every other price in this repo is stored. The BNR
# multiplier is a separate scale on the published quote.
# A code that is not listed is not ranked: the scale is not guessed.
# XAU and XDR are in the BNR file and are not book currencies.
_EXPONENT = {
    "AED": 2,
    "AUD": 2,
    "BGN": 2,
    "BRL": 2,
    "CAD": 2,
    "CHF": 2,
    "CNY": 2,
    "CZK": 2,
    "DKK": 2,
    "EGP": 2,
    "EUR": 2,
    "GBP": 2,
    "HUF": 2,
    "INR": 2,
    "JPY": 0,
    "KRW": 0,
    "MDL": 2,
    "MXN": 2,
    "NOK": 2,
    "NZD": 2,
    "PLN": 2,
    "RON": 2,
    "RSD": 2,
    "RUB": 2,
    "SEK": 2,
    "THB": 2,
    "TRY": 2,
    "UAH": 2,
    "USD": 2,
    "ZAR": 2,
}

# The reading layer already treats these as the same currency.
_LEI = {"lei", "leu", "ron", "lei românești", "lei romanești"}


class BnrXmlError(ValueError):
    """The document is not a usable BNR rate file."""


class BnrFetchError(RuntimeError):
    """The GET was refused before it was sent, or the body is too large."""


@dataclass(frozen=True)
class BnrRate:
    """One published quote. ``rate`` is RON for ``multiplier`` units."""

    currency: str
    rate: Decimal
    multiplier: int
    date: date

    def __post_init__(self) -> None:
        if type(self.multiplier) is not int or self.multiplier < 1:
            raise ValueError("multiplier must be an int >= 1")
        if not isinstance(self.rate, Decimal) or not self.rate.is_finite() or self.rate <= 0:
            raise ValueError("rate must be a positive Decimal")


@dataclass(frozen=True)
class RateTable:
    """Cubes from one BNR document. Lookup never invents a missing day."""

    rates: tuple[BnrRate, ...]
    publishing_date: date | None = None
    orig_currency: str = "RON"

    def __post_init__(self) -> None:
        if self.orig_currency != "RON":
            raise ValueError("orig currency must be RON")
        by_date: dict[date, dict[str, BnrRate]] = {}
        for row in self.rates:
            day = by_date.setdefault(row.date, {})
            if row.currency in day:
                raise ValueError(f"duplicate {row.currency} on {row.date.isoformat()}")
            day[row.currency] = row
        object.__setattr__(self, "_by_date", by_date)

    def published_dates(self) -> tuple[date, ...]:
        return tuple(sorted(self._by_date))

    def quote(
        self,
        currency: str,
        on_date: date,
        *,
        allow_previous_banking_day: bool = False,
    ) -> tuple[BnrRate | None, str | None]:
        """The cube for ``on_date``, or the reason it cannot be used.

        With ``allow_previous_banking_day``, the day is the latest cube
        dated on or before ``on_date``. The currency is read from that
        cube only. An older cube is not searched for a missing code.
        """
        if allow_previous_banking_day:
            days = [day for day in self._by_date if day <= on_date]
            if not days:
                return None, "missing_date"
            day = max(days)
        elif on_date not in self._by_date:
            return None, "missing_date"
        else:
            day = on_date
        row = self._by_date[day].get(currency)
        if row is None:
            return None, "missing_currency"
        return row, None


@dataclass(frozen=True)
class Conversion:
    """RON cents for one offer, or ``not_ranked`` when no rate may be used.

    ``ron_cents`` is None when the offer is not ranked. No field carries
    an estimated amount. ``reason`` is None, ``missing_date``,
    ``missing_currency``, or ``unknown_minor_unit``.
    """

    status: Literal["converted", "not_ranked"]
    ron_cents: int | None
    rate: Decimal | None
    multiplier: int | None
    rate_date: date | None
    currency: str
    reason: str | None = None


@dataclass(frozen=True)
class RateDisplay:
    """Slots for the line the offer and the order show.

    The words stay in the UI: "converted at the BNR rate of {date}:
    {units} {currency} = {rate} lei". ``rate`` uses a Romanian decimal
    comma and the published precision. ``units`` is 1, or the BNR
    multiplier when the quote is per 100 (HUF, JPY, KRW). ``date`` is
    the cube date, ISO-8601.
    """

    date: str
    units: str
    currency: str
    rate: str


def parse_bnr_xml(xml: str | bytes) -> RateTable:
    """Parse one nbrfxrates document. The rate date is the Cube date.

    ``multiplier`` defaults to 1. When BNR sets it (HUF, JPY and KRW are
    quoted per 100), the rate is RON for that many units, not for one.
    """
    if isinstance(xml, str):
        data = xml.encode("utf-8")
    elif isinstance(xml, bytes):
        data = xml
    else:
        raise TypeError("BNR XML must be str or bytes")
    if len(data) > _MAX_BYTES:
        raise BnrXmlError("BNR XML is larger than 2 MiB")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BnrXmlError("BNR XML is not well-formed") from exc
    if root.tag != f"{{{_NS}}}DataSet":
        raise BnrXmlError("BNR XML root is not DataSet in the BNR namespace")

    header = _required(root, "Header")
    publishing = _iso_date(_required_text(header, "PublishingDate"), "PublishingDate")
    body = _required(root, "Body")
    orig = _required_text(body, "OrigCurrency")
    if orig != "RON":
        raise BnrXmlError(f"BNR orig currency is {orig}, not RON")

    cubes = body.findall(f"{{{_NS}}}Cube")
    if not cubes:
        raise BnrXmlError("BNR XML has no Cube")
    rows: list[BnrRate] = []
    seen_dates: set[date] = set()
    for cube in cubes:
        raw_day = cube.get("date")
        if not raw_day:
            raise BnrXmlError("BNR Cube is missing a date")
        day = _iso_date(raw_day.strip(), "Cube date")
        if day in seen_dates:
            raise BnrXmlError(f"duplicate Cube date {day.isoformat()}")
        seen_dates.add(day)
        rate_els = list(cube.findall(f"{{{_NS}}}Rate"))
        if not rate_els:
            raise BnrXmlError(f"BNR Cube {day.isoformat()} has no Rate")
        seen_codes: set[str] = set()
        for el in rate_els:
            row = _rate(el, day)
            if row.currency in seen_codes:
                raise BnrXmlError(f"duplicate {row.currency} on {day.isoformat()}")
            seen_codes.add(row.currency)
            rows.append(row)
    return RateTable(rates=tuple(rows), publishing_date=publishing, orig_currency=orig)


def fetch_bnr_xml(
    url: str = BNR_DAILY_URL,
    *,
    timeout: float = 20,
    opener=None,
) -> bytes:
    """GET one BNR rate file and return the body. One attempt.

    The daily job calls this, then ``parse_bnr_xml`` on the body.
    Pass ``opener`` only to stand in for the network. urllib raises
    ``URLError`` when the host refuses the call.
    """
    if not url.startswith("https://"):
        raise BnrFetchError("BNR rates are fetched over https")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, text/xml",
        },
        method="GET",
    )
    open_url = urllib.request.urlopen if opener is None else opener.open
    with open_url(request, timeout=timeout) as response:
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise BnrFetchError("BNR response is larger than 2 MiB")
    return body


def convert_to_ron_cents(
    amount_minor: int,
    currency: str,
    rates: RateTable,
    on_date: date,
    *,
    allow_previous_banking_day: bool = False,
) -> Conversion:
    """Convert one price into RON cents at the BNR cube for ``on_date``.

    ``amount_minor`` is the ISO 4217 minor unit (euro cents, fillér, yen).
    Arithmetic is ``Decimal`` with ``ROUND_HALF_UP``. RON is returned
    unchanged and does not consult a cube.

    Any other currency needs a published rate for that cube. There is no
    estimate and no silent use of an older day.

    ``allow_previous_banking_day`` defaults to off. When it is on, a
    weekend or holiday uses the latest cube dated on or before ``on_date``
    that is actually in ``rates``. ``rate_date`` is that cube's date.
    A currency missing from that cube is still not ranked.
    """
    if type(amount_minor) is not int:
        raise TypeError("amount_minor must be an int")
    if amount_minor < 0:
        raise ValueError("amount_minor must be >= 0")
    if type(on_date) is not date:
        raise TypeError("on_date must be a datetime.date")
    if not isinstance(rates, RateTable):
        raise TypeError("rates must be a RateTable")

    code = _currency(currency)
    if code == "RON":
        return Conversion(
            status="converted",
            ron_cents=amount_minor,
            rate=Decimal("1"),
            multiplier=1,
            rate_date=on_date,
            currency="RON",
            reason=None,
        )

    row, reason = rates.quote(
        code,
        on_date,
        allow_previous_banking_day=allow_previous_banking_day,
    )
    if row is None:
        return _not_ranked(code, reason)
    exponent = _EXPONENT.get(code)
    if exponent is None:
        return _not_ranked(code, "unknown_minor_unit")
    return Conversion(
        status="converted",
        ron_cents=_ron_cents(amount_minor, row.rate, row.multiplier, exponent),
        rate=row.rate,
        multiplier=row.multiplier,
        rate_date=row.date,
        currency=code,
        reason=None,
    )


def rate_display(conversion: Conversion) -> RateDisplay | None:
    """String pieces for a converted foreign price.

    None for RON, which was not converted, and for an offer that is
    not ranked, which has no rate to print.
    """
    if conversion.status != "converted" or conversion.currency == "RON":
        return None
    if conversion.rate is None or conversion.multiplier is None or conversion.rate_date is None:
        return None
    return RateDisplay(
        date=conversion.rate_date.isoformat(),
        units=str(conversion.multiplier),
        currency=conversion.currency,
        rate=format(conversion.rate, "f").replace(".", ","),
    )


def _not_ranked(currency: str, reason: str | None) -> Conversion:
    return Conversion(
        status="not_ranked",
        ron_cents=None,
        rate=None,
        multiplier=None,
        rate_date=None,
        currency=currency,
        reason=reason,
    )


def _currency(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("currency must be a string")
    text = " ".join(value.strip().split())
    if text.lower() in _LEI:
        return "RON"
    code = text.upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError("currency must be an ISO 4217 code")
    return code


def _ron_cents(amount_minor: int, rate: Decimal, multiplier: int, exponent: int) -> int:
    """RON cents. The caller's decimal context does not choose the rounding."""
    # Published rate is RON for `multiplier` units. Minor units scale by 10^exponent.
    numerator = Decimal(amount_minor) * rate * Decimal(100)
    denominator = Decimal(multiplier) * (Decimal(10) ** exponent)
    with localcontext() as ctx:
        ctx.prec = max(50, ctx.prec)
        ctx.rounding = ROUND_HALF_UP
        cents = (numerator / denominator).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _required(parent: ET.Element, name: str) -> ET.Element:
    child = parent.find(f"{{{_NS}}}{name}")
    if child is None:
        raise BnrXmlError(f"BNR XML is missing {name}")
    return child


def _required_text(parent: ET.Element, name: str) -> str:
    child = _required(parent, name)
    if child.text is None or not child.text.strip():
        raise BnrXmlError(f"BNR XML {name} is empty")
    return child.text.strip()


def _iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BnrXmlError(f"BNR {label} is not a date") from exc


def _rate(el: ET.Element, day: date) -> BnrRate:
    code = el.get("currency")
    if (
        code is None
        or len(code) != 3
        or not code.isascii()
        or not code.isalpha()
        or code != code.upper()
    ):
        raise BnrXmlError("BNR Rate currency is not a 3-letter code")
    raw_mult = el.get("multiplier")
    if raw_mult is None:
        multiplier = 1
    else:
        try:
            multiplier = int(raw_mult.strip())
        except ValueError as exc:
            raise BnrXmlError(f"BNR multiplier for {code} is not an integer") from exc
        if multiplier < 1:
            raise BnrXmlError(f"BNR multiplier for {code} is below 1")
    if el.text is None or not el.text.strip():
        raise BnrXmlError(f"BNR rate for {code} is empty")
    try:
        rate = Decimal(el.text.strip())
    except InvalidOperation as exc:
        raise BnrXmlError(f"BNR rate for {code} is not a decimal") from exc
    return BnrRate(currency=code, rate=rate, multiplier=multiplier, date=day)


__all__ = [
    "BNR_DAILY_URL",
    "BNR_TEN_DAY_URL",
    "USER_AGENT",
    "BnrFetchError",
    "BnrRate",
    "BnrXmlError",
    "Conversion",
    "RateDisplay",
    "RateTable",
    "convert_to_ron_cents",
    "fetch_bnr_xml",
    "parse_bnr_xml",
    "rate_display",
]

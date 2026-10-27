"""One-shot page reads. A 410 or a challenge is a cache miss, not a retry.

eMAG is refused in a headless browser. Nothing in this module changes
headers, waits out a wall, or calls the fetcher a second time.
"""

from __future__ import annotations

from dataclasses import dataclass

from matching import match_offers, validate_extraction
from spike.extract import detect_block


class LiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    http_status: int | None
    text: str
    title: str
    challenge_overlay: bool
    screenshot_path: str | None = None
    model: dict | None = None
    final_url: str | None = None


@dataclass(frozen=True)
class ReadReport:
    store_id: str
    isbn13: str
    item_id: str
    status: str
    cache: str
    reason: str | None
    http_status: int | None
    attempts: int
    validated: dict | None = None
    validation: dict | None = None
    editions: dict | None = None


def read_page(
    *,
    store_id: str,
    isbn13: str,
    item_id: str,
    headless: bool,
    fetcher,
) -> ReadReport:
    """Read one page. ``fetcher`` is called at most once, and never after a block."""

    if store_id == "emag" and headless:
        return ReadReport(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="failed",
            cache="miss",
            reason="emag_requires_visible_browser",
            http_status=None,
            attempts=0,
        )

    fetched = fetcher()
    if not isinstance(fetched, FetchResult):
        raise LiveError("fetcher must return one FetchResult")

    blocked = _blocked(fetched)
    if blocked:
        return ReadReport(
            store_id=store_id,
            isbn13=isbn13,
            item_id=item_id,
            status="failed",
            cache="miss",
            reason=blocked,
            http_status=fetched.http_status,
            attempts=1,
        )

    validated = None
    verdict = None
    editions = None
    if isinstance(fetched.model, dict):
        validated, verdict = validate_extraction(fetched.model)
        editions = match_offers([validated], "strict_isbn", isbn13 or None)
        if not verdict["accepted"]:
            return ReadReport(
                store_id=store_id,
                isbn13=isbn13,
                item_id=item_id,
                status="failed",
                cache="miss",
                reason="extraction_rejected:" + ",".join(verdict["reasons"]),
                http_status=fetched.http_status,
                attempts=1,
                validated=validated,
                validation=verdict,
                editions=editions,
            )

    return ReadReport(
        store_id=store_id,
        isbn13=isbn13,
        item_id=item_id,
        status="ok",
        cache="live",
        reason=None,
        http_status=fetched.http_status,
        attempts=1,
        validated=validated,
        validation=verdict,
        editions=editions,
    )


def _blocked(fetched: FetchResult) -> str | None:
    if fetched.http_status == 410:
        return "http_410"
    if fetched.challenge_overlay:
        return "challenge_overlay"
    return detect_block(fetched.http_status, fetched.text, fetched.title)

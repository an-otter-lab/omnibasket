"""S9: progress lines carry the real status; eMAG is not "ok" when it was not checked."""

import asyncio
from unittest.mock import patch

from api.cache import PageCache
from api.offers import OfferRead, ReadProgress, _read_one_page, progress_message

ISBN = "9780142402535"


def test_no_raw_status_in_progress_text():
    assert progress_message("bookzone", "not_checked") == "Bookzone: not checked"
    assert "_" not in progress_message("emag", "not_checked")
    assert progress_message("libris", "ok") == "Libris: read"


def _run(tmp_path, status):
    seen: list[ReadProgress] = []

    async def fake(store_id, isbn13, item_id, *a, **k):
        return OfferRead(store_id=store_id, isbn13=isbn13, item_id=item_id, status=status, cache="miss", day="2026-10-31")

    with patch("api.offers._fetch_and_extract", fake):
        asyncio.run(_read_one_page("emag", ISBN, "b", PageCache(tmp_path / "c.sqlite"), progress_callback=seen.append))
    return [p for p in seen if p.status != "reading"]


def test_emag_not_checked_is_said_as_such(tmp_path):
    (last,) = _run(tmp_path, "not_checked")
    assert last.status == "not_checked"
    assert last.message == "eMAG: not checked"


def test_emag_skipped_is_not_ok(tmp_path):
    (last,) = _run(tmp_path, "skipped")
    assert last.status == "skipped"


def test_emag_read_is_ok(tmp_path):
    (last,) = _run(tmp_path, "ok")
    assert last.status == "ok"

"""Repo-wide test default: the existing suite exercises the sample basket, so it runs in demo mode.
Set at import so module-scoped fixtures see it. Tests of normal mode remove the variable themselves."""

import os

os.environ["OMNIBASKET_DEMO"] = "1"


import pytest


@pytest.fixture(autouse=True)
def _elefant_index_is_empty(tmp_path_factory, monkeypatch):
    """Elefant's title lookup never reads the gitignored data/index: a test that wants Elefant
    candidates points it at its own index (tests/test_elefant.py)."""
    from functools import partial

    import api.offers as offers

    empty = tmp_path_factory.getbasetemp() / "no-index.sqlite3"
    monkeypatch.setattr(offers, "lookup_elefant_urls", partial(offers.lookup_elefant_urls, db_path=empty))

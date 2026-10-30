"""Ask: 'no Amazon' maps to the exclude chip, honestly says when the shop is absent."""
from api import ask

NAMES = {"stores": {"libris": "Libris", "emag": "eMAG", "amazon_de": "Amazon.de", "books_express": "Books-Express"},
         "memberships": {}}


def state(ids):
    return {"tab": "cheapest", "selected_store_ids": None, "memberships": [], "edition_pins": {},
            "store_ids": ids, "membership_ids": [], "items": []}


FULL = ["libris", "books_express", "amazon_de", "emag"]


def no_muse(*a, **k):
    return {"actions": []}


def run(text, ids):
    return ask.answer(text, "en", state(ids), muse=no_muse, names=NAMES).as_response()


def test_no_amazon_with_amazon_in_data():
    r = run("no Amazon", FULL)
    assert r["status"] == "ok"
    assert r["actions"] == [{"name": "exclude_store", "args": {"store_id": "amazon_de"}}]
    assert r["reply_key"] == "askDoneExclude" and r["reply_args"] == {"shop": "Amazon.de"}


def test_no_amazon_without_amazon_is_honest():
    r = run("no Amazon", ["libris", "emag"])
    assert r["status"] == "unsupported" and r["actions"] == []
    assert r["reply_key"] == "askNotInBasket" and r["reply_args"] == {"shop": "Amazon.de"}


def test_combined_phrase_applies_both():
    r = run("no Amazon, and keep it to one order", FULL)
    assert r["status"] == "ok"
    assert r["actions"] == [{"name": "exclude_store", "args": {"store_id": "amazon_de"}},
                            {"name": "set_tab", "args": {"tab": "one"}}]
    assert [x["reply_key"] for x in r["replies"]] == ["askDoneExclude", "askDoneTab"]


def test_nonsense_still_unsupported():
    for text in ("no Zorgblatt", "make me a sandwich"):
        r = run(text, FULL)
        assert r["status"] == "unsupported" and r["reply_key"] == "askUnsupported"

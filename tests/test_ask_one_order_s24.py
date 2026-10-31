"""S24: 'one order' on a basket no single shop can fill says so, on the Muse path and the fast path."""
from api import ask

NAMES = {"stores": {"libris": "Libris", "emag": "eMAG", "amazon_de": "Amazon.de"}, "memberships": {}}


def state(ids, sets):
    return {"tab": "cheapest", "selected_store_ids": None, "memberships": [], "edition_pins": {},
            "store_ids": ids, "membership_ids": [],
            "items": [{"item_id": f"b{i}", "editions": [], "store_ids": s} for i, s in enumerate(sets)]}


IMPOSSIBLE = state(["libris", "emag", "amazon_de"], [["libris"], ["emag"]])
POSSIBLE = state(["libris", "emag", "amazon_de"], [["libris", "emag"], ["emag"]])
ONE = {"name": "set_tab", "args": {"tab": "one"}}
NO_AMAZON = {"name": "exclude_store", "args": {"store_id": "amazon_de"}}


def muse_says(*actions):
    calls = []

    def muse(*a, **k):
        calls.append(a)
        return {"actions": list(actions)}
    muse.calls = calls
    return muse


def test_muse_one_order_impossible_says_so():
    muse = muse_says(ONE)
    r = ask.answer("aș vrea să plătesc o singură livrare", "ro", IMPOSSIBLE, muse=muse, names=NAMES).as_response()
    assert len(muse.calls) == 1  # this phrasing is the Muse path
    assert r["status"] == "unsupported" and r["actions"] == []
    assert r["reply_key"] == "askOneNotPossible"


def test_muse_one_order_possible_still_switches():
    r = ask.answer("aș vrea să plătesc o singură livrare", "ro", POSSIBLE, muse=muse_says(ONE), names=NAMES).as_response()
    assert r["status"] == "ok" and r["actions"] == [ONE] and r["reply_key"] == "askDoneTab"


def test_muse_other_action_kept_one_order_refused():
    r = ask.answer("fără Amazon și o singură livrare", "ro", IMPOSSIBLE, muse=muse_says(NO_AMAZON, ONE), names=NAMES).as_response()
    assert r["status"] == "ok" and r["actions"] == [NO_AMAZON]
    assert [x["reply_key"] for x in r["replies"]] == ["askDoneExclude", "askOneNotPossible"]


def test_fast_path_one_order_impossible_says_so():
    r = ask.answer("keep it to one order", "en", IMPOSSIBLE, muse=muse_says(), names=NAMES).as_response()
    assert r["status"] == "unsupported" and r["reply_key"] == "askOneNotPossible"


def test_unknown_shop_lists_unchanged():
    st = dict(IMPOSSIBLE, items=[{"item_id": "b0", "editions": []}])
    r = ask.answer("keep it to one order", "en", st, muse=muse_says(), names=NAMES).as_response()
    assert r["status"] == "ok" and r["actions"] == [ONE]

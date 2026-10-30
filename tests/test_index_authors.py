import json
import sqlite3
from email.message import Message

search_module = __import__("index.search", fromlist=["search"])
authors = __import__("index.authors", fromlist=["x"])
from tests.test_index_search import make_db


class Resp:
    def __init__(self, payload, raw=None, status=200):
        self.payload, self.raw, self.status, self.headers = payload, raw, status, Message()
    def __enter__(self): return self
    def __exit__(self, *a): return None
    def read(self, size=-1): return self.raw if self.raw is not None else json.dumps(self.payload).encode()


class Opener:
    def __init__(self, authors_docs, works=None, mode="ok"):
        self.calls, self.docs, self.works, self.mode = [], authors_docs, works or {}, mode
    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        assert timeout == 3 and url.startswith("https://openlibrary.org/")
        if self.mode == "500":
            raise OSError("HTTP 500")
        if self.mode == "bad":
            return Resp(None, raw=b"{not json")
        if "search/authors.json" in url:
            return Resp({"docs": self.docs})
        if "search.json" in url:
            return Resp({"docs": []})
        oid = url.split("/authors/")[1].split("/")[0]
        return Resp({"entries": [{"title": t} for t in self.works.get(oid, [])]})


ROWS = [
    ("libris", "https://libris.ro/p/1", "Matilda", "roald-dahl", None),
    ("emag", "https://emag.ro/carte/2", "the bfg", None, None),
    ("libris", "https://libris.ro/p/3", "Matilda", "Jane Real", None),
    ("libris", "https://libris.ro/p/4", "Cartea nuntii", None, None),
]


def dahl():
    return Opener([{"key": "/authors/OL1A", "name": "Roald Dahl"}], {"OL1A": ["Matilda", "The BFG"]})


def authors_of(path):
    with sqlite3.connect(path) as db:
        return [r[0] for r in db.execute("SELECT author_hint FROM books ORDER BY rowid")]


def test_hit_writes_author_and_cache_hit_makes_no_calls(tmp_path):
    p = tmp_path / "b.sqlite3"; make_db(p, ROWS)
    op = dahl()
    res = search_module.search("roald dahl", db_path=p, opener=op)
    assert len([c for c in op.calls if "/authors" in c]) == 2
    assert authors_of(p)[:2] == ["Roald Dahl", "Roald Dahl"]
    assert authors_of(p)[2] == "Jane Real"  # sitemap author never overwritten
    assert {r["title"] for r in res} == {"Matilda", "the bfg"}
    op2 = dahl()
    search_module.search("roald dahl", db_path=p, opener=op2)
    assert [c for c in op2.calls if "authors" in c] == []


def test_cache_hit_second_call_zero_author_calls_even_when_rows_unmatched(tmp_path):
    p = tmp_path / "b.sqlite3"; make_db(p, ROWS)
    op = Opener([{"key": "/authors/OL9A", "name": "Nobody Known"}], {"OL9A": ["Not In Index"]})
    search_module.search("nobody known", db_path=p, opener=op)
    first = len(op.calls)
    search_module.search("nobody known", db_path=p, opener=op)
    assert len([c for c in op.calls[first:] if "authors" in c]) == 0


def test_miss_cached_and_results_unchanged(tmp_path):
    p = tmp_path / "b.sqlite3"; make_db(p, ROWS)
    op = Opener([])
    assert search_module.search("zzz qqq", db_path=p, opener=op) == []
    n = len(op.calls)
    assert n == 1
    search_module.search("zzz qqq", db_path=p, opener=op)
    assert len(op.calls) == n
    with sqlite3.connect(p) as db:
        assert db.execute("SELECT status FROM author_cache").fetchone()[0] == "miss"
    assert authors_of(p) == ["roald-dahl", None, "Jane Real", None]


def test_open_library_500_and_malformed_json_leave_search_intact(tmp_path):
    for mode in ("500", "bad"):
        p = tmp_path / (mode + ".sqlite3"); make_db(p, ROWS)
        op = Opener([], mode=mode)
        res = search_module.search("matilda", db_path=p, opener=op)
        assert {r["title"] for r in res} == {"Matilda"}
        assert authors_of(p) == ["roald-dahl", None, "Jane Real", None]
        assert len([c for c in op.calls if "authors" in c]) <= 3


def test_diacritics_eliade(tmp_path):
    p = tmp_path / "b.sqlite3"
    make_db(p, [("libris", "https://libris.ro/p/9", "Şarpele", "mircea-eliade", None),
                ("libris", "https://libris.ro/p/8", "Maitreyi Devi", None, None)])
    op = Opener([{"key": "/authors/OL2A", "name": "Mircea Eliade"}], {"OL2A": ["Șarpele", "Maitreyi devi"]})
    res = search_module.search("eliade mircea", db_path=p, opener=op)
    assert len(res) == 2 and all(r["author"] == "Mircea Eliade" for r in res)
    assert authors.is_slug("mircea-eliade") and not authors.is_slug("Mircea Eliade")


def test_two_authors_sharing_surname_picks_matching_one(tmp_path):
    p = tmp_path / "b.sqlite3"
    make_db(p, [("libris", "https://libris.ro/p/1", "Alpha Book", None, None),
                ("libris", "https://libris.ro/p/2", "Beta Book", None, None)])
    op = Opener([{"key": "/authors/OL3A", "name": "Ion Smith"}, {"key": "/authors/OL4A", "name": "Anna Smith"}],
                {"OL3A": ["Alpha Book"], "OL4A": ["Beta Book"]})
    search_module.search("anna smith", db_path=p, opener=op)
    assert authors_of(p) == [None, "Anna Smith"]

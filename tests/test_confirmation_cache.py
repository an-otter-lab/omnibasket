"""A Libris confirmation is fetched once and reused by every later pick of the same work."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api import fetch_guard
from api.cache import PageCache, CONFIRMATION_TTL
from api.offers import read_offers_parallel

TITLE = "Harry Potter si piatra filosofala"
AUTHOR = "J. K. Rowling"
HITS: list[str] = []


def _page(name, isbn, price):
    ld = {"@context": "https://schema.org", "@type": ["Product", "Book"], "name": name, "isbn": isbn,
          "author": [{"@type": "Person", "name": "J.K. Rowling"}],
          "offers": {"@type": "Offer", "price": price, "priceCurrency": "RON",
                     "availability": "https://schema.org/InStock"}}
    return ('<html><script type="application/ld+json">' + json.dumps(ld) + "</script></html>").encode()


PAGES = {
    "/carte/hp1": _page("Harry Potter si piatra filosofala - J.K. Rowling", "9786303218243", "56.62"),
    "/carte/hp2": _page("Harry Potter si camera secretelor - J.K. Rowling", "9786303218250", "60.00"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        body = PAGES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body or b"")))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body or b"")

    def log_message(self, *a):
        pass


@pytest.fixture(autouse=True)
def _no_network():
    """Override the project-wide no-network autouse: these tests use real loopback sockets."""
    yield


@pytest.fixture
def server(monkeypatch):
    real = fetch_guard.address_reason
    monkeypatch.setattr(fetch_guard, "address_reason", lambda ip: None if ip == "127.0.0.1" else real(ip))
    monkeypatch.setattr(fetch_guard, "_resolve_host", lambda host: ["127.0.0.1"])
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    monkeypatch.setattr(fetch_guard, "_ALLOWED_PORTS", frozenset({80, 443, port}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    HITS.clear()
    yield f"http://localhost:{port}"
    srv.shutdown()


def pick(cache, base, path, isbn, title):
    return asyncio.run(read_offers_parallel(
        ["libris"], isbn, "book-" + isbn, cache, index_lookup=lambda s, i: None,
        title=title, author=AUTHOR, title_lookup=lambda s, t, a: base + path))[0]


def test_three_picks_of_one_book_fetch_once(server, tmp_path):
    cache = PageCache(tmp_path / "c.sqlite")
    offers = [pick(cache, server, "/carte/hp1", "9789735832940", TITLE) for _ in range(3)]
    assert len(HITS) == 1
    assert [o.price_cents for o in offers] == [5662, 5662, 5662]
    assert all(o.status == "ok" and o.other_printing and o.isbn13 == "9786303218243" for o in offers)
    assert [o.cache for o in offers] == ["live", "hit", "hit"]


def test_different_book_still_fetches_and_matches_on_its_own(server, tmp_path):
    cache = PageCache(tmp_path / "c.sqlite")
    pick(cache, server, "/carte/hp1", "9789735832940", TITLE)
    pick(cache, server, "/carte/hp1", "9789735832940", TITLE)
    assert len(HITS) == 1
    other = pick(cache, server, "/carte/hp2", "9789735832957", "Harry Potter si camera secretelor")
    assert len(HITS) == 2 and other.price_cents == 6000 and other.isbn13 == "9786303218250"
    pick(cache, server, "/carte/hp2", "9789735832957", "Harry Potter si camera secretelor")
    assert len(HITS) == 2


def test_confirmation_expires(server, tmp_path):
    cache = PageCache(tmp_path / "c.sqlite")
    cache.put_confirmation("k", {"matched": False}, now=1000.0)
    assert cache.get_confirmation("k", now=1000.0 + CONFIRMATION_TTL - 1) == {"matched": False}
    assert cache.get_confirmation("k", now=1000.0 + CONFIRMATION_TTL + 1) is None

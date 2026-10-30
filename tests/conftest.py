"""No test opens a socket. A connect attempt fails the test."""

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(self, *args, **kwargs):
        raise AssertionError("test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield


@pytest.fixture
def indexed_shops_db(tmp_path, monkeypatch):
    """Minimal stand-in for the gitignored data/index/books.sqlite3 (same books table the code queries).

    Libris and Books Express have rows; every other shop has none. Points api.offers at it,
    so the tests pass on a clone with no data/index.
    """
    import sqlite3
    from functools import partial

    import api.offers as offers

    path = tmp_path / "books.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url))")
        db.executemany(
            "INSERT INTO books VALUES(?,?,?,?,?,?)",
            [
                ("libris", "https://www.libris.ro/carte/ghici/21197307", "ghici", None, "9786068996011", "2026-10-30"),
                ("books-express", "https://www.books-express.ro/ghici/p/x,9786068996011", "ghici", None, "9786068996011", "2026-10-30"),
            ],
        )
    monkeypatch.setattr(offers, "shop_is_indexed", partial(offers.shop_is_indexed, db_path=path))
    return path

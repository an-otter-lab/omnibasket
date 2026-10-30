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

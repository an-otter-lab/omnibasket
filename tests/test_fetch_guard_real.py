"""fetch_guard against REAL local servers (no mocks), plus an opt-in live smoke.

Both servers send `Connection: close`. The guard's production policy is kept;
tests only widen the port allow-list and the address check for 127.0.0.1.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api import fetch_guard

BODY = b"<html><body>" + b"hello omnibasket " * 5000 + b"</body></html>"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Connection", "close")
        if self.path.startswith("/chunked"):
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, len(BODY), 7000):
                piece = BODY[i : i + 7000]
                self.wfile.write(b"%x\r\n" % len(piece) + piece + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
        self.close_connection = True


@pytest.fixture(autouse=True)
def _no_network():
    """Override the project-wide no-network autouse for this module.

    The conftest.py blocks every socket.connect. These tests need real
    loopback sockets; production policy is kept intact by the guard itself.
    """

    yield


@pytest.fixture
def loopback(monkeypatch):
    real = fetch_guard.address_reason
    monkeypatch.setattr(
        fetch_guard, "address_reason", lambda ip: None if ip == "127.0.0.1" else real(ip)
    )
    monkeypatch.setattr(fetch_guard, "_resolve_host", lambda host: ["127.0.0.1"])
    # Production still refuses loopback:
    assert real("127.0.0.1") == "loopback"


def _serve(tls_ctx=None):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    if tls_ctx is not None:
        srv.socket = tls_ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def plain(monkeypatch, loopback):
    srv = _serve()
    port = srv.server_address[1]
    monkeypatch.setattr(fetch_guard, "_ALLOWED_PORTS", frozenset({80, 443, port}))
    yield port
    srv.shutdown()


@pytest.fixture
def tls(monkeypatch, loopback, tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl missing")
    key, crt = str(tmp_path / "k.pem"), str(tmp_path / "c.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
         "-out", crt, "-days", "1", "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost"],
        check=True, capture_output=True,
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(crt, key)
    srv = _serve(server_ctx)
    port = srv.server_address[1]
    client_ctx = ssl.create_default_context(cafile=crt)
    monkeypatch.setattr(fetch_guard, "_tls_context", lambda: client_ctx)
    monkeypatch.setattr(fetch_guard, "_ALLOWED_PORTS", frozenset({80, 443, port}))
    yield port
    srv.shutdown()


@pytest.mark.parametrize("kind", ["length", "chunked"])
def test_plain_connection_close(plain, kind):
    r = fetch_guard.fetch(f"http://localhost:{plain}/{kind}")
    assert r.status == 200 and r.body == BODY


@pytest.mark.parametrize("kind", ["length", "chunked"])
def test_tls_connection_close(tls, kind):
    r = fetch_guard.fetch(f"https://localhost:{tls}/{kind}")
    assert r.status == 200 and r.body == BODY


@pytest.mark.parametrize("kind", ["length", "chunked"])
def test_byte_cap_still_enforced(plain, kind):
    with pytest.raises(fetch_guard.FetchRefused) as e:
        fetch_guard.fetch(f"http://localhost:{plain}/{kind}", max_bytes=1000)
    assert e.value.reason == "too_large"


def test_production_policy_still_refuses_loopback_and_ports():
    with pytest.raises(fetch_guard.FetchRefused) as e:
        fetch_guard.fetch("http://127.0.0.1/")
    assert e.value.reason == "loopback"
    with pytest.raises(fetch_guard.FetchRefused) as e:
        fetch_guard.fetch("http://example.com:8080/")
    assert e.value.reason == "port"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OMNIBASKET_LIVE"), reason="set OMNIBASKET_LIVE=1")
@pytest.mark.parametrize(
    "url",
    ["https://www.libris.ro/", "https://www.books-express.ro/"],
)
def test_live_smoke(url):
    r = fetch_guard.fetch(url)
    assert r.status == 200 and len(r.body) > 1000

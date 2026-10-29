"""Pasted-link fetch guard. No test resolves a name or opens a real socket."""

from __future__ import annotations

import io
import socket
import ssl

import pytest

from api import fetch_guard as guard
from api.fetch_guard import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_S,
    MAX_REDIRECTS,
    USER_AGENT,
    FetchRefused,
    address_reason,
    fetch,
)

_REAL_CONNECT = guard._connect_pinned
_REAL_RESOLVE = guard._resolve_host

# (address, reason). IPv4-mapped forms are judged as the inner IPv4 address.
REFUSED_ADDRESSES = [
    ("127.0.0.1", "loopback"),
    ("127.0.0.2", "loopback"),
    ("::1", "loopback"),
    ("10.0.0.1", "private"),
    ("10.255.255.255", "private"),
    ("172.16.0.1", "private"),
    ("172.31.255.255", "private"),
    ("192.168.1.1", "private"),
    ("192.0.2.1", "private"),
    ("0.1.2.3", "private"),
    ("2001:db8::1", "private"),
    ("169.254.169.254", "metadata"),
    ("169.254.1.1", "link_local"),
    ("fe80::1", "link_local"),
    ("fe80::1%en0", "link_local"),
    ("224.0.0.1", "multicast"),
    ("ff02::1", "multicast"),
    ("240.0.0.1", "reserved"),
    ("255.255.255.255", "reserved"),
    ("fec0::1", "reserved"),
    ("64:ff9b::8.8.8.8", "reserved"),
    ("0.0.0.0", "unspecified"),
    ("::", "unspecified"),
    ("100.64.0.1", "cgnat"),
    ("100.127.255.255", "cgnat"),
    ("fc00::1", "ula"),
    ("fd12:3456::1", "ula"),
    ("::ffff:127.0.0.1", "loopback"),
    ("::ffff:10.0.0.1", "private"),
    ("::ffff:192.168.0.1", "private"),
    ("::ffff:169.254.169.254", "metadata"),
    ("::ffff:169.254.1.1", "link_local"),
    ("::ffff:224.0.0.1", "multicast"),
    ("::ffff:240.0.0.1", "reserved"),
    ("::ffff:0.0.0.0", "unspecified"),
    ("::ffff:100.64.0.1", "cgnat"),
]

LITERAL_ADDRESSES = [row for row in REFUSED_ADDRESSES if "%" not in row[0]]

# (address, address the socket must use)
ALLOWED_ADDRESSES = [
    ("1.1.1.1", "1.1.1.1"),
    ("8.8.8.8", "8.8.8.8"),
    ("100.63.255.255", "100.63.255.255"),
    ("100.128.0.1", "100.128.0.1"),
    ("172.15.255.255", "172.15.255.255"),
    ("172.32.0.1", "172.32.0.1"),
    ("11.0.0.1", "11.0.0.1"),
    ("2606:4700:4700::1111", "2606:4700:4700::1111"),
    ("::ffff:8.8.8.8", "8.8.8.8"),
]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network is not used from tests")

    monkeypatch.setattr(guard, "_resolve_host", blocked)
    monkeypatch.setattr(guard, "_connect_pinned", blocked)


class Page:
    def __init__(self, status=200, headers=None, body=b"", chunks=None):
        self.status = status
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}
        self._chunks = list(chunks) if chunks is not None else [body]
        self.reads = 0
        self.closed = False

    def read(self, amount):
        self.reads += 1
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if len(chunk) > amount:
            self._chunks.insert(0, chunk[amount:])
            return chunk[:amount]
        return chunk

    def close(self):
        self.closed = True


class Endless(Page):
    def __init__(self):
        super().__init__(headers={"Content-Type": "text/html"})
        self.sizes = []

    def read(self, amount):
        self.reads += 1
        self.sizes.append(amount)
        return b"x" * amount


class FakeSocket:
    def __init__(self, payload=b"", family=None):
        self.payload = payload
        self.family = family
        self.sent = bytearray()
        self.connected = None
        self.timeouts = []
        self.closed = 0

    def settimeout(self, value):
        self.timeouts.append(value)

    def gettimeout(self):
        return self.timeouts[-1] if self.timeouts else None

    def connect(self, address):
        self.connected = address

    def setsockopt(self, *args):
        return None

    def sendall(self, data):
        self.sent += bytes(data)

    def makefile(self, mode="rb", *args, **kwargs):
        return io.BytesIO(self.payload)

    def close(self):
        self.closed += 1

    def fileno(self):
        return 0


def _html(body=b"<p>ok</p>", status=200, content_type="text/html; charset=utf-8"):
    return Page(status, {"Content-Type": content_type}, body)


def _refused(url, monkeypatch=None, resolver=None):
    if resolver is not None:
        monkeypatch.setattr(guard, "_resolve_host", resolver)
    with pytest.raises(FetchRefused) as caught:
        fetch(url)
    return caught.value


def _literal(ip: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    return f"http://{host}/"


# ------------------------------------------------------------ user agent


def test_user_agent_names_omnibasket_and_not_a_crawler():
    assert USER_AGENT == "Omnibasket/0.1 (+https://omnibasket.anottersolution.com)"
    folded = USER_AGENT.lower()
    assert "spider" not in folded
    assert "crawler" not in folded


def test_request_sends_that_user_agent_once(monkeypatch):
    seen = {}

    def opener(target):
        seen["headers"] = dict(target.headers)
        seen["calls"] = seen.get("calls", 0) + 1
        return _html(b"hi")

    monkeypatch.setattr(guard, "_open", opener)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    result = fetch("http://shop.example/book")
    assert seen["calls"] == 1
    assert seen["headers"]["User-Agent"] == USER_AGENT
    assert result.body == b"hi"
    assert result.text == "hi"
    assert result.hops == 0


# ------------------------------------------------------------ refusal


@pytest.mark.parametrize("ip,reason", REFUSED_ADDRESSES)
def test_address_reason_names_the_blocked_class(ip, reason):
    assert address_reason(ip) == reason


@pytest.mark.parametrize("ip,reason", LITERAL_ADDRESSES)
def test_literal_address_is_refused_before_connect(ip, reason):
    err = _refused(_literal(ip))
    assert err.reason == reason


@pytest.mark.parametrize("ip,reason", REFUSED_ADDRESSES)
def test_resolved_address_is_refused_before_connect(ip, reason, monkeypatch):
    err = _refused("http://shop.example/book", monkeypatch, lambda host: [ip])
    assert err.reason == reason
    assert err.url == "http://shop.example/book"


@pytest.mark.parametrize(
    "url,reason",
    [
        ("ftp://shop.example/", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("gopher://shop.example/", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("", "scheme"),
        ("   ", "scheme"),
        ("http://user:secret@shop.example/a", "userinfo"),
        ("http://user@shop.example/", "userinfo"),
        ("http://books.example\\@127.0.0.1/", "userinfo"),
        ("http://shop.example:8080/", "port"),
        ("https://shop.example:8443/a", "port"),
        ("http://shop.example:0/", "port"),
        ("http://shop.example:99999/", "port"),
        ("http://", "host"),
        ("http:///etc/passwd", "host"),
        ("http://shop.example/\nnext", "host"),
        ("http://2130706433/", "host"),
        ("http://0177.0.0.1/", "host"),
        ("http://127.1/", "host"),
        ("http://0x7f000001/", "host"),
        ("http://0x7f.0.0.1/", "host"),
        ("http://exa mple.com/", "host"),
        ("http://.shop.example/", "host"),
    ],
)
def test_url_is_refused(url, reason):
    err = _refused(url)
    assert err.reason == reason
    if reason == "userinfo":
        assert err.url is None
        assert "secret" not in str(err)


def test_non_text_url_is_refused():
    assert _refused(None).reason == "scheme"


def test_scoped_ipv6_literal_is_link_local():
    err = _refused("http://[fe80::1%25eth0]/")
    assert err.reason == "link_local"


def test_mixed_records_refuse_when_any_address_is_private(monkeypatch):
    err = _refused(
        "http://shop.example/",
        monkeypatch,
        lambda host: ["1.1.1.1", "192.168.0.5"],
    )
    assert err.reason == "private"


def test_empty_resolution_is_refused(monkeypatch):
    assert _refused("http://shop.example/", monkeypatch, lambda host: []).reason == "resolve"


def test_resolver_failure_is_refused(monkeypatch):
    def resolver(host):
        raise socket.gaierror(8, "no such host")

    assert _refused("http://shop.example/", monkeypatch, resolver).reason == "resolve"


def test_unparseable_resolver_answer_is_refused(monkeypatch):
    err = _refused("http://shop.example/", monkeypatch, lambda host: ["not-an-ip"])
    assert err.reason == "resolve"


# ------------------------------------------------------------ allowed fetch


@pytest.mark.parametrize("ip,pinned", ALLOWED_ADDRESSES)
def test_public_literal_is_fetched_at_the_checked_address(ip, pinned, monkeypatch):
    assert address_reason(ip) is None
    seen = []

    def opener(target):
        seen.append(target)
        return _html(b"page")

    monkeypatch.setattr(guard, "_open", opener)
    result = fetch(_literal(ip) + "item")
    assert seen[0].ip == pinned
    assert seen[0].port == 80
    assert result.final_url == _literal(ip) + "item"
    assert result.body == b"page"
    assert result.hops == 0


def test_one_attempt_uses_only_the_first_public_address(monkeypatch):
    seen = []

    def opener(target):
        seen.append(target.ip)
        return _html()

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1", "8.8.8.8"])
    monkeypatch.setattr(guard, "_open", opener)
    fetch("http://shop.example/a")
    assert seen == ["1.1.1.1"]


def test_failed_connection_is_not_retried(monkeypatch):
    calls = []

    def connect(ip, port, timeout):
        calls.append((ip, port))
        raise ConnectionRefusedError("down")

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1", "8.8.8.8"])
    monkeypatch.setattr(guard, "_connect_pinned", connect)
    err = _refused("http://shop.example/a")
    assert err.reason == "connect"
    assert calls == [("1.1.1.1", 80)]


def test_tls_failure_is_not_retried(monkeypatch):
    calls = []

    def connect(ip, port, timeout):
        calls.append(ip)
        return FakeSocket()

    def wrap(self, sock, server_hostname=None, **kwargs):
        raise ssl.SSLError(1, "certificate verify failed")

    monkeypatch.setattr(guard, "_connect_pinned", connect)
    monkeypatch.setattr(guard.ssl.SSLContext, "wrap_socket", wrap)
    assert _refused("https://1.1.1.1/").reason == "connect"
    assert calls == ["1.1.1.1"]


def test_connect_timeout_is_not_retried(monkeypatch):
    calls = []

    def connect(ip, port, timeout):
        calls.append(ip)
        raise TimeoutError("slow")

    monkeypatch.setattr(guard, "_connect_pinned", connect)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    assert _refused("http://shop.example/").reason == "timeout"
    assert calls == ["1.1.1.1"]


def test_broken_response_is_a_read_failure(monkeypatch):
    def opener(target):
        raise guard.http.client.BadStatusLine("nope")

    monkeypatch.setattr(guard, "_open", opener)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    assert _refused("http://shop.example/").reason == "read"


def test_http_status_is_returned_without_a_second_attempt(monkeypatch):
    calls = []

    def opener(target):
        calls.append(target.path)
        return _html(b"later", status=503)

    monkeypatch.setattr(guard, "_open", opener)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    result = fetch("http://shop.example/a")
    assert result.status == 503
    assert result.body == b"later"
    assert calls == ["/a"]


def test_ports_80_and_443_are_the_only_ones_opened(monkeypatch):
    seen = []

    def opener(target):
        seen.append((target.scheme, target.port, target.path))
        return _html()

    monkeypatch.setattr(guard, "_open", opener)
    fetch("http://1.1.1.1:443/x")
    fetch("https://1.1.1.1:80/y")
    assert seen == [("http", 443, "/x"), ("https", 80, "/y")]
    assert _refused("http://1.1.1.1:8080/").reason == "port"


def test_query_stays_and_fragment_is_dropped(monkeypatch):
    seen = []

    def opener(target):
        seen.append(target)
        return _html()

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    result = fetch("HTTP://Shop.Example/A/B?q=1#section")
    assert result.final_url == "http://shop.example/A/B?q=1"
    assert seen[0].path == "/A/B?q=1"
    assert seen[0].host == "shop.example"


def test_trailing_dot_is_resolved_as_the_registrable_name(monkeypatch):
    names = []

    def resolver(host):
        names.append(host)
        return ["1.1.1.1"]

    monkeypatch.setattr(guard, "_resolve_host", resolver)
    monkeypatch.setattr(guard, "_open", lambda target: _html())
    result = fetch("http://shop.example./a")
    assert names == ["shop.example"]
    assert result.final_url == "http://shop.example/a"


def test_unicode_path_is_percent_encoded(monkeypatch):
    seen = []

    def opener(target):
        seen.append(target.path)
        return _html()

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    result = fetch("http://shop.example/caf\u00e9")
    assert seen == ["/caf%C3%A9"]
    assert result.final_url == "http://shop.example/caf%C3%A9"


def test_idn_host_is_punycode_on_the_wire(monkeypatch):
    names = []
    opened = []

    def resolver(host):
        names.append(host)
        return ["93.184.216.34"]

    def opener(target):
        opened.append(target)
        return _html("bücher".encode())

    monkeypatch.setattr(guard, "_resolve_host", resolver)
    monkeypatch.setattr(guard, "_open", opener)
    result = fetch("http://bücher.example/seite")
    assert names == ["xn--bcher-kva.example"]
    assert opened[0].host == "xn--bcher-kva.example"
    assert opened[0].ip == "93.184.216.34"
    assert result.final_url == "http://xn--bcher-kva.example/seite"
    assert result.text == "bücher"

    names.clear()
    fetch("http://XN--BCHER-KVA.example/seite")
    assert names == ["xn--bcher-kva.example"]


# ------------------------------------------------------------ redirects


def test_redirect_to_a_private_address_is_not_opened(monkeypatch):
    opened = []

    def opener(target):
        opened.append(target.url if hasattr(target, "url") else target.ip)
        return Page(302, {"Location": "http://169.254.169.254/latest/meta-data"})

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    err = _refused("http://shop.example/book")
    assert err.reason == "metadata"
    assert err.url == "http://169.254.169.254/latest/meta-data"
    assert opened == ["1.1.1.1"]


def test_redirect_to_a_name_that_resolves_private_is_not_opened(monkeypatch):
    opened = []

    def resolver(host):
        if host == "shop.example":
            return ["1.1.1.1"]
        if host == "rebind.example":
            return ["10.0.0.8"]
        raise AssertionError(host)

    def opener(target):
        opened.append(target.host)
        return Page(301, {"Location": "http://rebind.example/x"})

    monkeypatch.setattr(guard, "_resolve_host", resolver)
    monkeypatch.setattr(guard, "_open", opener)
    err = _refused("http://shop.example/a")
    assert err.reason == "private"
    assert err.url == "http://rebind.example/x"
    assert opened == ["shop.example"]


@pytest.mark.parametrize(
    "location,reason",
    [
        ("http://10.1.2.3/a", "private"),
        ("http://[::1]/a", "loopback"),
        ("http://[fc00::1]/a", "ula"),
        ("http://shop.example:8080/a", "port"),
        ("http://user:secret@shop.example/a", "userinfo"),
        ("ftp://shop.example/a", "scheme"),
        ("//169.254.169.254/latest", "metadata"),
    ],
)
def test_every_redirect_hop_is_checked(location, reason, monkeypatch):
    def opener(target):
        return Page(302, {"Location": location})

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    err = _refused("https://shop.example/start")
    assert err.reason == reason
    if reason == "userinfo":
        assert err.url is None


def test_relative_redirect_is_followed_and_resolved_again(monkeypatch):
    names = []
    paths = []

    def resolver(host):
        names.append(host)
        return ["1.1.1.1"]

    def opener(target):
        paths.append(target.path)
        if len(paths) == 1:
            return Page(302, {"Location": "next"})
        return _html(b"there")

    monkeypatch.setattr(guard, "_resolve_host", resolver)
    monkeypatch.setattr(guard, "_open", opener)
    result = fetch("http://shop.example/a/b")
    assert names == ["shop.example", "shop.example"]
    assert paths == ["/a/b", "/a/next"]
    assert result.hops == 1
    assert result.final_url == "http://shop.example/a/next"
    assert result.body == b"there"


def test_five_redirects_then_a_page(monkeypatch):
    paths = []

    def opener(target):
        paths.append(target.path)
        if len(paths) <= 5:
            return Page(302, {"Location": f"/hop{len(paths)}"})
        return _html(b"done")

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    result = fetch("http://shop.example/start")
    assert result.hops == MAX_REDIRECTS
    assert result.body == b"done"
    assert result.final_url == "http://shop.example/hop5"
    assert paths == ["/start", "/hop1", "/hop2", "/hop3", "/hop4", "/hop5"]


def test_sixth_redirect_is_refused(monkeypatch):
    paths = []

    def opener(target):
        paths.append(target.path)
        return Page(302, {"Location": f"/hop{len(paths)}"})

    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    err = _refused("http://shop.example/start")
    assert err.reason == "too_many_redirects"
    assert paths == ["/start", "/hop1", "/hop2", "/hop3", "/hop4", "/hop5"]


def test_redirect_without_a_location_is_refused(monkeypatch):
    page = Page(302, {"Content-Type": "text/html"}, b"go")
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", lambda target: page)
    assert _refused("http://shop.example/").reason == "redirect"
    assert page.reads == 0
    assert page.closed is True


def test_blank_location_is_refused(monkeypatch):
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", lambda target: Page(307, {"Location": "  "}))
    assert _refused("http://shop.example/").reason == "redirect"


# ------------------------------------------------------------ caps


def test_content_length_above_the_cap_aborts_before_the_body(monkeypatch):
    page = Page(200, {"Content-Type": "text/html", "Content-Length": "50"}, b"x" * 50)
    monkeypatch.setattr(guard, "_open", lambda target: page)
    with pytest.raises(FetchRefused) as caught:
        fetch("http://1.1.1.1/", max_bytes=8)
    assert caught.value.reason == "too_large"
    assert page.reads == 0
    assert page.closed is True


def test_stream_aborts_once_the_body_passes_the_cap(monkeypatch):
    page = Endless()
    monkeypatch.setattr(guard, "_open", lambda target: page)
    with pytest.raises(FetchRefused) as caught:
        fetch("http://1.1.1.1/", max_bytes=8)
    assert caught.value.reason == "too_large"
    assert page.reads == 1
    assert page.sizes == [9]
    assert page.closed is True


def test_body_at_exactly_the_cap_is_kept(monkeypatch):
    page = _html(b"12345678")
    monkeypatch.setattr(guard, "_open", lambda target: page)
    result = fetch("http://1.1.1.1/", max_bytes=8)
    assert result.body == b"12345678"
    assert page.closed is True


def test_defaults_are_three_mebibytes_and_ten_seconds():
    assert DEFAULT_MAX_BYTES == 3 * 1024 * 1024
    assert DEFAULT_TIMEOUT_S == 10.0
    assert MAX_REDIRECTS == 5


def test_deadline_during_the_body_is_a_timeout(monkeypatch):
    clock = {"now": 0.0}

    def monotonic():
        return clock["now"]

    page = _html(b"hello")

    def read(amount):
        page.reads += 1
        clock["now"] = 50.0
        return b"hello"

    page.read = read
    monkeypatch.setattr(guard.time, "monotonic", monotonic)
    monkeypatch.setattr(guard, "_open", lambda target: page)
    with pytest.raises(FetchRefused) as caught:
        fetch("http://1.1.1.1/", timeout=10)
    assert caught.value.reason == "timeout"
    assert page.closed is True


def test_read_timeout_is_not_retried(monkeypatch):
    calls = []

    def read(amount):
        raise TimeoutError("slow body")

    def opener(target):
        calls.append(1)
        page = _html(b"hello")
        page.read = read
        return page

    monkeypatch.setattr(guard, "_open", opener)
    with pytest.raises(FetchRefused) as caught:
        fetch("http://1.1.1.1/")
    assert caught.value.reason == "timeout"
    assert calls == [1]


def test_time_spent_before_a_redirect_is_part_of_the_same_deadline(monkeypatch):
    clock = {"now": 0.0}
    opened = []

    def opener(target):
        opened.append(target.path)
        clock["now"] = 50.0
        return Page(302, {"Location": "/next"})

    monkeypatch.setattr(guard.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["1.1.1.1"])
    monkeypatch.setattr(guard, "_open", opener)
    assert _refused("http://shop.example/start").reason == "timeout"
    assert opened == ["/start"]


# ------------------------------------------------------------ content type


@pytest.mark.parametrize(
    "content_type,body,text",
    [
        ("text/html", b"<p>a</p>", "<p>a</p>"),
        ("Text/HTML", b"A", "A"),
        ("text/html; charset=utf-8", "café".encode(), "café"),
        ("text/html; charset=iso-8859-1", b"caf\xe9", "café"),
        ("application/xhtml+xml", b"<x/>", "<x/>"),
        ("application/xhtml+xml; charset=utf-8", b"<x/>", "<x/>"),
        ("text/html; charset=not-a-charset", b"hi", "hi"),
    ],
)
def test_html_and_xhtml_are_accepted(content_type, body, text, monkeypatch):
    page = Page(200, {"Content-Type": content_type}, body)
    monkeypatch.setattr(guard, "_open", lambda target: page)
    result = fetch("http://1.1.1.1/a")
    assert result.content_type == content_type
    assert result.body == body
    assert result.text == text
    assert page.closed is True


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/json", "text/htmltext"])
def test_other_content_types_are_refused_without_reading(content_type, monkeypatch):
    headers = {} if content_type is None else {"Content-Type": content_type}
    page = Page(200, headers, b"secret-body")
    monkeypatch.setattr(guard, "_open", lambda target: page)
    with pytest.raises(FetchRefused) as caught:
        fetch("http://1.1.1.1/")
    assert caught.value.reason == "content_type"
    assert page.reads == 0
    assert page.closed is True


# ------------------------------------------------------------ pinned socket


def test_connect_pinned_uses_the_checked_address(monkeypatch):
    made = []

    def factory(family, typ, proto=0):
        assert typ == socket.SOCK_STREAM
        sock = FakeSocket(family=family)
        made.append(sock)
        return sock

    monkeypatch.setattr(guard.socket, "socket", factory)
    monkeypatch.setattr(guard, "_connect_pinned", _REAL_CONNECT)
    sock = guard._connect_pinned("93.184.216.34", 443, 2.5)
    assert sock.family == socket.AF_INET
    assert sock.connected == ("93.184.216.34", 443)
    assert sock.timeouts == [2.5]

    made.clear()
    sock = guard._connect_pinned("2606:4700:4700::1111", 80, 1.0)
    assert sock.family == socket.AF_INET6
    assert sock.connected == ("2606:4700:4700::1111", 80)


def test_connect_pinned_closes_the_socket_when_connect_fails(monkeypatch):
    made = []

    class Refusing(FakeSocket):
        def connect(self, address):
            raise ConnectionRefusedError("no")

    def factory(family, typ, proto=0):
        sock = Refusing(family=family)
        made.append(sock)
        return sock

    monkeypatch.setattr(guard.socket, "socket", factory)
    with pytest.raises(ConnectionRefusedError):
        _REAL_CONNECT("1.1.1.1", 80, 1.0)
    assert made[0].closed == 1


def test_resolve_host_keeps_order_and_drops_duplicates(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        assert host == "shop.example"
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0, 0, 0)),
        ]

    monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)
    assert _REAL_RESOLVE("shop.example") == ["1.1.1.1", "2606:4700:4700::1111"]


def test_resolve_host_refuses_when_nothing_comes_back(monkeypatch):
    monkeypatch.setattr(guard.socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(FetchRefused) as caught:
        _REAL_RESOLVE("shop.example")
    assert caught.value.reason == "resolve"

    def explode(*args, **kwargs):
        raise socket.gaierror(8, "no")

    monkeypatch.setattr(guard.socket, "getaddrinfo", explode)
    with pytest.raises(FetchRefused) as caught:
        _REAL_RESOLVE("shop.example")
    assert caught.value.reason == "resolve"


def _http_bytes(body: bytes, content_type=b"text/html; charset=utf-8") -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: " + content_type + b"\r\n"
        b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + body
    )


def test_http_sends_the_host_and_connects_to_the_pinned_ip(monkeypatch):
    socks = []

    def connect(ip, port, timeout):
        sock = FakeSocket(_http_bytes(b"hello"))
        sock.connected = (ip, port)
        sock.timeouts.append(timeout)
        socks.append(sock)
        return sock

    def wrap(self, sock, server_hostname=None, **kwargs):
        raise AssertionError("plain http must not start TLS")

    monkeypatch.setattr(guard.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(guard, "_connect_pinned", connect)
    monkeypatch.setattr(guard.ssl.SSLContext, "wrap_socket", wrap)
    result = fetch("http://books.example:443/item")
    sent = bytes(socks[0].sent)
    assert socks[0].connected == ("93.184.216.34", 443)
    assert socks[0].timeouts[0] == 10.0
    assert b"GET /item HTTP/1.1\r\n" in sent
    assert b"Host: books.example:443\r\n" in sent
    assert b"93.184.216.34" not in sent
    assert b"User-Agent: " + USER_AGENT.encode("ascii") in sent
    assert b"Accept-Encoding: identity\r\n" in sent
    assert sent.lower().count(b"get ") == 1
    assert b"spider" not in sent.lower()
    assert b"crawler" not in sent.lower()
    assert result == guard.GuardedFetch(
        final_url="http://books.example:443/item",
        status=200,
        content_type="text/html; charset=utf-8",
        body=b"hello",
        text="hello",
        hops=0,
    )


def test_https_sni_is_the_hostname_not_the_ip(monkeypatch):
    seen = {}

    def connect(ip, port, timeout):
        sock = FakeSocket(_http_bytes("seite".encode()))
        seen["connect"] = (ip, port, timeout)
        seen["sock"] = sock
        return sock

    def wrap(self, sock, server_hostname=None, **kwargs):
        seen["sni"] = server_hostname
        return sock

    monkeypatch.setattr(guard.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(guard, "_resolve_host", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(guard, "_connect_pinned", connect)
    monkeypatch.setattr(guard.ssl.SSLContext, "wrap_socket", wrap)
    result = fetch("https://bücher.example/seite")
    sent = bytes(seen["sock"].sent)
    assert seen["connect"] == ("93.184.216.34", 443, 10.0)
    assert seen["sni"] == "xn--bcher-kva.example"
    assert seen["sni"] != seen["connect"][0]
    assert b"Host: xn--bcher-kva.example\r\n" in sent
    assert b"User-Agent: " + USER_AGENT.encode("ascii") in sent
    assert b"GET /seite HTTP/1.1\r\n" in sent
    assert result.final_url == "https://xn--bcher-kva.example/seite"
    assert result.text == "seite"
    assert result.hops == 0

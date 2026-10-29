"""Fetch guard for a pasted link. One attempt, no retries.

http and https only, on ports 80 and 443. The name is resolved and the
socket is opened to an address that was just checked, so a later DNS
answer cannot move the connection. The Host header and TLS SNI keep the
name from the URL. Each redirect is checked again, up to five hops. The
body is streamed up to 3 MiB, and every hop shares one 10 second deadline.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass

USER_AGENT = "Omnibasket/0.1 (+https://omnibasket.anottersolution.com)"
DEFAULT_MAX_BYTES = 3 * 1024 * 1024
DEFAULT_TIMEOUT_S = 10.0
MAX_REDIRECTS = 5

_CHUNK = 64 * 1024
_ALLOWED_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_ULA = ipaddress.ip_network("fc00::/7")
# Python reports this deprecated site-local prefix as global.
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
_METADATA = ipaddress.ip_address("169.254.169.254")
_HOST_RE = re.compile(
    r"(?=.{1,253}$)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_REQUEST_HEADERS = (
    ("User-Agent", USER_AGENT),
    ("Accept", "text/html, application/xhtml+xml"),
    ("Connection", "close"),
)


class FetchRefused(Exception):
    """The link was not fetched. ``reason`` is a stable code.

    scheme, userinfo, port, host, resolve, loopback, private, link_local,
    metadata, multicast, reserved, unspecified, cgnat, ula,
    too_many_redirects, too_large, timeout, content_type, redirect,
    connect, read.
    """

    def __init__(self, reason: str, url: str | None = None):
        self.reason = reason
        self.url = url
        super().__init__(reason)


@dataclass(frozen=True)
class GuardedFetch:
    final_url: str
    status: int
    content_type: str
    body: bytes
    text: str
    hops: int


@dataclass(frozen=True)
class Target:
    """One hop that has already passed the address check.

    ``ip`` is the address the socket must use. ``host`` is the name for
    the Host header and for TLS SNI.
    """

    scheme: str
    host: str
    ip: str
    port: int
    path: str
    headers: tuple[tuple[str, str], ...]
    timeout: float


@dataclass(frozen=True)
class _Request:
    scheme: str
    host: str
    port: int
    path: str
    url: str


def address_reason(ip: str) -> str | None:
    """Refusal code for an address, or None when it is public unicast.

    An IPv4-mapped IPv6 address is judged as the IPv4 address inside it.
    """

    if "%" in ip:
        return "link_local"
    parsed = ipaddress.ip_address(ip)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    # 169.254.169.254 is link-local, and it is also the OCI metadata address.
    if parsed.version == 4 and parsed == _METADATA:
        return "metadata"
    if parsed.is_unspecified:
        return "unspecified"
    if parsed.is_loopback:
        return "loopback"
    if parsed.is_link_local:
        return "link_local"
    # Multicast is flagged global in this Python, so it is not left to is_global.
    if parsed.is_multicast:
        return "multicast"
    # 100.64/10 is neither private nor global in this Python.
    if parsed.version == 4 and parsed in _CGNAT:
        return "cgnat"
    if parsed.version == 6 and parsed in _ULA:
        return "ula"
    if parsed.version == 6 and parsed in _SITE_LOCAL:
        return "reserved"
    if parsed.is_reserved:
        return "reserved"
    if parsed.is_private:
        return "private"
    if not parsed.is_global:
        return "reserved"
    return None


def fetch(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> GuardedFetch:
    """Fetch one pasted URL, or raise ``FetchRefused``.

    At most one TCP connection is opened per hop, and a failed connection
    is not tried again. At most ``MAX_REDIRECTS`` redirects are followed.
    """

    deadline = time.monotonic() + timeout
    current = url
    hops = 0
    while True:
        req = _parse(current)
        left = deadline - time.monotonic()
        if left <= 0:
            raise FetchRefused("timeout", req.url)
        ip = _pin(req.host, req.url)
        left = deadline - time.monotonic()
        if left <= 0:
            raise FetchRefused("timeout", req.url)
        target = Target(
            scheme=req.scheme,
            host=req.host,
            ip=ip,
            port=req.port,
            path=req.path,
            headers=_REQUEST_HEADERS,
            timeout=left,
        )
        resp = _exchange(target, req.url)
        try:
            if time.monotonic() >= deadline:
                raise FetchRefused("timeout", req.url)
            if resp.status in _REDIRECTS:
                if hops >= MAX_REDIRECTS:
                    raise FetchRefused("too_many_redirects", req.url)
                location = _header(resp.headers, "location")
                if location is None or not location.strip():
                    raise FetchRefused("redirect", req.url)
                current = urllib.parse.urljoin(req.url, location.strip())
                hops += 1
                continue
            content_type = _header(resp.headers, "content-type")
            if _media_type(content_type) not in _ALLOWED_TYPES:
                raise FetchRefused("content_type", req.url)
            body = _read_limited(resp, max_bytes, deadline, req.url)
            return GuardedFetch(
                final_url=req.url,
                status=resp.status,
                content_type=(content_type or "").strip(),
                body=body,
                text=_decode(body, content_type or ""),
                hops=hops,
            )
        finally:
            _close(resp)


def _parse(url: str) -> _Request:
    if not isinstance(url, str):
        raise FetchRefused("scheme")
    raw = url.strip()
    if not raw:
        raise FetchRefused("scheme")
    if any(ord(ch) < 32 for ch in raw):
        raise FetchRefused("host")
    parts = urllib.parse.urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchRefused("scheme")
    if parts.username is not None or parts.password is not None:
        raise FetchRefused("userinfo")
    host = parts.hostname
    if not host:
        raise FetchRefused("host")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchRefused("port") from exc
    if port is None:
        port = 443 if scheme == "https" else 80
    if port not in (80, 443):
        raise FetchRefused("port")
    if "%" in host:
        raise FetchRefused("link_local")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise FetchRefused("host") from exc
    if host.endswith("."):
        host = host[:-1]
    if not host:
        raise FetchRefused("host")
    _reject_bad_host(host)
    path = _path_of(parts)
    return _Request(scheme, host, port, path, _url_for(scheme, host, port, path))


def _reject_bad_host(host: str) -> None:
    if _literal_ip(host) is not None:
        return
    # Decimal, octal, hex and short dotted forms are not canonical addresses.
    # ipaddress rejects them, and some libc resolvers turn them into addresses.
    if _numeric_labels(host):
        raise FetchRefused("host")
    if _HOST_RE.fullmatch(host) is None:
        raise FetchRefused("host")


def _numeric_labels(host: str) -> bool:
    labels = host.split(".")
    if not labels or any(label == "" for label in labels):
        return False
    for label in labels:
        if label.isdigit():
            continue
        hexed = label[2:] if label.startswith("0x") else ""
        if hexed and all(ch in "0123456789abcdef" for ch in hexed):
            continue
        return False
    return True


def _literal_ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _path_of(parts: urllib.parse.SplitResult) -> str:
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = _ascii_part(path, "/%:@!$&'()*+,;=-._~")
    if parts.query:
        path = path + "?" + _ascii_part(parts.query, "/%:@!$&'()*+,;=-._~?=&")
    return path


def _ascii_part(text: str, safe: str) -> str:
    if text.isascii() and " " not in text:
        return text
    return urllib.parse.quote(text, safe=safe)


def _url_for(scheme: str, host: str, port: int, path: str) -> str:
    default = 443 if scheme == "https" else 80
    shown = f"[{host}]" if ":" in host else host
    authority = shown if port == default else f"{shown}:{port}"
    return f"{scheme}://{authority}{path}"


def _pin(host: str, url: str) -> str:
    """Return the address to connect to, or refuse the whole name.

    One disallowed address refuses the hop. A later public record is not
    a way past a private one.
    """

    literal = _literal_ip(host)
    if literal is not None:
        ips = [str(literal)]
    else:
        try:
            ips = list(_resolve_host(host))
        except FetchRefused:
            raise
        except socket.gaierror as exc:
            raise FetchRefused("resolve", url) from exc
    if not ips:
        raise FetchRefused("resolve", url)
    chosen = None
    seen: set[str] = set()
    for raw in ips:
        if raw in seen:
            continue
        seen.add(raw)
        try:
            reason = address_reason(raw)
        except ValueError as exc:
            raise FetchRefused("resolve", url) from exc
        if reason is not None:
            raise FetchRefused(reason, url)
        if chosen is None:
            chosen = _canonical(raw)
    if chosen is None:
        raise FetchRefused("resolve", url)
    return chosen


def _canonical(raw: str) -> str:
    parsed = ipaddress.ip_address(raw)
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return str(parsed)


def _resolve_host(host: str) -> list[str]:
    """Addresses for a hostname, in resolver order, without duplicates."""

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchRefused("resolve") from exc
    found: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in found:
            found.append(ip)
    if not found:
        raise FetchRefused("resolve")
    return found


def _connect_pinned(ip: str, port: int, timeout: float) -> socket.socket:
    """Open one TCP connection to an address the guard has already allowed."""

    parsed = ipaddress.ip_address(ip)
    family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((ip, port))
    except Exception:
        sock.close()
        raise
    return sock


def _open(target: Target):
    """GET ``target`` once. The socket uses ``target.ip``; the name stays on the wire."""

    started = time.monotonic()
    sock = _connect_pinned(target.ip, target.port, target.timeout)
    try:
        if target.scheme == "https":
            # The handshake shares the hop's remaining time. TCP connect
            # already spent part of target.timeout. SNI is the URL host.
            left = target.timeout - (time.monotonic() - started)
            if left <= 0:
                raise TimeoutError("deadline")
            sock.settimeout(left)
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=target.host)
            conn = http.client.HTTPSConnection(target.host, target.port, timeout=target.timeout)
        else:
            conn = http.client.HTTPConnection(target.host, target.port, timeout=target.timeout)
        conn.sock = sock
        conn.request("GET", target.path or "/", headers=dict(target.headers))
        resp = conn.getresponse()
    except Exception:
        sock.close()
        raise
    return _SockResponse(conn, resp, sock)


class _SockResponse:
    def __init__(self, conn, resp, sock):
        self.status = resp.status
        self.headers = {key.lower(): value for key, value in resp.getheaders()}
        self._conn = conn
        self._resp = resp
        self._sock = sock
        self._closed = False

    def set_timeout(self, seconds: float) -> None:
        self._sock.settimeout(seconds)

    def read(self, amount: int) -> bytes:
        return self._resp.read(amount)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._resp.close()
        finally:
            self._conn.close()


def _exchange(target: Target, url: str):
    try:
        return _open(target)
    except FetchRefused:
        raise
    except TimeoutError as exc:
        raise FetchRefused("timeout", url) from exc
    except OSError as exc:
        raise FetchRefused("connect", url) from exc
    except http.client.HTTPException as exc:
        raise FetchRefused("read", url) from exc


def _read_limited(resp, max_bytes: int, deadline: float, url: str) -> bytes:
    length = _content_length(resp.headers)
    if length is not None and length > max_bytes:
        raise FetchRefused("too_large", url)
    parts: list[bytes] = []
    total = 0
    while True:
        _arm(resp, deadline, url)
        try:
            chunk = resp.read(min(_CHUNK, max_bytes - total + 1))
        except FetchRefused:
            raise
        except TimeoutError as exc:
            raise FetchRefused("timeout", url) from exc
        except OSError as exc:
            raise FetchRefused("connect", url) from exc
        except http.client.HTTPException as exc:
            raise FetchRefused("read", url) from exc
        if time.monotonic() >= deadline:
            raise FetchRefused("timeout", url)
        if not chunk:
            return b"".join(parts)
        total += len(chunk)
        if total > max_bytes:
            raise FetchRefused("too_large", url)
        parts.append(chunk)


def _arm(resp, deadline: float, url: str) -> None:
    left = deadline - time.monotonic()
    if left <= 0:
        raise FetchRefused("timeout", url)
    setter = getattr(resp, "set_timeout", None)
    if setter is not None:
        setter(left)


def _content_length(headers) -> int | None:
    raw = _header(headers, "content-length")
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _header(headers, name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _media_type(value: str | None) -> str | None:
    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def _decode(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    for piece in content_type.split(";")[1:]:
        key, sep, value = piece.partition("=")
        if sep and key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip("\"'")
            break
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _close(resp) -> None:
    try:
        resp.close()
    except OSError:
        pass


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_S",
    "MAX_REDIRECTS",
    "USER_AGENT",
    "FetchRefused",
    "GuardedFetch",
    "Target",
    "address_reason",
    "fetch",
]

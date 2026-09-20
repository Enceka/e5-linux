"""Generic outbound HTTP proxy: the ``anyProxyModule`` port.

``/api/proxy/--<url>`` is the frontend's escape hatch for things that must leave
the device: the plugin store, changelog lookups and cellular speed tests (which
download an external file through the tunnel).  The SSRF filter from the Android
implementation is kept verbatim: loopback, link-local and RFC1918 destinations
are refused, so a compromised page cannot use the device to probe the LAN.

The vendor-specific ``/api/goform`` reverse proxy that used to live here is gone:
the E5 is not a ZTE device and there is no vendor web backend to forward to.  The
only thing still served under that path is the web UI's own login handshake,
which lives in :mod:`ufitools.api.ui_compat`.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

from ..httpd import ApiError, Response

PROXY_TIMEOUT = 30.0

_HOP_BY_HOP = {
    "connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length",
    "expect", "referer", "origin", "authorization", "x-forwarded-for", "via", "proxy-connection",
}
_ATTR_RE = re.compile(r'(?P<attr>\b(?:src|href|action)=)(?P<quote>["\'])(?P<url>/[^"\']*)')


def _query_string(request) -> str:
    if not request.query:
        return ""
    return urllib.parse.urlencode(
        [(k, v) for k, values in request.query.items() for v in values], doseq=True
    )


def _is_private_host(host: str) -> bool:
    """``true`` when the host resolves to something the proxy must not reach."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Cannot resolve: let the request fail on its own rather than blocking a
        # legitimate name the device's resolver is slow about.
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast:
            return True
    return False


def register(router, app) -> None:
    def any_proxy(request):
        target = request.params.get("tail", "").lstrip("/")
        if target.startswith("--"):
            target = target[2:]
        if not target.startswith(("http://", "https://")):
            target = "http://" + target.lstrip("/")

        parsed = urllib.parse.urlsplit(target)
        host = parsed.hostname or ""
        if not host:
            raise ApiError("目标地址非法", 400)
        if _is_private_host(host):
            raise ApiError("目标地址被禁止", 403)

        query = _query_string(request)
        if query:
            target = target + ("&" if parsed.query else "?") + query

        headers: Dict[str, str] = {"User-Agent": "Mozilla/5.0 (UFI-TOOLS-linux)"}
        for key, value in request.headers.items():
            lowered = key.lower()
            if lowered in _HOP_BY_HOP or lowered.startswith("sec-") or lowered.startswith("kano-"):
                continue
            headers[key] = value
        # kano-<Header> carries headers fetch() refuses to set, minus the prefix.
        for key, value in request.headers.items():
            if key.lower().startswith("kano-") and key.lower() not in ("kano-t", "kano-sign"):
                headers[key[5:]] = value

        return _forward(request, target, headers)

    router.add("ANY", "/api/proxy/{...}", any_proxy)


def _forward(request, target: str, headers: Dict[str, str]) -> Response:
    body = request.body if request.method in ("POST", "PUT", "PATCH", "DELETE") else None
    if body is not None and not headers.get("Content-Type"):
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    http_request = urllib.request.Request(target, data=body, headers=headers)
    if request.method not in ("GET", "HEAD"):
        http_request.get_method = lambda: request.method
    try:
        with urllib.request.urlopen(http_request, timeout=PROXY_TIMEOUT) as upstream:
            payload = upstream.read()
            content_type = upstream.headers.get("Content-Type", "application/octet-stream")
            status = upstream.status
            set_cookies = upstream.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        content_type = exc.headers.get("Content-Type", "application/json")
        status = exc.code
        set_cookies = exc.headers.get_all("Set-Cookie") or []
    except (urllib.error.URLError, OSError):
        raise ApiError("上游请求失败", 502)

    if "html" in content_type.lower():
        payload = _rewrite_html(payload, target)

    extra: Dict[str, str] = {}
    cookies: List[str] = list(set_cookies)
    if cookies:
        extra["Kano-SetCk"] = cookies[0]

    return Response(status, payload, content_type, extra)


def _rewrite_html(payload: bytes, target: str) -> bytes:
    """Point root-relative URLs back through this proxy (Android parity)."""
    text = payload.decode("utf-8", "replace")
    parsed = urllib.parse.urlsplit(target)
    prefix = "/api/proxy/--%s://%s" % (parsed.scheme, parsed.netloc)

    def replacement(match: "re.Match[str]") -> str:
        url = match.group("url")
        if url.startswith("//") or url.startswith(prefix):
            return match.group(0)
        return "%s%s%s%s" % (match.group("attr"), match.group("quote"), prefix, url)

    return _ATTR_RE.sub(replacement, text).encode("utf-8")

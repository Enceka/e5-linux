"""HTTP plumbing: router, request/response types, static files.

Stdlib only (``http.server``).  UFI-TOOLS on Android uses Ktor; the contract
that matters is the wire format, not the framework, and a stdlib server keeps
the E5-LINUX image free of extra packages.

Two conventions are copied deliberately from Ktor's behaviour because the web
frontend depends on them:

* every response carries ``Access-Control-Allow-Origin: *``;
* failures are JSON ``{"error": "..."}`` with HTTP 500 unless stated otherwise.
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Expose-Headers": "kano-cookie, Kano-SetCk, Kano-Set-Cookie",
}


class ApiError(Exception):
    """Raised by a handler to produce an error response."""

    def __init__(self, message: str, status: int = 500, raw: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        #: When true the message is already a JSON document (used by the
        #: reverse proxy, which must pass upstream bodies through verbatim).
        self.raw = raw


class Response:
    __slots__ = ("status", "body", "content_type", "headers")

    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "application/json",
                 headers: Optional[Dict[str, str]] = None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers or {}


def json_response(payload: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> Response:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return Response(status, body, "application/json", headers)


def raw_json_response(text: str, status: int = 200) -> Response:
    """Pass through a JSON document that was assembled by hand."""
    return Response(status, text.encode("utf-8"), "application/json")


def text_response(text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> Response:
    return Response(status, text.encode("utf-8"), content_type)


class Request:
    """Everything a handler may need about one HTTP request."""

    __slots__ = ("method", "raw_path", "path", "query", "headers", "body", "client_ip",
                 "server", "params")

    def __init__(self, method: str, raw_path: str, query: Dict[str, List[str]], headers: Dict[str, str],
                 body: bytes, client_ip: str, server):
        self.method = method.upper()
        self.raw_path = raw_path
        self.path = raw_path
        self.query = query
        self.headers = headers
        self.body = body
        self.client_ip = client_ip
        self.server = server
        #: Path parameters captured by the router (``tail`` for proxies).
        self.params: Dict[str, str] = {}

    def q(self, key: str, default: Optional[str] = None) -> Optional[str]:
        values = self.query.get(key)
        return values[0] if values else default

    def q_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.q(key, default))
        except (TypeError, ValueError):
            return default

    def json_body(self) -> Dict[str, Any]:
        if not self.body:
            return {}
        try:
            parsed = json.loads(self.body.decode("utf-8", "replace"))
        except ValueError:
            raise ApiError("请求体不是合法 JSON", 400)
        if not isinstance(parsed, dict):
            raise ApiError("请求体必须是 JSON 对象", 400)
        return parsed

    def header(self, name: str, default: str = "") -> str:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return default


_RULE_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class Router:
    """Tiny path router with ``{name}`` segments and a trailing ``{...}``."""

    def __init__(self):
        self._exact: Dict[Tuple[str, str], Callable] = {}
        self._dynamic: List[Tuple[str, re.Pattern, List[str], Callable]] = []

    def add(self, method: str, rule: str, handler: Callable) -> None:
        method = method.upper()
        if "{" not in rule:
            self._exact[(method, rule.rstrip("/") or "/")] = handler
            if method == "GET":
                # Register the trailing-slash variant too; browsers are sloppy.
                self._exact.setdefault(("GET", (rule.rstrip("/") or "") + "/"), handler)
            return
        tail = ""
        if "{...}" in rule:
            rule, tail = rule.replace("/{...}", ""), "(?P<tail>.*)"
        pattern = _RULE_PARAM.sub(lambda m: "(?P<%s>[^/]+)" % m.group(1), rule) + tail + "$"
        names = _RULE_PARAM.findall(rule) + (["tail"] if tail else [])
        self._dynamic.append((method, re.compile("^" + pattern), names, handler))

    def match(self, method: str, path: str) -> Optional[Tuple[Callable, Dict[str, str]]]:
        method = method.upper()
        handler = self._exact.get((method, path)) or self._exact.get(("ANY", path))
        if handler is not None:
            return handler, {}
        for rule_method, pattern, names, func in self._dynamic:
            if rule_method not in (method, "ANY"):
                continue
            match = pattern.match(path)
            if match:
                return func, {name: match.group(name) for name in names}
        return None

    def methods_for(self, path: str) -> List[str]:
        found = [m for (m, p) in self._exact if p == path]
        for rule_method, pattern, _names, _func in self._dynamic:
            if pattern.match(path):
                found.append(rule_method)
        return found


# ---------------------------------------------------------------------------
# static files
# ---------------------------------------------------------------------------

_MIME_FALLBACK = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8",
    ".woff2": "font/woff2",
}


def guess_content_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _MIME_FALLBACK:
        return _MIME_FALLBACK[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def serve_static(root: str, url_path: str) -> Response:
    """Serve ``url_path`` from ``root`` with path-traversal protection."""
    if not root or not os.path.isdir(root):
        return ApiError("静态资源目录不存在: %s" % root, 404)

    relative = urllib.parse.unquote(url_path).lstrip("/")
    if ".." in relative.split("/") or "\x00" in relative:
        return Response(403, b"403 Forbidden", "text/plain; charset=utf-8")
    if not relative or relative.endswith("/"):
        relative = posixpath.join(relative, "index.html")

    root_abs = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_abs, relative))
    if target != root_abs and not target.startswith(root_abs + os.sep):
        return Response(403, b"403 Forbidden", "text/plain; charset=utf-8")
    if not os.path.isfile(target):
        # A single-page app: unknown non-asset paths fall back to index.html so
        # deep links keep working.
        index = os.path.join(root_abs, "index.html")
        if os.path.isfile(index) and "." not in os.path.basename(target):
            target = index
        else:
            return Response(404, b"404 Not Found", "text/plain; charset=utf-8")

    try:
        with open(target, "rb") as handle:
            body = handle.read()
    except OSError:
        return Response(500, b"500 Internal Server Error", "text/plain; charset=utf-8")
    return Response(200, body, guess_content_type(target))


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "UFI-TOOLS-linux"
    protocol_version = "HTTP/1.1"

    # -- logging ----------------------------------------------------------
    def log_message(self, fmt, *args):
        server = getattr(self, "server", None)
        if server is not None and getattr(server, "quiet", False):
            return
        self.server.log("%s - %s" % (self.address_string(), fmt % args))

    def log_error(self, fmt, *args):
        self.log_message(fmt, *args)

    # -- dispatch ---------------------------------------------------------
    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            size = int(length)
        except ValueError:
            return b""
        if size <= 0:
            return b""
        return self.rfile.read(size)

    def _build_request(self) -> Request:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        headers = {k: v for k, v in self.headers.items()}
        client_ip = self.client_address[0] if self.client_address else ""
        if headers.get("X-Forwarded-For"):
            client_ip = headers["X-Forwarded-For"].split(",")[0].strip()
        return Request(
            self.command or "GET",
            urllib.parse.unquote(parsed.path),
            query,
            headers,
            self._read_body(),
            client_ip,
            self.server,
        )

    def _send(self, response: Response) -> None:
        if not isinstance(response, Response):  # a handler returned a dict
            response = json_response(response)
        try:
            self.send_response(response.status)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)
            for key, value in (response.headers or {}).items():
                self.send_header(key, value)
            if response.content_type:
                self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle(self, method: str) -> None:
        handler = getattr(self.server, "dispatch", None)
        if handler is None:  # pragma: no cover - server not fully wired
            self._send(text_response("server not ready", 503))
            return
        request = self._build_request()
        request.method = method
        self._send(handler(request))

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_HEAD(self):
        self._handle("GET")

    def do_OPTIONS(self):
        self._send(Response(204, b"", "", dict(CORS_HEADERS)))


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, address, dispatch: Callable[[Request], Response], logger=None, quiet: bool = False):
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _Handler)
        self.dispatch = dispatch
        self.quiet = quiet
        self._logger = logger
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        if self._logger:
            self._logger(message)
        else:  # pragma: no cover - default stderr
            print(message)

    def server_bind(self):
        # Keep the port free across restarts on a phone that reboots often.
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()

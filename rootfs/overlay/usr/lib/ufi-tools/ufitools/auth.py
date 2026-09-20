"""Request authentication and signing, ported byte-for-byte from the Android app.

Three headers guard ``/api/``:

``kano-t``       milliseconds timestamp (``Date.now()``)
``kano-sign``    ``SHA256(SHA256(hmac_md5[0:8]) || SHA256(hmac_md5[8:16]))``
                 where the HMAC input is ``"minikano" + METHOD + PATH + t``
``authorization`` ``sha256_hex(plaintext token)``, compared in constant time

The reference implementations are the four that shipped with the Android app
(which lives in its own repository, not here): ``KanoAuth.kt`` and
``KanoUtils.kt`` on the server side, ``ufi_req.go`` in the tool shipped to
devices, and ``requests.js`` in the browser.  All four agree, so the same client
code -- including the web frontend in ``linux/www`` -- talks to this server
unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Mapping, Optional
from urllib.parse import unquote

#: Shared secret.  Not a credential by itself: it only proves the request was
#: produced by a UFI-TOOLS client, the token in ``authorization`` is the actual
#: credential.
REQUEST_SECRET_KEY = "minikano_kOyXz0Ciz4V7wR0IeKmJFYFQ20jd"

#: ``/api/`` paths that need no headers at all (KanoAuth.kt:19-29).
API_WHITELIST_EXACT = frozenset(
    {
        "/api/get_custom_head",
        "/api/version_info",
        "/api/need_token",
        "/api/get_theme",
        "/api/SELinux",
    }
)

#: ``/api/uploads`` and everything under it is public.
API_WHITELIST_PREFIX = ("/api/uploads",)

_REPEATED_SLASHES = re.compile("/+")
_LEADING_SLASHES = re.compile("^/+")
_SHA256_HEX = re.compile("^[a-fA-F0-9]{64}$")

#: Default token, identical to ``KanoUtils.initSharedPerfs``.
DEFAULT_TOKEN = "admin"


def sha256_hex(data) -> str:
    """Lowercase hex SHA-256 of ``data`` (``str`` is encoded as UTF-8)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hmac_signature(secret: str, data: str) -> str:
    """Port of ``KanoUtils.HmacSignature``.

    ``HMAC-MD5`` gives 16 bytes; each half is hashed with SHA-256 separately and
    the two 32-byte digests are concatenated before a final SHA-256.  Note that
    the halves are hashed as *bytes*, not as hex strings -- a detail that is easy
    to get wrong and is covered by the signature test vectors.
    """
    mac = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.md5).digest()
    mid = len(mac) // 2
    part1, part2 = mac[:mid], mac[mid:]
    sha1 = hashlib.sha256(part1).digest()
    sha2 = hashlib.sha256(part2).digest()
    return hashlib.sha256(sha1 + sha2).hexdigest()


def normalize_path(raw_path: str) -> str:
    """Port of ``KanoUtils.normalizePath``: decode twice, squash slashes."""
    path = unquote(unquote(raw_path))
    path = path.replace("\\", "/")
    path = _REPEATED_SLASHES.sub("/", path)
    if not path.startswith("/"):
        path = "/" + path
    return path


def normalize_leading_slashes(path: str) -> str:
    """Port of ``KanoUtils.normalizeLeadingSlashes`` (no URL decoding)."""
    path = path.replace("\\", "/")
    path = _LEADING_SLASHES.sub("/", path)
    if not path.startswith("/"):
        path = "/" + path
    return path


def is_sha256_hex(value: Optional[str]) -> bool:
    return bool(value) and bool(_SHA256_HEX.match(value))


def constant_time_sha256_equals(first: str, second: str) -> bool:
    """Port of ``KanoUtils.constantTimeSha256Equals``."""
    a = hashlib.sha256(first.encode("utf-8")).digest()
    b = hashlib.sha256(second.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def normalize_token(raw: Optional[str]) -> str:
    """Return the stored representation of a token.

    The Android app stores ``sha256_hex(token)`` and rewrites a plaintext value on
    first use.  Accepting both forms here means a preferences export from a
    device can be imported verbatim.
    """
    token = (raw or "").strip()
    if is_sha256_hex(token):
        return token.lower()
    return sha256_hex(token)


def is_weak_token(token_hash: str) -> bool:
    """``true`` while the token is still the factory default or a known default."""
    if not token_hash:
        return True
    return token_hash.lower() == sha256_hex(DEFAULT_TOKEN)


def check_token_rules(token: str) -> Optional[str]:
    """Validate a *new* token, returning an error message or ``None``.

    Mirrors ``POST /api/set_token``: 8..128 chars, at least one letter and one
    digit.
    """
    if not token:
        return "口令不能为空"
    if not (8 <= len(token) <= 128):
        return "口令长度必须在 8-128 位之间"
    if not re.search(r"[a-zA-Z]", token):
        return "口令必须包含字母"
    if not re.search(r"\d", token):
        return "口令必须包含数字"
    return None


def is_public_path(normalized_path: str) -> bool:
    """Whitelist check, mirroring ``KanoAuth.checkAuth``."""
    if not (normalized_path == "/api" or normalized_path.startswith("/api/")):
        return True  # static assets are public
    if normalized_path in API_WHITELIST_EXACT:
        return True
    for prefix in API_WHITELIST_PREFIX:
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            return True
    return False


class AuthError(Exception):
    """Raised when a request fails authentication; rendered as HTTP 401."""


class AuthChecker:
    """Validates the three UFI-TOOLS headers.

    ``token_source`` and ``enabled_source`` are callables so the checker always
    reads the live configuration (the token can change while the server runs).
    """

    def __init__(self, token_source, enabled_source, max_skew_ms: int = 0, now_ms=None):
        self._token_source = token_source
        self._enabled_source = enabled_source
        #: 0 disables the check (Android parity).  A non-zero value adds replay
        #: protection for deployments that expose the port beyond the hotspot
        #: LAN; it is opt-in because phones with a wrong clock would be locked
        #: out otherwise.
        self.max_skew_ms = int(max_skew_ms or 0)
        self._now_ms = now_ms or (lambda: int(__import__("time").time() * 1000))

    def check(self, method: str, raw_path: str, headers: Mapping[str, str]) -> None:
        """Raise :class:`AuthError` unless the request is allowed."""
        normalized = normalize_path(raw_path)
        if self.is_enabled() is False or is_public_path(normalized):
            return

        lowered = {k.lower(): v for k, v in headers.items()}
        timestamp = (lowered.get("kano-t") or "").strip()
        signature = (lowered.get("kano-sign") or "").strip()
        authorization = (lowered.get("authorization") or "").strip()
        token = self._token_source() or ""

        if not timestamp or not signature or not authorization or not token:
            raise AuthError("缺少鉴权信息")

        if not constant_time_sha256_equals(authorization, token):
            raise AuthError("口令错误")

        try:
            client_ts = int(timestamp)
        except ValueError:
            raise AuthError("时间戳非法")

        if self.max_skew_ms > 0 and abs(self._now_ms() - client_ts) > self.max_skew_ms:
            raise AuthError("时间戳超出允许范围")

        # /api/proxy signs the raw path (leading slashes squashed), everything
        # else signs the normalized path -- KanoAuth.kt:72-77.
        if normalized == "/api/proxy" or normalized.startswith("/api/proxy/"):
            sign_target = normalize_leading_slashes(raw_path)
        else:
            sign_target = normalized

        raw = "minikano%s%s%s" % (method.upper(), sign_target, client_ts)
        expected = hmac_signature(REQUEST_SECRET_KEY, raw)
        if expected.lower() != signature.lower():
            raise AuthError("签名校验失败")

    def is_enabled(self) -> bool:
        return bool(self._enabled_source())

"""``ufi_req`` -- signed request tool, the port of the ``ufi_req`` helper that
ships with the Android app.

That helper exists so a shell on the device can drive the API without knowing the
token: it reads the stored hash out of the app's preferences.  Here the same
trick reads ``config.json``, so the command line stays almost identical:

    ufi_req -X POST -e /api/root_shell -d '{"command":"id"}'
    ufi_req -host 192.168.0.1:2333 -pass 123456 -X GET -e "/api/AT?command=AT"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .auth import hmac_signature, sha256_hex
from .config import Config

REQUEST_SECRET_KEY = "minikano_kOyXz0Ciz4V7wR0IeKmJFYFQ20jd"


def _token_from_config() -> str:
    try:
        return Config().token_hash
    except Exception:  # noqa: BLE001 - the CLI must still work off-device
        return ""


def build_url(host: str, endpoint: str) -> str:
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return "http://" + host + endpoint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ufi_req",
        description="MiniKano 签名请求工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  ufi_req -X POST -e /api/xxx -d '{\"command\":\"ls\"}'\n"
               "  ufi_req -X GET  -e \"/api/AT?command=AT&slot=0\"",
    )
    parser.add_argument("-host", default="192.168.0.1:2333", help="目标地址（选填）")
    # ``pass`` is a Python keyword, hence the explicit dest.
    parser.add_argument("-pass", dest="password", default="",
                        help="密码明文；不填则读取本机已存储的口令哈希")
    parser.add_argument("-X", dest="method", default="GET", help="HTTP 方法，默认 GET")
    parser.add_argument("-e", dest="endpoint", required=True, help="请求路径或完整 URL")
    parser.add_argument("-d", dest="data", default="", help="请求体（JSON 字符串）")
    parser.add_argument("-t", dest="timeout", type=int, default=10, help="超时秒数，默认 10")
    args = parser.parse_args(argv)

    authorization = sha256_hex(args.password) if args.password else _token_from_config()
    if not authorization:
        print(json.dumps({"error": "没有可用的口令：请用 -pass 传入，或先在本机配置口令"},
                         ensure_ascii=False))
        return 2

    url = build_url(args.host, args.endpoint)
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    method = (args.method or "GET").upper()

    timestamp = str(int(time.time() * 1000))
    signature = hmac_signature(REQUEST_SECRET_KEY, "minikano%s%s%s" % (method, path, timestamp))

    body = args.data.encode("utf-8") if args.data else None
    request = urllib.request.Request(url, data=body, headers={
        "kano-t": timestamp,
        "kano-sign": signature,
        "Authorization": authorization,
    })
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if method != "GET":
        request.get_method = lambda: method

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            sys.stdout.write(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        if payload:
            sys.stdout.write(payload)
        else:
            print(json.dumps({"error": "HTTP %d %s" % (exc.code, exc.reason)}))
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(json.dumps({"error": "响应失败: %s" % exc}))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

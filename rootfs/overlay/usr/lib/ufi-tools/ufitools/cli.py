"""Command line entry points for the Linux port.

``ufi-tools serve`` runs the daemon (this is what the systemd unit calls);
``ufi-tools status`` prints the state of every bridge so a field engineer can see
in one screen why, say, the AT tab is empty; ``ufi-tools set-token`` rotates the
web passphrase without editing JSON by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .auth import check_token_rules
from .config import Config


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def cmd_serve(args) -> int:
    from .app import Application

    app = Application(config=Config(data_dir=args.data_dir), static_root=args.static_root)
    if args.port:
        app.config.set("port", args.port)
    if args.bind:
        app.config.set("bind", args.bind)
    app.serve_forever(port=args.port, bind=args.bind, quiet=args.quiet)
    return 0


def cmd_status(args) -> int:
    from .app import Application
    from .traffic import detect_interfaces

    app = Application(config=Config(data_dir=args.data_dir), static_root=args.static_root)
    control = app.control
    _print({
        "version": __version__,
        "data_dir": app.config.data_dir,
        "static_root": app.static_root,
        "static_root_ready": os.path.isfile(os.path.join(app.static_root, "index.html")),
        "shim_root": app.shim_root,
        "listen": "%s:%s" % (app.config.get("bind"), app.config.get("port")),
        "token_enabled": app.config.token_enabled,
        "weak_token": app.config.is_weak_token,
        "advanced_enabled": app.advanced,
        "at_backend": app.at.describe(),
        "at_available": app.at.available(),
        "modem_fields": sorted(app.modem.as_dict()),
        "uplink_interfaces": detect_interfaces(),
        "mobile_data": control.mobile_data_status(),
        "hotspot": control.hotspot_status(),
        "lan": control.lan_status(),
        "performance": control.performance_status(),
        "led_supported": control.led_status().get("supported"),
        "task_count": len(app.tasks.tasks()),
    })
    return 0


def cmd_set_token(args) -> int:
    problem = check_token_rules(args.token)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    Config(data_dir=args.data_dir).set_token(args.token)
    print("口令已更新")
    return 0


def cmd_clients(args) -> int:
    from .app import Application

    app = Application(config=Config(data_dir=args.data_dir), static_root=args.static_root)
    _print({"count": len(app.control.clients()), "clients": app.control.clients()})
    return 0


def cmd_at(args) -> int:
    """Send one AT command through whatever channel is configured."""
    from .app import Application

    app = Application(config=Config(data_dir=args.data_dir), static_root=args.static_root)
    try:
        print(app.at.run(" ".join(args.command)))
    except Exception as exc:  # noqa: BLE001 - the CLI reports, it does not crash
        print("AT 失败: %s" % exc, file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufi-tools", description="UFI-TOOLS for Linux %s" % __version__)
    parser.add_argument("--data-dir", default=None, help="配置与数据目录（默认 $UFI_TOOLS_DATA）")
    parser.add_argument("--static-root", default=None, help="Web 前端目录")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动 Web 后台服务")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--bind", default=None)
    serve.add_argument("--quiet", action="store_true", help="不打印访问日志")
    serve.set_defaults(func=cmd_serve)

    status = sub.add_parser("status", help="打印各子系统状态")
    status.set_defaults(func=cmd_status)

    token = sub.add_parser("set-token", help="修改后台登录口令")
    token.add_argument("token")
    token.set_defaults(func=cmd_set_token)

    clients = sub.add_parser("clients", help="列出当前接入的无线客户端")
    clients.set_defaults(func=cmd_clients)

    at = sub.add_parser("at", help="通过已配置的 AT 通道发送一条指令")
    at.add_argument("command", nargs=argparse.REMAINDER)
    at.set_defaults(func=cmd_at)

    req = sub.add_parser("req", help="ufi_req 签名请求工具")
    req.add_argument("args", nargs=argparse.REMAINDER, help="传递给 ufi_req 的参数")
    req.set_defaults(func=cmd_req)
    return parser


def cmd_req(args) -> int:
    from .req import main as req_main

    return req_main(args.args)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

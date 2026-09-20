"""Application wiring: config, bridges and the request dispatcher.

``Application`` is the Linux counterpart of the Android ``WebService`` +
``ADBService`` pair: it owns the configuration, the hardware bridges (device
info, AT, native control) and the HTTP server, and it drives the background
tasks that Android ran in a foreground Service.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Callable, Optional

from . import __version__
from .at import ATRunner
from .auth import AuthChecker, AuthError
from .config import Config
from .control import SystemControl
from .httpd import ApiError, HTTPServer, Request, Response, Router, json_response, serve_static
from .modem import ModemSnapshot
from .store import JsonFile, PluginStore, TaskStore, ThemeStore
from .sysinfo import DeviceInfo


def bundled_static_root() -> str:
    """Where the web frontend lives, in order of preference."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("UFI_TOOLS_WWW", ""),
        os.path.join(here, "..", "www"),          # source checkout (linux/www)
        os.path.join(here, "www"),                # installed next to the package
        "/usr/share/ufi-tools/www",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = os.path.abspath(candidate)
        if os.path.isfile(os.path.join(resolved, "index.html")):
            return resolved
    return os.path.abspath(candidates[1])


def bundled_shim_root() -> str:
    """Where the built-in frontend shim lives (served as a static overlay)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("UFI_TOOLS_SHIM", ""),
        os.path.join(here, "..", "www-linux"),   # source checkout
        os.path.join(here, "www-linux"),         # installed next to the package
        "/usr/share/ufi-tools/www-linux",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "ufi-linux-shim.js")):
            return os.path.abspath(candidate)
    return os.path.abspath(candidates[1])


class Application:
    """Owns every long-lived object and turns requests into responses."""

    def __init__(self, config: Optional[Config] = None, data_dir: Optional[str] = None,
                 static_root: Optional[str] = None, logger: Optional[Callable[[str], None]] = None):
        self.config = config or Config(data_dir=data_dir)
        self.logger = logger or self._default_log
        self.static_root = static_root or str(self.config.get("static_root") or "") or bundled_static_root()
        self.shim_root = bundled_shim_root()

        self.device_info = DeviceInfo()
        self.at = ATRunner(
            socket_path=str(self.config.get("at_socket") or ""),
            device=str(self.config.get("at_device") or ""),
            command=str(self.config.get("at_command") or ""),
            timeout=self.config.get_float("at_timeout", 8.0),
        )
        self.modem = ModemSnapshot(
            self.at,
            interval=self.config.at_poll_interval,
            logger=self.log,
        )
        self.control = SystemControl(self)

        self.plugins = PluginStore(os.path.join(self.config.data_dir, "plugins.json"))
        self.theme = ThemeStore(os.path.join(self.config.data_dir, "theme.json"))
        self.tasks = TaskStore(os.path.join(self.config.data_dir, "tasks.json"))
        self.runtime = JsonFile(os.path.join(self.config.data_dir, "runtime.json"), {})

        self.auth = AuthChecker(
            token_source=lambda: self.config.token_hash,
            enabled_source=lambda: self.config.token_enabled,
            max_skew_ms=self.config.get_int("kano_max_skew_ms", 0),
        )

        self.started_at = time.time()
        self.router = Router()
        self._scheduler_stop = threading.Event()
        self._scheduler: Optional[threading.Thread] = None

        from .api import register_all

        register_all(self.router, self)

    # -- helpers ------------------------------------------------------------
    def _default_log(self, message: str) -> None:
        print("[ufi-tools] %s" % message, flush=True)

    def log(self, message: str) -> None:
        self.logger(message)

    @property
    def advanced(self) -> bool:
        return self.config.get_bool("advanced_enabled", False)

    def require_advanced(self) -> None:
        if not self.advanced:
            raise ApiError("高级功能未开启，请先开启高级功能", 500)

    def uptime(self) -> int:
        value = self.device_info.uptime()
        if value >= 0:
            return value
        return int(time.time() - self.started_at)

    # -- dispatch -----------------------------------------------------------
    def dispatch(self, request: Request) -> Response:
        try:
            self.auth.check(request.method, request.path, request.headers)
        except AuthError as exc:
            self.log("401 %s %s (%s)" % (request.method, request.path, exc))
            return Response(401, b"", "text/plain; charset=utf-8")

        matched = self.router.match(request.method, request.path)
        if matched is None:
            if request.path.startswith("/api"):
                return json_response({"error": "接口不存在: %s" % request.path}, 404)
            if request.method in ("GET", "HEAD"):
                return self._serve_frontend(request.path)
            return json_response({"error": "不支持的方法"}, 405)

        handler, params = matched
        request.params = params
        try:
            result = handler(request)
            if isinstance(result, Response):
                return result
            if result is None:
                return json_response({"result": "success"})
            return json_response(result)
        except ApiError as exc:
            if exc.raw:
                return Response(exc.status, exc.message.encode("utf-8"), "application/json")
            return json_response({"error": exc.message}, exc.status)
        except Exception as exc:  # noqa: BLE001 - last line of defence, log and answer
            self.log("500 %s %s: %s\n%s" % (request.method, request.path, exc, traceback.format_exc()))
            return json_response({"error": str(exc) or exc.__class__.__name__}, 500)

    def _serve_frontend(self, path: str) -> Response:
        """Serve the SPA, with the built-in shim as a fallback overlay."""
        result = serve_static(self.static_root, path)
        if isinstance(result, Response) and result.status == 200:
            if path.rstrip("/") in ("", "/", "/index.html") and self.config.get_bool("ui_shim", True):
                return self._inject_shim(result)
            return result
        # Not in the frontend: try the overlay (shim assets we add).
        if os.path.isdir(self.shim_root):
            overlay = serve_static(self.shim_root, path)
            if isinstance(overlay, Response) and overlay.status == 200:
                return overlay
        if isinstance(result, Response):
            return result
        return json_response({"error": str(result)}, 404)

    def _inject_shim(self, response: Response) -> Response:
        """Append the shim script to index.html."""
        marker = b"</body>"
        tag = b'<script src="/ufi-linux-shim.js" defer></script>\n</body>'
        if marker not in response.body:
            return response
        body = response.body.replace(marker, tag, 1)
        headers = dict(response.headers or {})
        headers["Cache-Control"] = "no-store"
        return Response(response.status, body, response.content_type, headers)

    # -- lifecycle ----------------------------------------------------------
    def make_server(self, bind: Optional[str] = None, port: Optional[int] = None,
                    quiet: bool = False) -> HTTPServer:
        host = bind or str(self.config.get("bind") or "0.0.0.0")
        chosen = int(port or self.config.get_int("port", 2333))
        return HTTPServer((host, chosen), self.dispatch, logger=self.log, quiet=quiet)

    def start_background(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = threading.Thread(target=self._scheduler_loop, name="ufi-scheduler", daemon=True)
        self._scheduler.start()

    def stop_background(self) -> None:
        self._scheduler_stop.set()

    def _scheduler_loop(self) -> None:
        from . import traffic
        from .tasks import run_due_restart, run_due_tasks

        while not self._scheduler_stop.wait(20.0):
            try:
                traffic.sample(self)
            except Exception as exc:  # noqa: BLE001 - accounting must not kill the loop
                self.log("traffic: %s" % exc)
            try:
                run_due_tasks(self)
                run_due_restart(self)
            except Exception as exc:  # noqa: BLE001 - a bad task must not kill the loop
                self.log("scheduler: %s" % exc)

    def serve_forever(self, bind: Optional[str] = None, port: Optional[int] = None,
                      quiet: bool = False) -> None:
        server = self.make_server(bind=bind, port=port, quiet=quiet)
        self.start_background()
        host, chosen = server.server_address[:2]
        self.log("UFI-TOOLS %s listening on http://%s:%s/ (static: %s)" % (
            __version__, host, chosen, self.static_root))
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            pass
        finally:
            self.stop_background()
            server.server_close()

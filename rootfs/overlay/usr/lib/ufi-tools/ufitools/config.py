"""Configuration storage.

Everything lives in ``config.json`` under the data directory: the access token,
the service settings, the hardware unit names, the forwarding configuration and
the traffic thresholds.  Key names follow the ones the Android app used, so a
preferences export from a device can be imported and the two implementations
stay comparable.

Data directory resolution order:

1. ``$UFI_TOOLS_DATA``
2. ``/var/lib/ufi-tools`` when running as root (the systemd case)
3. ``$XDG_DATA_HOME/ufi-tools`` or ``~/.local/share/ufi-tools``
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid as uuidlib
from typing import Any, Dict, Optional

from .auth import DEFAULT_TOKEN, is_sha256_hex, is_weak_token, normalize_token, sha256_hex

DEFAULT_RES_SERVER = "https://pan.kanokano.cn"
DEFAULT_TTYD_PORT = 1146
DEFAULT_HTTP_PORT = 2333

DEFAULTS: Dict[str, Any] = {
    "login_token": sha256_hex(DEFAULT_TOKEN),
    "login_token_enabled": True,
    "kano_max_skew_ms": 0,
    "nickname": "",
    "model": "",
    "device_uuid": "",
    "isReadUseTerms": False,
    "bind": "0.0.0.0",
    "port": DEFAULT_HTTP_PORT,
    "static_root": "",
    "uploads_dir": "",
    "kano_is_debug": False,
    "GLOBAL_SERVER_URL": DEFAULT_RES_SERVER,
    "ttyd_port": DEFAULT_TTYD_PORT,
    "ttyd_unit": "ttyd.service",
    "advanced_enabled": False,
    # -- Linux bridges ------------------------------------------------------
    #: The modem tty must have exactly one owner, and on this image that is
    #: e5-atd (the mu300-atd port): it serves a fifo, not a socket, so AT goes
    #: through the e5-at client rather than through a direct open of the tty.
    "at_socket": "",
    "at_device": "",
    "at_command": "/opt/e5/e5-at {cmd}",
    "at_timeout": 8.0,
    #: Modem-derived fields (signal, operator, IMEI...) need AT, and the E5's CP
    #: dies if AT is polled hard, so they are served from a cache refreshed at
    #: most this often.  0 disables AT-derived fields entirely.
    "at_poll_interval": 60.0,
    "mobile_data_unit": "e5-mobile-data.service",
    "hotspot_unit": "e5-hotspot.service",
    "wlan_interface": "wlan0",
    "hotspot_conf": "/etc/hostapd/e5.conf",
    "hotspot_conf_2g": "/etc/hostapd/e5-2g.conf",
    "hotspot_conf_5g": "/etc/hostapd/e5.conf",
    "hotspot_band": "5g",
    "dnsmasq_conf": "/etc/dnsmasq.d/e5-hotspot.conf",
    "traffic_interfaces": "",
    #: Best-effort hardware toggles; empty means "not present on this board".
    "led_names": "",
    "samba_unit": "",
    #: Serve the built-in frontend shim (hides the vendor-only panels and adds
    #: the native device console).  Turn off to serve the frontend untouched.
    "ui_shim": True,
    "kano_data_flow_limit_enabled": "0",
    "kano_data_limit_status_forward_enabled": "0",
    "kano_data_flow_max_limit": -1,
    "kano_data_flow_check_daily_or_monthly": "monthly",
    "kano_data_check_reference": "android",
    "volte_status_0": "1",
    "volte_status_1": "1",
    "vonr_status_0": "0",
    "vonr_status_1": "0",
    "sms_forward_method": "",
    "sms_forward_enabled": "0",
    "kano_power_status_forward_enabled": "0",
    "kano_sms_blacklist_phone": "",
    "kano_sms_blacklist_keywords": "",
    "kano_smtp_host": "",
    "kano_smtp_port": "465",
    "kano_smtp_to": "",
    "kano_smtp_username": "",
    "kano_smtp_password": "",
    "kano_smtp_forward_dev_info": "0",
    "kano_curl_text": "",
    "kano_dingtalk_url": "",
    "kano_dingtalk_secret": "",
    "kano_dingtalk_forward_dev_info": "0",
}


def default_data_dir() -> str:
    env = os.environ.get("UFI_TOOLS_DATA")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    try:
        if os.geteuid() == 0:
            return "/var/lib/ufi-tools"
    except AttributeError:  # non-POSIX
        pass
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "ufi-tools")


class Config:
    """Thread-safe JSON-backed key/value store with Android-compatible keys."""

    #: How often at most the file is stat()-ed for external changes.  Cheap
    #: enough to do on every read, but there is no point doing it more often
    #: than an operator can type.
    RELOAD_INTERVAL = 2.0

    def __init__(self, data_dir: Optional[str] = None, filename: str = "config.json"):
        self.data_dir = data_dir or default_data_dir()
        self.path = os.path.join(self.data_dir, filename)
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self._mtime: float = 0.0
        self._checked_at: float = 0.0
        self.load()

    # -- persistence --------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict):
                    self.data.update(stored)
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                # A corrupt config must not stop the service: keep the defaults
                # and leave the broken file in place for the operator.
                pass
            self._migrate()
            self._mtime = self._stat_mtime()

    def _stat_mtime(self) -> float:
        try:
            return os.stat(self.path).st_mtime
        except OSError:
            return 0.0

    def maybe_reload(self) -> None:
        """Pick up a config.json edited by ``ufi-tools set-token`` or by hand.

        The service is long-lived and would otherwise keep the token it read at
        start-up, so a token rotated on the command line would silently stop
        working until a restart.
        """
        now = time.monotonic()
        with self._lock:
            if now - self._checked_at < self.RELOAD_INTERVAL:
                return
            self._checked_at = now
            mtime = self._stat_mtime()
            if mtime and mtime != self._mtime:
                self._mtime = mtime
                self._reload_locked()

    def _reload_locked(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                self.data = dict(DEFAULTS)
                self.data.update(stored)
                self._migrate()
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        with self._lock:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            self._mtime = self._stat_mtime()

    def _migrate(self) -> None:
        """Apply the same fix-ups as ``KanoUtils.transformLoginToken``."""
        token = self.data.get("login_token")
        if token and not is_sha256_hex(str(token)):
            self.data["login_token"] = normalize_token(str(token))
        if not self.data.get("device_uuid"):
            self.data["device_uuid"] = str(uuidlib.uuid4())

    # -- accessors ----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        self.maybe_reload()
        with self._lock:
            if key in self.data:
                return self.data[key]
            if key in DEFAULTS:
                return DEFAULTS[key]
            return default

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self.data[key] = value
        if persist:
            self.save()

    def update(self, values: Dict[str, Any], persist: bool = True) -> None:
        with self._lock:
            self.data.update(values)
        if persist:
            self.save()

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        value = self.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # -- derived ------------------------------------------------------------
    @property
    def token_hash(self) -> str:
        return normalize_token(str(self.get("login_token") or ""))

    @property
    def token_enabled(self) -> bool:
        return self.get_bool("login_token_enabled", True)

    @property
    def is_weak_token(self) -> bool:
        return is_weak_token(self.token_hash)

    def set_token(self, plaintext: str) -> None:
        self.update({"login_token": sha256_hex(plaintext), "kano_weak_token": False})

    @property
    def uploads_dir(self) -> str:
        configured = str(self.get("uploads_dir") or "").strip()
        return configured or os.path.join(self.data_dir, "uploads")

    @property
    def at_poll_interval(self) -> float:
        return max(0.0, self.get_float("at_poll_interval", 60.0))

    def as_public_dict(self) -> Dict[str, Any]:
        """Everything except secrets, for diagnostics pages."""
        hidden = {"login_token", "kano_smtp_password"}
        return {k: v for k, v in self.data.items() if k not in hidden}

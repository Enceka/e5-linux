"""Cached modem state: from ModemManager, or AT-derived.

On the E5 ModemManager owns the modem (docs/FINDINGS.md 37) and already keeps
everything the UI shows -- registration, operator, access technology, signal,
the SIM, the bearer -- so the snapshot reads it over D-Bus (``mmcli -J``) and
sends no AT at all.  The AT path below is the fallback for an image without
ModemManager.

Signal strength, operator, registration and the SIM identity only exist behind
AT commands, and AT is the one resource on this device that must not be polled
hard: the E5's CP asserts (``MN_AL Task PS CP assert ... queue was full``) when
the command channel is used faster than Android's RIL would, which is why
``e5-atd`` owns the tty and serialises its callers, and why this cache exists.

The web UI, however, polls its status block once per second.  The two are
reconciled here: :class:`ModemSnapshot` keeps the last answer and refreshes it in
a background thread at most once per ``at_poll_interval`` seconds (60 by
default).  Requests always read the cache, so the UI stays at 1 Hz while the
modem sees at most one command burst per minute.  Setting the interval to 0
disables AT entirely and every derived field becomes empty.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional

#: Read-only commands, in the order they are issued.  Nothing here changes modem
#: state, so a refresh is safe to run at any time.
COMMANDS = (
    ("csq", "AT+CSQ"),
    ("cesq", "AT+CESQ"),
    ("cops", "AT+COPS?"),
    ("creg", "AT+CREG?"),
    ("cereg", "AT+CEREG?"),
    ("imei", "AT+CGSN"),
    ("imsi", "AT+CIMI"),
    ("iccid", "AT+CCID"),
    ("cnum", "AT+CNUM"),
    ("cgev", "AT+CGDCONT?"),
    ("cGCONTRDP", "AT+CGCONTRDP"),
)

#: ``AT+COPS?`` access technology -> what the UI shows.
_ACT_NAMES = {
    0: "2G",
    1: "2G",
    2: "3G",
    3: "3G",
    4: "3G",
    5: "3G",
    6: "3G",
    7: "4G",
    8: "4G",
    9: "4G",
    10: "5G",
    11: "5G",
    13: "4G",
}

_NUMERIC = re.compile(r"(-?\d+)")


def _ints(text: str):
    return [int(value) for value in _NUMERIC.findall(text or "")]


def _quoted(text: str):
    return re.findall(r'"([^"]*)"', text or "")


def _mmcli(*args: str, timeout: float = 10.0) -> Dict[str, Any]:
    """One mmcli call with JSON output; {} when it fails."""
    try:
        out = subprocess.run(("mmcli", "-J") + args, capture_output=True, text=True,
                             timeout=timeout, check=False)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def _mm_value(value: Any) -> str:
    """mmcli prints "--" for an unset property."""
    if isinstance(value, list):
        value = value[0] if value else ""
    value = "" if value is None else str(value)
    return "" if value == "--" else value


def modemmanager_available() -> bool:
    if not shutil.which("mmcli"):
        return False
    try:
        return subprocess.run(("systemctl", "-q", "is-active", "ModemManager"),
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


#: ModemManager's registration states -> the 27.007 <stat> the UI expects.
_MM_REG_STAT = {"idle": "0", "home": "1", "searching": "2", "denied": "3",
                "unknown": "4", "roaming": "5", "home-sms-only": "6",
                "roaming-sms-only": "7", "emergency-only": "8"}


def _mm_network_type(techs: str) -> str:
    techs = techs.lower()
    for key, name in (("5gnr", "5G"), ("lte", "4G"), ("hspa", "3G"), ("umts", "3G"),
                      ("edge", "2G"), ("gprs", "2G"), ("gsm", "2G")):
        if key in techs:
            return name
    return ""


def modemmanager_snapshot() -> Dict[str, str]:
    """The fields :func:`derive` produces, read from ModemManager."""
    modem = _mmcli("-m", "any").get("modem", {})
    if not modem:
        return {}
    generic = modem.get("generic", {})
    gpp = modem.get("3gpp", {})
    raw: Dict[str, str] = {}

    raw["imei"] = _mm_value(gpp.get("imei")) or _mm_value(generic.get("equipment-identifier"))
    raw["network_provider"] = _mm_value(gpp.get("operator-name"))
    state = _mm_value(gpp.get("registration-state"))
    if state in _MM_REG_STAT:
        raw["reg_status"] = _MM_REG_STAT[state]
    raw["network_type"] = _mm_network_type(" ".join(generic.get("access-technologies") or []))
    raw["msisdn"] = _mm_value(generic.get("own-numbers"))
    quality = (generic.get("signal-quality") or {}).get("value")
    if _mm_value(quality):
        raw["signal_quality"] = _mm_value(quality)

    sim_path = _mm_value(generic.get("sim"))
    if sim_path:
        props = _mmcli("-i", sim_path).get("sim", {}).get("properties", {})
        raw["imsi"] = _mm_value(props.get("imsi"))
        raw["iccid"] = _mm_value(props.get("iccid"))

    # extended signal: ModemManager polls it only once a refresh rate is set
    signal = _mmcli("-m", "any", "--signal-get").get("modem", {}).get("signal", {})
    if not _mm_value((signal.get("refresh") or {}).get("rate")) or \
            _mm_value((signal.get("refresh") or {}).get("rate")) == "0":
        _mmcli("-m", "any", "--signal-setup=60")
    for tech in ("5g", "lte"):
        block = signal.get(tech) or {}
        rsrp = _mm_value(block.get("rsrp"))
        if rsrp:
            raw["lte_rsrp"] = str(int(float(rsrp)))
            raw["Z5g_rsrp"] = raw["lte_rsrp"]
            rsrq = _mm_value(block.get("rsrq"))
            if rsrq:
                raw["lte_rsrq"] = "%.1f" % float(rsrq)
            break

    for path in generic.get("bearers") or []:
        bearer = _mmcli("-b", path).get("bearer", {})
        if _mm_value((bearer.get("status") or {}).get("connected")) != "yes":
            continue
        raw["apn"] = _mm_value((bearer.get("properties") or {}).get("apn"))
        raw["ipv4_wan_ipaddr"] = _mm_value((bearer.get("ipv4-config") or {}).get("address"))
        break

    out = {key: value for key, value in raw.items() if value}
    bar = _signal_bar(out.get("lte_rsrp", ""))
    if bar:
        out["network_signalbar"] = bar
    return out


def _signal_bar(rsrp_text: str) -> str:
    """Signal bars, 0..5, using the thresholds the Android UI used."""
    rsrp = _ints(rsrp_text)
    if not rsrp:
        return ""
    for bar, floor in (("5", -80), ("4", -90), ("3", -100), ("2", -110), ("1", -120)):
        if rsrp[0] >= floor:
            return bar
    return "0"


class ModemSnapshot:
    """Thread-safe cache of read-only modem state."""

    def __init__(self, at_runner, interval: float = 60.0, logger=None):
        self.at = at_runner
        self.interval = max(0.0, float(interval or 0.0))
        self.log = logger or (lambda message: None)
        self._data: Dict[str, str] = {}
        self._raw: Dict[str, str] = {}
        self._refreshed_at = 0.0
        self._lock = threading.RLock()
        self._running = False

    # -- cache -------------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        self._kick()
        with self._lock:
            return self._data.get(key, default)

    def raw(self, key: str, default: str = "") -> str:
        with self._lock:
            return self._raw.get(key, default)

    def as_dict(self) -> Dict[str, str]:
        self._kick()
        with self._lock:
            return dict(self._data)

    @property
    def age(self) -> float:
        return time.time() - self._refreshed_at if self._refreshed_at else -1.0

    # -- refresh -----------------------------------------------------------
    def _stale(self) -> bool:
        if self.interval <= 0:
            return False
        if not self._refreshed_at:
            return True
        return (time.time() - self._refreshed_at) >= self.interval

    def _kick(self) -> None:
        """Start a background refresh when the cache is old."""
        with self._lock:
            if self._running or not self._stale() or self.interval <= 0:
                return
            if not modemmanager_available() and not self.at.available():
                return
            self._running = True
        threading.Thread(target=self._refresh_worker, name="ufi-modem", daemon=True).start()

    def refresh_now(self) -> Dict[str, str]:
        """Synchronous refresh; used by tests and by ``ufi-tools status``."""
        return self._refresh_worker()

    def _refresh_worker(self) -> Dict[str, str]:
        if modemmanager_available():
            derived: Dict[str, str] = {}
            try:
                derived = modemmanager_snapshot()
            finally:
                with self._lock:
                    self._raw = {}
                    self._data = derived
                    self._refreshed_at = time.time()
                    self._running = False
            return derived
        raw: Dict[str, str] = {}
        try:
            for name, command in COMMANDS:
                try:
                    raw[name] = self.at.run(command)
                except Exception as exc:  # noqa: BLE001 - missing modem is normal
                    raw[name] = ""
                    self.log("modem: %s failed: %s" % (command, exc))
        finally:
            derived = derive(raw)
            with self._lock:
                self._raw = raw
                self._data = derived
                self._refreshed_at = time.time()
                self._running = False
        return derived


def derive(raw: Dict[str, str]) -> Dict[str, str]:
    """Turn raw AT responses into the fields the UI displays."""
    out: Dict[str, str] = {}

    csq = _ints(raw.get("csq", ""))
    if len(csq) >= 1 and 0 <= csq[0] <= 31:
        out["rssi"] = str(-113 + 2 * csq[0])
        out["network_rssi"] = out["rssi"]

    cesq = _ints(raw.get("cesq", ""))
    # +CESQ: <rxlev>,<ber>,<rscp>,<ecno>,<rsrq>,<rsrp>
    if len(cesq) >= 6:
        if 0 <= cesq[4] <= 34:
            out["lte_rsrq"] = "%.1f" % (-19.5 + cesq[4] * 0.5)
        if 0 <= cesq[5] <= 97:
            rsrp = -140 + cesq[5]
            out["lte_rsrp"] = str(rsrp)
            out["Z5g_rsrp"] = str(rsrp)

    cops = raw.get("cops", "")
    names = _quoted(cops)
    if names:
        out["network_provider"] = names[0]
    acts = _ints(cops.split(":", 1)[-1]) if ":" in cops else _ints(cops)
    if acts:
        act = acts[-1]
        if act in _ACT_NAMES:
            out["network_type"] = _ACT_NAMES[act]

    for key in ("creg", "cereg"):
        values = _ints(raw.get(key, ""))
        if not values:
            continue
        # +CREG: <n>,<stat> -- the status is the second field when <n> is present.
        out["reg_status"] = str(values[1] if len(values) >= 2 else values[0])
        break

    for field, key in (("imei", "imei"), ("imsi", "imsi"), ("iccid", "iccid")):
        text = raw.get(field, "")
        digits = re.sub(r"\D", "", text or "")
        if digits:
            out[key] = digits
    ccid = raw.get("iccid", "")
    if ccid and not out.get("iccid"):
        hexish = re.sub(r"[^0-9A-Fa-f]", "", ccid.split(":", 1)[-1])
        if len(hexish) >= 18:
            out["iccid"] = hexish

    # +CNUM: ,"<number>",<type> -- the first field is deliberately empty.
    cnum = [value for value in _quoted(raw.get("cnum", "")) if value]
    if cnum:
        out["msisdn"] = cnum[0]

    # AT+CGCONTRDP gives "cid,bearer_id,\"apn\",\"local_addr\",...".
    for line in (raw.get("cGCONTRDP") or "").splitlines():
        if "+CGCONTRDP" not in line:
            continue
        fields = _quoted(line)
        if len(fields) >= 2:
            out.setdefault("apn", fields[0])
            out.setdefault("ipv4_wan_ipaddr", fields[1])
        else:
            parts = line.split(":", 1)[-1].split(",")
            if len(parts) >= 3:
                out.setdefault("ipv4_wan_ipaddr", parts[2].strip().strip('"'))

    if not out.get("apn"):
        apns = _quoted(raw.get("cgev", ""))
        if apns:
            out["apn"] = apns[-1]

    bar = _signal_bar(out.get("lte_rsrp", ""))
    if bar:
        out["network_signalbar"] = bar
    return out

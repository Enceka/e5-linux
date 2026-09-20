"""Local device information gathered from /proc and /sys.

Port of the Android app's ``DeviceInfo.kt``.

The Android file and this one read the *same* Linux interfaces, which is the
happy accident that makes this port small: ``/proc/stat``, ``/proc/meminfo``,
``/sys/class/thermal``, ``/sys/class/power_supply`` and ``/sys/bus/usb/devices``
are kernel interfaces, not Android APIs.  What is Android-specific is only the
holder: ``NetworkStatsManager`` for per-UID traffic and ``BatteryManager`` for
the percentage.

Everything takes a ``root`` prefix so the collectors can be pointed at a
fixture tree in tests (``System(root=tests/fixtures/e5)``).
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

#: Thermal zone names that are not the SoC (same filter as the Kotlin code).
_THERMAL_EXCLUDE = ("chg", "front", "frame", "wcn", "usb", "bcl", "interface", "skin", "back")

_CPU_CORE_OK = lambda name: name.startswith("cpu") and name[3:].isdigit()  # noqa: E731

_UDC_SPEED_LABELS = {
    "low-speed": "USB 1.0 (1.5Mbps)",
    "full-speed": "USB 1.1 (12Mbps)",
    "high-speed": "USB 2.0 (480Mbps)",
    "super-speed": "USB 3.0 (5Gbps)",
    "super-speed-plus": "USB 3.1 (10Gbps)",
}


class ProcSys:
    """Read-only access to a (possibly relocated) /proc and /sys."""

    def __init__(self, root: str = "/"):
        self.root = "/" if root in ("", "/") else root.rstrip("/")

    def path(self, absolute: str) -> str:
        if self.root == "/":
            return absolute
        return self.root + absolute

    def read(self, absolute: str) -> Optional[str]:
        try:
            with open(self.path(absolute), "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return None

    def read_trimmed(self, absolute: str) -> Optional[str]:
        data = self.read(absolute)
        return data.strip() if data is not None else None

    def read_int(self, absolute: str, default: Optional[int] = None) -> Optional[int]:
        raw = self.read_trimmed(absolute)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def exists(self, absolute: str) -> bool:
        return os.path.exists(self.path(absolute))

    def listdir(self, absolute: str) -> List[str]:
        try:
            return sorted(os.listdir(self.path(absolute)))
        except OSError:
            return []


def _fmt1(value: float) -> str:
    return "%.1f" % value


class DeviceInfo:
    """Collects the numbers behind /api/baseDeviceInfo and /api/connInfo."""

    def __init__(self, root: str = "/", cpu_sample_interval: float = 0.1):
        self.fs = ProcSys(root)
        self.cpu_sample_interval = cpu_sample_interval
        self._lock = threading.RLock()
        self._prev_cpu: Dict[str, Tuple[int, int]] = {}

    # -- CPU ---------------------------------------------------------------
    def _read_proc_stat(self) -> Dict[str, Tuple[int, int]]:
        text = self.fs.read("/proc/stat")
        stats: Dict[str, Tuple[int, int]] = {}
        if not text:
            return stats
        for line in text.splitlines():
            if not line.startswith("cpu"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            name = parts[0]
            if name != "cpu" and not _CPU_CORE_OK(name):
                continue
            values = [int(v) for v in parts[1:] if v.lstrip("-").isdigit()]
            if not values:
                continue
            total = sum(values)
            # idle + iowait, exactly as DeviceInfo.kt:158-159
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            stats[name] = (total, idle)
        return stats

    def cpu_usage(self, force_sample: bool = False) -> Tuple[Dict[str, str], Optional[float]]:
        """Return (per-core usage JSON, overall usage).

        Like the Android implementation the first call has no baseline, so it
        takes two samples ``cpu_sample_interval`` apart.  Later calls reuse the
        previous sample, which makes the endpoint cheap to poll at 1 Hz.
        """
        with self._lock:
            current = self._read_proc_stat()
            baseline = self._prev_cpu
            if not baseline or force_sample:
                baseline = current
                time.sleep(self.cpu_sample_interval)
                current = self._read_proc_stat()

            usage: Dict[str, str] = {}
            overall: Optional[float] = None
            for name, (total, idle) in baseline.items():
                now = current.get(name)
                if not now:
                    continue
                total_diff = now[0] - total
                idle_diff = now[1] - idle
                if total_diff <= 0:
                    value = 0.0
                else:
                    value = (total_diff - idle_diff) * 100.0 / total_diff
                    value = min(100.0, max(0.0, value))
                text = _fmt1(value)
                usage[name] = text
                if name == "cpu":
                    overall = float(text)
            self._prev_cpu = current
            return usage, overall

    def cpu_freq(self) -> Dict[str, Dict[str, int]]:
        result: Dict[str, Dict[str, int]] = {}
        for name in self.fs.listdir("/sys/devices/system/cpu"):
            if not _CPU_CORE_OK(name):
                continue
            base = "/sys/devices/system/cpu/%s/cpufreq" % name
            cur = self.fs.read_int(base + "/scaling_cur_freq", 0) or 0
            top = self.fs.read_int(base + "/cpuinfo_max_freq", 0) or 0
            result[name] = {"cur": cur // 1000, "max": top // 1000}
        return result

    # -- memory ------------------------------------------------------------
    def memory(self) -> Tuple[Dict[str, Any], float]:
        values = {"MemTotal": 0, "MemAvailable": 0, "SwapTotal": 0, "SwapFree": 0}
        text = self.fs.read("/proc/meminfo") or ""
        for line in text.splitlines():
            key = line.split(":")[0]
            if key in values:
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    values[key] = int(parts[1])
        used = values["MemTotal"] - values["MemAvailable"]
        percent = (used * 100.0 / values["MemTotal"]) if values["MemTotal"] > 0 else 0.0
        swap_used = values["SwapTotal"] - values["SwapFree"]
        swap_percent = (swap_used * 100.0 / values["SwapTotal"]) if values["SwapTotal"] > 0 else 0.0
        info = {
            "mem_total_kb": values["MemTotal"],
            "mem_available_kb": values["MemAvailable"],
            "mem_used_kb": used,
            "mem_usage_percent": _fmt1(percent),
            "swap_total_kb": values["SwapTotal"],
            "swap_free_kb": values["SwapFree"],
            "swap_used_kb": swap_used,
            "swap_usage_percent": _fmt1(swap_percent),
        }
        return info, float(_fmt1(percent))

    # -- thermal -----------------------------------------------------------
    def thermal(self) -> Tuple[int, List[Dict[str, Any]]]:
        zones: List[Dict[str, Any]] = []
        for entry in self.fs.listdir("/sys/class/thermal"):
            if not entry.startswith("thermal_zone"):
                continue
            base = "/sys/class/thermal/%s" % entry
            zone_type = self.fs.read_trimmed(base + "/type")
            if not zone_type:
                continue
            if any(token in zone_type for token in _THERMAL_EXCLUDE):
                continue
            temp = self.fs.read_int(base + "/temp")
            if temp is None or not (0 <= temp <= 124000):
                continue
            zones.append({"type": zone_type, "temp": temp})
        max_temp = max((z["temp"] for z in zones), default=-1)
        return max_temp, zones

    # -- power -------------------------------------------------------------
    def battery(self) -> Dict[str, Any]:
        """Battery percent/status/current/voltage from /sys/class/power_supply."""
        percent: Optional[int] = None
        status: Optional[str] = None
        current_ua: Optional[int] = None
        voltage_uv: Optional[int] = None

        for entry in self.fs.listdir("/sys/class/power_supply"):
            base = "/sys/class/power_supply/%s" % entry
            capacity = self.fs.read_int(base + "/capacity")
            entry_type = (self.fs.read_trimmed(base + "/type") or "").lower()
            if capacity is not None and entry_type == "battery":
                percent = capacity
                status = self.fs.read_trimmed(base + "/status")
                current_ua = self.fs.read_int(base + "/current_now")
                voltage_uv = self.fs.read_int(base + "/voltage_now")
                break

        # Android keeps these under .../power_supply/battery/; some boards name
        # the same node differently, so fall back to the conventional path.
        if percent is None:
            base = "/sys/class/power_supply/battery"
            percent = self.fs.read_int(base + "/capacity")
            status = self.fs.read_trimmed(base + "/status")
            current_ua = self.fs.read_int(base + "/current_now")
            voltage_uv = self.fs.read_int(base + "/voltage_now")

        return {
            "percent": percent if percent is not None else -1,
            "status": status,
            "current_uA": current_ua if current_ua is not None else -1,
            "voltage_uV": voltage_uv if voltage_uv is not None else -1,
        }

    # -- USB ---------------------------------------------------------------
    def usb(self) -> Tuple[int, Dict[str, Any]]:
        devices: List[Dict[str, Any]] = []
        max_speed = 0
        for entry in self.fs.listdir("/sys/bus/usb/devices"):
            base = "/sys/bus/usb/devices/%s" % entry
            product = self.fs.read_trimmed(base + "/product")
            raw_speed = self.fs.read_trimmed(base + "/speed")
            if not product or raw_speed is None:
                continue
            # Same exclusions as DeviceInfo.kt:420-424: root hubs are not
            # user-visible Type-C devices.
            if entry.startswith("usb"):
                continue
            if "host controller" in product.lower() or "hdrc" in product.lower():
                continue
            try:
                speed = int(float(raw_speed))
            except ValueError:
                speed = 0
            max_speed = max(max_speed, speed)
            devices.append({"path": entry, "product": product, "speed": speed})

        # Type-C host/gadget mode.  Android reads
        # /sys/class/android_usb/android0/state; on mainline Linux the same
        # information is available through the role switch or the UDC list.
        type_c_mode = "unknown"
        state = self.fs.read_trimmed("/sys/class/android_usb/android0/state")
        if state:
            type_c_mode = "host" if state.upper() == "DISCONNECTED" else "gadget"
        elif self.fs.listdir("/sys/class/udc"):
            type_c_mode = "gadget"
        elif self.fs.exists("/sys/bus/usb/devices/usb1"):
            type_c_mode = "host"

        gadget_speed = "unknown"
        if type_c_mode == "gadget":
            for udc in self.fs.listdir("/sys/class/udc"):
                raw = self.fs.read_trimmed("/sys/class/udc/%s/current_speed" % udc)
                if raw and raw != "UNKNOWN":
                    gadget_speed = _UDC_SPEED_LABELS.get(raw, raw)
                    break

        details = {
            "typec_mode": type_c_mode,
            "gadget_speed": gadget_speed,
            "devices": devices,
        }
        return max_speed, details

    # -- connections -------------------------------------------------------
    def conn_counts(self) -> Dict[str, int]:
        tcp_total, tcp_active = self._count_tcp("/proc/net/tcp")
        result = {
            "tcp": tcp_total,
            "tcp_active": tcp_active,
            "tcp_other": (tcp_total - tcp_active) if tcp_total >= 0 and tcp_active >= 0 else -1,
            "tcp6": self._count_lines("/proc/net/tcp6"),
            "udp": self._count_lines("/proc/net/udp"),
            "udp6": self._count_lines("/proc/net/udp6"),
            "unix": self._count_lines("/proc/net/unix"),
        }
        return result

    def _count_tcp(self, path: str) -> Tuple[int, int]:
        text = self.fs.read(path)
        if text is None:
            return -1, -1
        total = 0
        active = 0
        for line in text.splitlines()[1:]:
            if not line:
                continue
            total += 1
            parts = line.split()
            if len(parts) >= 4 and parts[3] == "01":  # ESTABLISHED
                active += 1
        return total, active

    def _count_lines(self, path: str) -> int:
        text = self.fs.read(path)
        if text is None:
            return -1
        return sum(1 for line in text.splitlines()[1:] if line)

    # -- storage / uptime --------------------------------------------------
    def storage(self, path: str) -> Dict[str, int]:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            return {"total": 0, "used": 0, "available": 0}
        return {"total": usage.total, "used": usage.used, "available": usage.free}

    def uptime(self) -> int:
        text = self.fs.read_trimmed("/proc/uptime")
        if not text:
            return -1
        try:
            return int(float(text.split()[0]))
        except (ValueError, IndexError):
            return -1

    def load_average(self) -> Optional[List[float]]:
        text = self.fs.read_trimmed("/proc/loadavg")
        if not text:
            return None
        try:
            return [float(v) for v in text.split()[:3]]
        except ValueError:
            return None

    def model(self) -> str:
        """Best-effort model string from DMI, device tree or /proc/cpuinfo."""
        for path in (
            "/sys/firmware/devicetree/base/model",
            "/sys/devices/virtual/dmi/id/product_name",
            "/proc/device-tree/model",
        ):
            raw = self.fs.read_trimmed(path)
            if raw:
                return raw.replace("\x00", "").strip()
        text = self.fs.read("/proc/cpuinfo") or ""
        for line in text.splitlines():
            if line.lower().startswith("hardware"):
                return line.split(":", 1)[1].strip()
        return ""

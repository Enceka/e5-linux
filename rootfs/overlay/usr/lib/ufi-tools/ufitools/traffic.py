"""Per-day traffic accounting -- the Linux replacement for ``NetworkStatsManager``.

Android asks the framework for a device-wide byte count.  On Linux the same
number is obtained by sampling the kernel's per-interface counters
(``/sys/class/net/<if>/statistics/{rx,tx}_bytes``) and remembering the delta.

Samples are taken by the background scheduler (every ~20 s) and accumulated into
``runtime.json`` as ``{"traffic": {"2026-09-19": {"rx": n, "tx": n}}}``, which
gives the web UI a working "daily" and "monthly" figure and makes
``/api/cellularUsage`` work for the ranges that have already been sampled.

The counters are cumulative and reset on reboot, so a sample smaller than the
previous one is treated as a reboot rather than a negative delta.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

COUNTER_PATH = "/sys/class/net/%s/statistics/%s_bytes"

#: Interfaces that never carry metered traffic.
_EXCLUDED = ("lo", "tun", "docker", "br-", "veth", "virbr", "tailscale", "zt")


def _read_counter(interface: str, direction: str) -> Optional[int]:
    try:
        with open(COUNTER_PATH % (interface, direction), "r", encoding="ascii") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def default_route_interface() -> Optional[str]:
    """Interface carrying the default route, from /proc/net/route."""
    try:
        with open("/proc/net/route", "r", encoding="ascii") as handle:
            for line in handle.readlines()[1:]:
                fields = line.split()
                if len(fields) >= 2 and fields[1] == "00000000" and int(fields[7], 16) & 0x2:
                    return fields[0]
    except (OSError, ValueError, IndexError):
        pass
    return None


def detect_interfaces(configured: str = "") -> List[str]:
    """Interfaces to account for: the configured list, else the default route."""
    if configured.strip():
        return [name.strip() for name in configured.split(",") if name.strip()]
    route = default_route_interface()
    if route and not route.startswith(_EXCLUDED):
        return [route]
    try:
        import os

        return [name for name in sorted(os.listdir("/sys/class/net")) if not name.startswith(_EXCLUDED)]
    except OSError:
        return []


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def sample(app) -> Optional[int]:
    """Take one sample and fold the delta into today's bucket.

    Also records the instantaneous rate, which is what the UI's throughput chart
    and the ``realtime_*`` fields show.
    """
    interfaces = detect_interfaces(str(app.config.get("traffic_interfaces") or ""))
    if not interfaces:
        return None

    total = 0
    previous = app.runtime.data.get("traffic_previous") or {}
    previous_at = float(app.runtime.data.get("traffic_previous_at") or 0.0)
    current: Dict[str, Dict[str, int]] = {}
    rx_delta_total = 0
    tx_delta_total = 0

    for interface in interfaces:
        rx = _read_counter(interface, "rx")
        tx = _read_counter(interface, "tx")
        if rx is None or tx is None:
            continue
        current[interface] = {"rx": rx, "tx": tx}
        total += rx + tx
        before = previous.get(interface)
        if before:
            rx_delta = rx - int(before.get("rx", rx))
            tx_delta = tx - int(before.get("tx", tx))
            # A reboot resets the kernel counters; treat that as a fresh start.
            if rx_delta >= 0 and tx_delta >= 0:
                rx_delta_total += rx_delta
                tx_delta_total += tx_delta

    if not current:
        return None

    now = time.time()
    delta = rx_delta_total + tx_delta_total
    if delta > 0:
        traffic = app.runtime.data.setdefault("traffic", {})
        bucket = traffic.setdefault(_today(), {"rx": 0, "tx": 0, "bytes": 0})
        bucket["rx"] = int(bucket.get("rx", 0)) + rx_delta_total
        bucket["tx"] = int(bucket.get("tx", 0)) + tx_delta_total
        bucket["bytes"] = int(bucket.get("bytes", 0)) + delta

    elapsed = max(0.0, now - previous_at) if previous_at else 0.0
    if elapsed > 0 and delta >= 0:
        app.runtime.data["traffic_rate"] = {
            "rx_bps": int(rx_delta_total / elapsed),
            "tx_bps": int(tx_delta_total / elapsed),
            "at": now,
        }
    app.runtime.data["traffic_previous"] = current
    app.runtime.data["traffic_previous_at"] = now
    app.runtime.save()
    return total


def rate(app) -> Dict[str, int]:
    """Last measured throughput in bytes/second (0/0 when not sampled yet)."""
    stored = app.runtime.data.get("traffic_rate") or {}
    return {"rx_bps": int(stored.get("rx_bps", 0)), "tx_bps": int(stored.get("tx_bps", 0))}


def calibrate(app, total_bytes: int) -> int:
    """Set today's counter to ``total_bytes`` (the UI's manual calibration)."""
    traffic = app.runtime.data.setdefault("traffic", {})
    bucket = traffic.setdefault(_today(), {"rx": 0, "tx": 0, "bytes": 0})
    bucket["bytes"] = max(0, int(total_bytes))
    app.runtime.save()
    return bucket["bytes"]


def _sum_bucket(bucket) -> int:
    if isinstance(bucket, dict):
        return int(bucket.get("bytes", 0))
    if isinstance(bucket, (int, float)):
        return int(bucket)
    return 0


def today_bytes(app) -> int:
    traffic = app.runtime.data.get("traffic") or {}
    return _sum_bucket(traffic.get(_today(), {}))


def month_bytes(app) -> int:
    traffic = app.runtime.data.get("traffic") or {}
    prefix = time.strftime("%Y-%m")
    return sum(_sum_bucket(value) for key, value in traffic.items() if str(key).startswith(prefix))


def range_bytes(app, start_ms: int, end_ms: int) -> int:
    traffic = app.runtime.data.get("traffic") or {}
    start_day = time.strftime("%Y-%m-%d", time.localtime(start_ms / 1000.0))
    end_day = time.strftime("%Y-%m-%d", time.localtime(end_ms / 1000.0))
    total = 0
    for key, value in traffic.items():
        if start_day <= str(key) <= end_day:
            total += _sum_bucket(value)
    return total


def range_daily(app, start_ms: int, end_ms: int) -> List[Dict[str, str]]:
    traffic = app.runtime.data.get("traffic") or {}
    start_day = time.strftime("%Y-%m-%d", time.localtime(start_ms / 1000.0))
    end_day = time.strftime("%Y-%m-%d", time.localtime(end_ms / 1000.0))
    return [
        {"date": str(key), "usage": str(_sum_bucket(value))}
        for key, value in sorted(traffic.items())
        if start_day <= str(key) <= end_day
    ]

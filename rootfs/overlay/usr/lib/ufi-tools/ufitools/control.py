"""Native control of the local Linux device.

This is the device's control plane: rather than asking a vendor web backend to
reboot the device or change the hotspot, UFI-TOOLS drives the Linux facilities
that already own those resources -- systemd units, NetworkManager, dnsmasq,
nftables, sysfs.

The hotspot is NetworkManager's "Hotspot" connection (an AP that is a port of
br0), the same one Phosh's Wi-Fi menu starts; every read and write goes through
``nmcli``.  E5-LINUX caveat: the initramfs overlay is copied over ``/etc`` on
every boot, so the profile ships read-only in
``/usr/lib/NetworkManager/system-connections`` and NetworkManager itself writes
the edited copy to ``/etc/NetworkManager/system-connections``, which is not in
the overlay and survives.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import shlex
import shutil
import socket
import struct
from typing import Any, Dict, List, Optional

from .shell import ShellResult, run_shell, systemctl, unit_active

_IFACE_RE = re.compile(r"^\s+(?:inet|inet6)\s+([0-9a-fA-F:.]+)(?:/(\d+))?", re.MULTILINE)
_STATION_MAC_RE = re.compile(r"^Station\s+([0-9a-fA-F:]{17})", re.MULTILINE)


class ControlError(Exception):
    """Raised for a control action that cannot be performed on this board."""


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


#: The hotspot settings read back from NetworkManager, in ``nmcli -t`` names.
NM_HOTSPOT_FIELDS = ("802-11-wireless.ssid,802-11-wireless.band,802-11-wireless.channel,"
                     "802-11-wireless.hidden,802-11-wireless-security.key-mgmt,"
                     "802-11-wireless-security.psk")

#: nftables table holding the hotspot's MAC allow/deny list (NetworkManager's AP
#: mode has none of its own): a bridge filter on frames that enter from wlan0.
ACL_TABLE = "e5acl"


def parse_nmcli_terse(text: str) -> Dict[str, str]:
    """``nmcli -t -f a,b connection show X`` prints ``a:value`` lines, with ``:``
    and ``\\`` inside values backslash-escaped."""
    result: Dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = re.sub(r"\\(.)", r"\1", value)
    return result


def auth_mode(key_mgmt: str) -> str:
    """Map NetworkManager's key-mgmt onto the auth names the web UI knows."""
    key_mgmt = (key_mgmt or "").strip().lower()
    if key_mgmt in ("", "none"):
        return "OPEN"
    if key_mgmt == "sae":
        return "WPA3-PSK"
    return "WPA2(AES)-PSK"


def _decode_ui_password(value: str) -> str:
    """The web UI sends the password base64-encoded (main.js encodeBase64)."""
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return value
    return decoded if decoded.isprintable() else value


def iface_ipv4(interface: str) -> Dict[str, str]:
    """Address and netmask of ``interface`` from /proc/net (no external tools)."""
    text = run_shell("ip -4 addr show dev %s" % interface, timeout=5.0).content
    info: Dict[str, str] = {}
    for match in _IFACE_RE.finditer(text or ""):
        address = match.group(1)
        if ":" in address:
            continue
        prefix = match.group(2)
        info["lan_ipaddr"] = address
        if prefix:
            try:
                info["lan_netmask"] = str(prefix)
            except (TypeError, ValueError):
                pass
        break
    if info.get("lan_ipaddr"):
        info["dhcpStart"], info["dhcpEnd"] = _dhcp_range_hint(info["lan_ipaddr"])
    return info


def _dhcp_range_hint(address: str) -> tuple:
    parts = address.split(".")
    if len(parts) != 4:
        return "", ""
    return ".".join(parts[:3] + ["2"]), ".".join(parts[:3] + ["200"])


class SystemControl:
    """Every write this project performs on the local device."""

    def __init__(self, app):
        self.app = app

    @property
    def config(self):
        return self.app.config

    # -- power -------------------------------------------------------------
    def reboot(self) -> ShellResult:
        # --no-block so the HTTP response gets out before the socket disappears.
        return run_shell("systemctl reboot --no-block", timeout=10)

    def poweroff(self) -> ShellResult:
        return run_shell("systemctl poweroff", timeout=10)

    # -- mobile data -------------------------------------------------------
    def mobile_data_status(self) -> Dict[str, Any]:
        unit = str(self.config.get("mobile_data_unit") or "")
        interface = self.gateway_interface()
        status: Dict[str, Any] = {
            "active": unit_active(unit) if unit else False,
            "unit": unit,
            "interface": interface,
        }
        if interface:
            info = iface_ipv4(interface)
            status.update(info)
        status["connected"] = bool(interface) and bool(status.get("lan_ipaddr"))
        status["ppp_status"] = "ppp_connected" if status["connected"] else "ppp_disconnected"
        return status

    def gateway_interface(self) -> str:
        """Interface holding the default route -- the cellular uplink."""
        from .traffic import default_route_interface

        return default_route_interface() or ""

    def set_mobile_data(self, enable: bool) -> ShellResult:
        unit = str(self.config.get("mobile_data_unit") or "")
        if not unit:
            raise ControlError("未配置蜂窝数据服务单元")
        return systemctl("start" if enable else "stop", unit)

    # -- hotspot -----------------------------------------------------------
    def _hotspot_name(self) -> str:
        return str(self.config.get("hotspot_connection") or "Hotspot")

    def _nmcli(self, args: str, timeout: float = 15.0) -> ShellResult:
        return run_shell("nmcli %s" % args, timeout=timeout)

    def hotspot_active(self) -> bool:
        out = self._nmcli("-t -f NAME connection show --active", timeout=5.0).content
        return self._hotspot_name() in (out or "").splitlines()

    def hotspot_values(self) -> Dict[str, str]:
        raw = parse_nmcli_terse(self._nmcli("-s -t -f %s connection show %s" % (
            NM_HOTSPOT_FIELDS, shlex.quote(self._hotspot_name())), timeout=5.0).content)
        band = raw.get("802-11-wireless.band", "")
        return {
            "ssid": raw.get("802-11-wireless.ssid", ""),
            "channel": raw.get("802-11-wireless.channel", ""),
            "hw_mode": "g" if band == "bg" else "a",
            "hidden": raw.get("802-11-wireless.hidden", "no"),
            "key_mgmt": raw.get("802-11-wireless-security.key-mgmt", ""),
            "psk": raw.get("802-11-wireless-security.psk", ""),
        }

    def hotspot_status(self) -> Dict[str, Any]:
        values = self.hotspot_values()
        lan = str(self.config.get("lan_interface") or "br0")
        return {
            "active": self.hotspot_active(),
            "connection": self._hotspot_name(),
            "unit": self._hotspot_name(),
            "managed_by": "NetworkManager",
            "interface": str(self.config.get("wlan_interface") or "wlan0"),
            "ssid": values["ssid"],
            "psk": values["psk"],
            "channel": values["channel"],
            "hw_mode": values["hw_mode"],
            "auth": auth_mode(values["key_mgmt"]),
            "hidden": values["hidden"] == "yes",
            # NetworkManager's AP mode has no station limit
            "max_clients": "",
            "country": "CN",
            "ipv4": iface_ipv4(lan).get("lan_ipaddr", ""),
        }

    def set_hotspot(self, enable: bool) -> ShellResult:
        name = shlex.quote(self._hotspot_name())
        if not enable:
            return self._nmcli("connection down %s" % name, timeout=20.0)
        # The WCN firmware can refuse the first beacon right after a boot; a
        # second activation has always gone through.
        result = self._nmcli("--wait 40 connection up %s" % name, timeout=45.0)
        if not result.done:
            result = self._nmcli("--wait 40 connection up %s" % name, timeout=45.0)
        return result

    def configure_hotspot(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Change the hotspot connection with ``nmcli connection modify``.

        Accepts the field names the vendor UI used (``SSID``/``Password``/
        ``AuthMode``/``ApBroadcastDisabled``/``channel``/``hw_mode``) and the
        plain ones (``ssid``/``psk``/``auth``/``hidden``); an active hotspot is
        brought up again with the new settings.
        """
        props: List[tuple] = []
        applied: Dict[str, Any] = {}

        def given(*names):
            for name in names:
                if name in updates and updates[name] not in (None, ""):
                    return str(updates[name])
            return None

        ssid = given("SSID", "ssid")
        if ssid:
            props.append(("802-11-wireless.ssid", ssid))
            applied["ssid"] = ssid

        psk = given("psk")
        if psk is None and given("Password"):
            psk = _decode_ui_password(given("Password"))
        auth = given("AuthMode", "auth")
        if auth == "OPEN":
            props.append(("802-11-wireless-security.key-mgmt", "none"))
        elif auth:
            props.append(("802-11-wireless-security.key-mgmt",
                          "sae" if auth == "WPA3-PSK" else "wpa-psk"))
        if auth:
            applied["auth"] = auth
        if psk and auth != "OPEN":
            if not 8 <= len(psk) <= 63:
                raise ControlError("WPA 密码长度须为 8-63 个字符")
            props.append(("802-11-wireless-security.psk", psk))
            applied["psk"] = "***"

        channel = given("channel")
        hw_mode = given("hw_mode")
        if channel or hw_mode:
            if channel:
                band = "bg" if int(channel) <= 14 else "a"
            else:
                band = "bg" if hw_mode in ("g", "b") else "a"
                channel = "6" if band == "bg" else "149"
            # 80 MHz on 5 GHz (149 needs the patched network-manager, which the
            # image carries -- docs/FINDINGS.md 35.2)
            width = "20" if band == "bg" else "80"
            props += [("802-11-wireless.band", band), ("802-11-wireless.channel", channel),
                      ("802-11-wireless.channel-width", width)]
            applied.update({"band": band, "channel": channel, "channel_width": width})

        hidden = None
        if "ApBroadcastDisabled" in updates:
            # main.js: the "broadcast SSID" box checked sends 0
            hidden = str(updates["ApBroadcastDisabled"]) != "0"
        if "hidden" in updates:
            hidden = bool(updates["hidden"])
        if hidden is not None:
            props.append(("802-11-wireless.hidden", "yes" if hidden else "no"))
            applied["hidden"] = hidden

        if not props:
            return {"applied": {}, "connection": self._hotspot_name(), "restarted": False}
        name = shlex.quote(self._hotspot_name())
        args = " ".join("%s %s" % (key, shlex.quote(value)) for key, value in props)
        result = self._nmcli("connection modify %s %s" % (name, args))
        if not result.done:
            raise ControlError("NetworkManager 拒绝了这些设置：%s" % result.content.strip())
        restarted = False
        if self.hotspot_active():
            restarted = self.set_hotspot(True).done
        return {"applied": applied, "connection": self._hotspot_name(), "restarted": restarted}

    # -- clients -----------------------------------------------------------
    def clients(self) -> List[Dict[str, str]]:
        """Wireless clients, merged from station dump, ARP and DHCP leases."""
        interface = str(self.config.get("wlan_interface") or "wlan0")
        by_mac: Dict[str, Dict[str, str]] = {}

        stations = run_shell("iw dev %s station dump" % interface, timeout=5.0).content
        for mac in _STATION_MAC_RE.findall(stations or ""):
            by_mac[mac.lower()] = {"mac_addr": mac.lower(), "ip_addr": "", "hostname": "",
                                   "type": "wireless"}

        # `ip neigh` prints "<ip> dev <if> lladdr <mac> <state>".  The AP is a
        # port of the LAN bridge, so its clients' addresses are on the bridge.
        lan = str(self.config.get("lan_interface") or "br0")
        arp = run_shell("ip -4 neigh show dev %s" % lan, timeout=5.0).content
        for line in (arp or "").splitlines():
            fields = line.split()
            if len(fields) < 4 or "lladdr" not in fields:
                continue
            address = fields[0]
            mac = fields[fields.index("lladdr") + 1] if fields.index("lladdr") + 1 < len(fields) else ""
            if mac.count(":") != 5:
                continue
            entry = by_mac.get(mac.lower())
            if entry is not None:
                entry["ip_addr"] = address

        # leases cover the USB port too: only the associated stations are Wi-Fi clients
        for mac, address, hostname in self._leases():
            entry = by_mac.get(mac.lower())
            if entry is None:
                continue
            if address:
                entry["ip_addr"] = address
            if hostname:
                entry["hostname"] = hostname
        for entry in by_mac.values():
            if not entry["hostname"]:
                entry["hostname"] = entry["mac_addr"]
        return sorted(by_mac.values(), key=lambda item: item.get("ip_addr") or "")

    def _leases(self) -> List[tuple]:
        """dnsmasq leases: ``<expiry> <mac> <ip> <hostname> <client-id>``."""
        for path in ("/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases",
                     "/run/dnsmasq.leases"):
            text = read_text(path)
            if not text:
                continue
            out = []
            for line in text.splitlines():
                fields = line.split()
                if len(fields) >= 4:
                    out.append((fields[1], fields[2], "" if fields[3] == "*" else fields[3]))
            return out
        return []

    def set_client_access(self, mode: str, macs: List[str]) -> Dict[str, Any]:
        """Allow/deny list for the hotspot, as an nftables bridge filter.

        NetworkManager's AP mode has no MAC list, so a station still associates,
        but nothing it sends gets past the bridge.  The ruleset is kept in the
        data directory and loaded again by ``apply_client_access`` at start-up.
        """
        interface = str(self.config.get("wlan_interface") or "wlan0")
        macs = [m.lower() for m in macs if re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", m)]
        lines = ["table bridge %s" % ACL_TABLE, "delete table bridge %s" % ACL_TABLE]
        if macs:
            match = "!=" if mode == "allow" else "=="
            lines += [
                "table bridge %s {" % ACL_TABLE,
                "  chain filter {",
                "    type filter hook prerouting priority -200; policy accept;",
                "    iifname \"%s\" ether saddr %s { %s } drop" % (
                    interface, match, ", ".join(macs)),
                "  }",
                "}",
            ]
        path = os.path.join(self.config.data_dir, "hotspot-acl.nft")
        write_text(path, "\n".join(lines) + "\n")
        result = run_shell("nft -f %s" % shlex.quote(path), timeout=10.0)
        if not result.done:
            raise ControlError("nftables 拒绝了访问控制规则：%s" % result.content.strip())
        return {"mode": mode, "count": len(macs), "ruleset": path}

    def apply_client_access(self) -> None:
        """Load the saved allow/deny list (called once at start-up)."""
        path = os.path.join(self.config.data_dir, "hotspot-acl.nft")
        if os.path.isfile(path):
            run_shell("nft -f %s" % shlex.quote(path), timeout=10.0)

    # -- LAN (read-only) ---------------------------------------------------
    def lan_status(self) -> Dict[str, Any]:
        interface = str(self.config.get("lan_interface") or "br0")
        info = iface_ipv4(interface)
        mac = read_text("/sys/class/net/%s/address" % interface)
        conf = read_text(str(self.config.get("dnsmasq_conf") or "")) or ""
        start, end = "", ""
        # dnsmasq: dhcp-range=[set:<tag>,|tag:<tag>,]<start>,<end>[,...]
        match = re.search(r"dhcp-range=(?:(?:set|tag):[^,\s]+,)*([0-9.]+),([0-9.]+)", conf)
        if match:
            start, end = match.group(1), match.group(2)
        else:
            start, end = info.get("dhcpStart", ""), info.get("dhcpEnd", "")
        return {
            "lan_ipaddr": info.get("lan_ipaddr", ""),
            "lan_netmask": info.get("lan_netmask", ""),
            "dhcpStart": start,
            "dhcpEnd": end,
            "dhcpEnabled": bool(start),
            "mac_address": (mac or "").strip(),
        }

    # -- performance -------------------------------------------------------
    def _governor_paths(self) -> List[str]:
        base = "/sys/devices/system/cpu/cpufreq"
        try:
            return sorted(
                os.path.join(base, entry, "scaling_governor")
                for entry in os.listdir(base)
                if entry.startswith("policy")
            )
        except OSError:
            return []

    def performance_status(self) -> Dict[str, Any]:
        paths = self._governor_paths()
        governors = []
        for path in paths:
            value = (read_text(path) or "").strip()
            if value:
                governors.append(value)
        current = governors[0] if governors else ""
        available = []
        if paths:
            candidates = read_text(os.path.join(os.path.dirname(paths[0]), "scaling_available_governors"))
            available = (candidates or "").split()
        return {
            "governors": sorted(set(governors)),
            "governor": current,
            "available": available,
            "performance": current == "performance",
            "supported": bool(paths),
        }

    def set_performance(self, enabled: bool) -> Dict[str, Any]:
        paths = self._governor_paths()
        if not paths:
            raise ControlError("当前内核没有 cpufreq 调速器")
        target = "performance" if enabled else str(self.config.get("powersave_governor") or "schedutil")
        written = []
        for path in paths:
            try:
                write_text(path, target + "\n")
                written.append(path)
            except OSError:
                continue
        if not written:
            raise ControlError("写入调速器失败（需要 root）")
        return {"governor": target, "interfaces": len(written)}

    # -- indicator LED -----------------------------------------------------
    def _led_paths(self) -> List[str]:
        configured = [name for name in str(self.config.get("led_names") or "").split(",") if name.strip()]
        base = "/sys/class/leds"
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            return []
        if configured:
            entries = [entry for entry in entries if entry in [c.strip() for c in configured]]
        return [os.path.join(base, entry) for entry in entries]

    def led_status(self) -> Dict[str, Any]:
        paths = self._led_paths()
        leds = []
        for path in paths:
            leds.append({
                "name": os.path.basename(path),
                "brightness": (read_text(os.path.join(path, "brightness")) or "").strip(),
                "trigger": (read_text(os.path.join(path, "trigger")) or "").strip().split()[-1:],
            })
        return {"supported": bool(paths), "leds": leds}

    def set_led(self, enabled: bool) -> Dict[str, Any]:
        paths = self._led_paths()
        if not paths:
            raise ControlError("当前设备没有可控指示灯")
        changed = 0
        for path in paths:
            try:
                write_text(os.path.join(path, "trigger"), "default-on\n" if enabled else "none\n")
                write_text(os.path.join(path, "brightness"),
                           ("255" if enabled else "0") + "\n")
                changed += 1
            except OSError:
                continue
        if not changed:
            raise ControlError("写入指示灯失败（需要 root）")
        return {"enabled": enabled, "leds": changed}

    # -- misc --------------------------------------------------------------
    def samba_unit(self) -> str:
        return str(self.config.get("samba_unit") or "")

    def set_samba(self, enabled: bool) -> Dict[str, Any]:
        unit = self.samba_unit()
        if not unit:
            raise ControlError("未配置文件共享服务单元（samba_unit）")
        result = systemctl("start" if enabled else "stop", unit)
        return {"unit": unit, "started": result.done}

    def uptime(self) -> int:
        return self.app.device_info.uptime()

    def ip_to_int(self, address: str) -> int:
        try:
            return struct.unpack("!I", socket.inet_aton(address))[0]
        except OSError:
            return 0

    def which(self, binary: str) -> Optional[str]:
        return shutil.which(binary)

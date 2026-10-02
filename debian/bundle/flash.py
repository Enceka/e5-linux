#!/usr/bin/env python3
"""E5 Debian one-click installer and A/B updater.

The package is deliberately self-contained: ``serve/`` is served over the
USB LAN for the SD installer and for a running Debian system, while the
Android path uses adb and only writes the inactive Debian slot.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


B = Path(__file__).resolve().parent
SERVE = B / "serve"
ADB = os.environ.get("ADB", "adb")
TELNET = B / "e5-telnet.py"
REMOTE = "/data/local/tmp/e5-debian-update"
RAW_SIZE = 4 * 1024 * 1024 * 1024


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package_files() -> list[Path]:
    """Files covered by the package checksum list (excluding the list)."""
    return sorted(p for p in B.rglob("*") if p.is_file() and p.name != "SHA256SUMS")


def check_package() -> None:
    sums = B / "SHA256SUMS"
    if not sums.is_file():
        raise SystemExit("SHA256SUMS is missing")
    checked = set()
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        try:
            want, name = line.split(None, 1)
        except ValueError:
            raise SystemExit(f"invalid checksum line: {line!r}")
        name = name.strip()
        path = (B / name).resolve()
        if B not in path.parents or not path.is_file():
            raise SystemExit(f"checksum file is missing: {name}")
        got = digest(path)
        if got != want:
            raise SystemExit(f"checksum mismatch: {name}\nexpected {want}\nread     {got}")
        checked.add(path)
    expected = {p.resolve() for p in package_files()}
    if checked != expected:
        missing = sorted(str(p.relative_to(B)) for p in expected - checked)
        extra = sorted(str(p.relative_to(B)) for p in checked - expected)
        raise SystemExit(f"SHA256SUMS coverage mismatch; missing={missing}, extra={extra}")
    manifest = B / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        for name, want in data.get("files", {}).items():
            path = B / name
            if not path.is_file() or digest(path) != want:
                raise SystemExit(f"manifest mismatch: {name}")
    raw = SERVE / "rootfs.raw.sha256"
    if len(raw.read_text().strip()) != 64:
        raise SystemExit("invalid rootfs.raw.sha256")
    print("PACKAGE-CHECK-OK")


def adb_run(*args: str, check: bool = True, capture: bool = True) -> str:
    p = subprocess.run([ADB, *args], text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None)
    out = p.stdout or ""
    if check and p.returncode:
        raise SystemExit(f"adb {' '.join(args[:2])} failed (exit {p.returncode})\n{out[-2000:]}")
    return out


def su(cmd: str, check: bool = True) -> str:
    return adb_run("shell", "su", "-c", cmd, check=check)


def start_server() -> tuple[http.server.ThreadingHTTPServer, str]:
    bind = os.environ.get("E5_LOCAL", "192.168.9.2")
    advertise = os.environ.get("E5_ADVERTISE_HOST", bind)
    port = int(os.environ.get("E5_HTTP_PORT", "8788"))
    old = os.getcwd()
    os.chdir(SERVE)
    try:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(SERVE))
        server = http.server.ThreadingHTTPServer((bind, port), handler)
    except Exception:
        os.chdir(old)
        raise
    os.chdir(old)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{advertise}:{port}"


def remote(command: str, *, wait: float = 90.0, must_succeed: bool = True) -> str:
    """Run one command through the existing telnet login without phone actions."""
    marker = "__E5_FLASH_OK__"
    wrapped = f"set -e; {command}; echo {marker}"
    env = os.environ.copy()
    env.setdefault("E5_TELNET_HOST", os.environ.get("E5_HOST", "192.168.9.1"))
    env.setdefault("E5_TELNET_WAIT", str(max(60, int(wait))))
    p = subprocess.run([sys.executable, str(TELNET), wrapped], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=env, timeout=wait)
    print(p.stdout, end="")
    if p.returncode or (must_succeed and marker not in p.stdout):
        raise SystemExit(f"device command failed (exit {p.returncode}); preserve the output above")
    return p.stdout


def sd_install() -> None:
    check_package()
    server, base = start_server()
    raw = (SERVE / "rootfs.raw.sha256").read_text().strip()
    release = (B / "kernel.release").read_text().strip()
    try:
        print("== switching to the existing OpenWrt slot; no phone call is made")
        remote("e5-os openwrt --once; sync; (sleep 2; reboot) >/dev/null 2>&1 &",
               wait=30, must_succeed=False)
        delay = int(os.environ.get("E5_BOOT_WAIT", "35"))
        print(f"== waiting {delay}s for OpenWrt")
        time.sleep(delay)
        print("== installing Debian A/B roots; capacity is checked before writes")
        remote(f"wget -q -O /tmp/device-install-sd.sh {base}/device-install-sd.sh; "
               f"chmod 755 /tmp/device-install-sd.sh; "
               f"/tmp/device-install-sd.sh {base} {raw} {release}", wait=900)
        boot = base + "/boot.img"
        misc = base + "/boot.misc-slot-b-trial.bin"
        print("== flashing the shared boot image and arming a Linux trial")
        remote(f"wget -q -O /tmp/e5-boot.img {boot}; "
               f"wget -q -O /tmp/e5-misc.bin {misc}; "
               "dd if=/tmp/e5-boot.img of=/dev/block/by-name/boot_b bs=4M conv=fsync; "
               "dd if=/tmp/e5-misc.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc; "
               "sync; sha256sum /dev/block/by-name/boot_b /tmp/e5-boot.img", wait=300)
        print("== Debian SD installation is armed; reboot is left to the operator")
    finally:
        server.shutdown()
        server.server_close()


def debian_update() -> None:
    check_package()
    server, base = start_server()
    raw = (SERVE / "rootfs.raw.sha256").read_text().strip()
    release = (B / "kernel.release").read_text().strip()
    boot_sha = digest(SERVE / "boot.img")
    try:
        cmd = (f"/usr/local/sbin/e5-debian-update {base} {raw} {RAW_SIZE} {release} "
               f"{boot_sha} {base}/boot.img {base}/boot.misc-slot-b-trial.bin")
        print("== updating the inactive Debian A/B slot; reboot is left to the operator")
        remote(cmd, wait=1200)
    finally:
        server.shutdown()
        server.server_close()


def push_chunks(src: Path, remote_path: str) -> None:
    su(f"rm -f {remote_path}")
    part_size = 16 << 20
    with tempfile.TemporaryDirectory() as td, src.open("rb") as f:
        n = 0
        while True:
            data = f.read(part_size)
            if not data:
                break
            part = Path(td) / f"part{n:04d}"
            part.write_bytes(data)
            adb_run("push", str(part), f"{REMOTE}/part")
            su(f"stat -c %s {REMOTE}/part")
            su(f"cat {REMOTE}/part >> {remote_path}; rm -f {REMOTE}/part")
            n += 1
            print(f"  pushed {f.tell() / 1048576:.0f} MiB", flush=True)
    if su(f"sha256sum {remote_path}").split()[0] != digest(src):
        raise SystemExit(f"{src.name} arrived damaged on Android")


def android_update() -> None:
    check_package()
    devices = [l for l in adb_run("devices").splitlines()[1:] if l.endswith("\tdevice")]
    if len(devices) != 1:
        raise SystemExit(f"need exactly one adb device (found {len(devices)})")
    if "uid=0" not in su("id"):
        raise SystemExit("adb shell has no root; grant Shell root access")
    if su("getprop ro.boot.slot_suffix").strip() != "_a":
        raise SystemExit("Android must run slot_a")
    su(f"rm -rf {REMOTE}; mkdir -p {REMOTE}")
    rootfs = SERVE / "rootfs.ext4.gz"
    push_chunks(rootfs, REMOTE + "/rootfs.gz")
    for name, remote_name in (("boot.img", "boot.img"),
                              ("boot.misc-slot-b-trial.bin", "misc.bin")):
        adb_run("push", str(SERVE / name), f"{REMOTE}/{remote_name}")
    adb_run("push", str(B / "android-update-device.sh"), REMOTE + "/update.sh")
    boot_sha = digest(SERVE / "boot.img")
    su(f"printf '%s  %s\\n' {boot_sha} {REMOTE}/boot.img > {REMOTE}/boot.img.sha256; "
       f"chmod 755 {REMOTE}/update.sh")
    raw = (SERVE / "rootfs.raw.sha256").read_text().strip()
    release = (B / "kernel.release").read_text().strip()
    su(f"sh {REMOTE}/update.sh {REMOTE}/rootfs.gz {REMOTE}/boot.img {REMOTE}/misc.bin "
       f"{raw} {RAW_SIZE} {release}")
    print("ANDROID-DEBIAN-UPDATE-READY; reboot is left to the operator")


def main() -> None:
    ap = argparse.ArgumentParser(description="E5 Debian one-click SD installer and A/B updater")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify package only")
    group.add_argument("--sd", action="store_true", help="install Debian A/B on the SD card")
    group.add_argument("--update", action="store_true", help="update inactive Debian from running Debian")
    group.add_argument("--android-update", action="store_true", help="update inactive Debian through rooted adb")
    args = ap.parse_args()
    if args.check:
        check_package()
    elif args.update:
        debian_update()
    elif args.android_update:
        android_update()
    else:
        sd_install()


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as e:
        raise SystemExit(f"command timed out after {e.timeout}s")

"""UFI-TOOLS for Linux.

This package is the Linux port of UFI-TOOLS' device-side backend.  The Android
app in ``app/`` is a Ktor server that exposes the *host* device's capabilities
as a web API plus a static SPA; this package keeps the same HTTP contract (auth
scheme, endpoint paths, JSON shapes) so the very same web frontend works, but
replaces every Android facility with a Linux one:

===============  ==================================  ==========================
Android          Linux (this package)                module
===============  ==================================  ==========================
``sendat``       ``/opt/e5/e5-at`` (a shim onto unisoc-cpd)  :mod:`ufitools.at`
``Build.MODEL``  ``/proc``, ``/sys``, DMI             :mod:`ufitools.sysinfo`
``Runtime.exec`` ``/bin/sh -c``                       :mod:`ufitools.shell`
``LocalSocket``  Unix domain socket / plain shell     :mod:`ufitools.shell`
SharedPreferences  JSON file under the data dir       :mod:`ufitools.config`
foreground Service  systemd unit                      ``systemd/``
===============  ==================================  ==========================

The module is deliberately stdlib-only: a Linux handset like the Rongyue E5
running E5-LINUX (Debian + systemd) has python3 in the base image, and a
service that needs no wheels is a service that cannot be broken by an apt
upgrade in the field.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_VER", "APP_VER_CODE"]

# Reported to the web frontend through /api/version_info and
# /api/baseDeviceInfo.  Kept identical to the Android app's versionName so the
# frontend's own version handling stays untouched; the Linux port adds a local
# suffix so operators can tell the two backends apart.
APP_VER = "4.1.5"
LINUX_SUFFIX = "linux"
__version__ = "%s+%s" % (APP_VER, LINUX_SUFFIX)

# Frozen at build time like Android's versionCode (yyyyMMdd).  Overridden by
# ``UFI_TOOLS_VER_CODE`` so a distro build can stamp its own date.
import os as _os

APP_VER_CODE = int(_os.environ.get("UFI_TOOLS_VER_CODE", "20260919"))

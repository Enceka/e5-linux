"""HTTP endpoint modules.

Each module exposes ``register(router, app)`` and owns the same paths the
Android app served, so the web frontend in ``linux/www`` needs no changes.
The split mirrors the Kotlin ``modules/`` package one-for-one.

Two of them are Linux-only and are where the actual device control lives:

* :mod:`ufitools.api.control_api` -- the native surface (power, cellular data,
  hotspot, clients, LAN, performance, LED) that the built-in UI console uses;
* :mod:`ufitools.api.ui_compat` -- a read/action translation layer so the stock
  frontend, which speaks the vendor's field vocabulary, can drive those same
  native facilities.
"""

from __future__ import annotations

from . import at_api, base, config_api, control_api, media_api, misc_api, proxy_api, shell_api, task_api
from . import ui_compat

MODULES = (
    base,
    config_api,
    at_api,
    shell_api,
    proxy_api,
    control_api,
    media_api,
    task_api,
    misc_api,
    ui_compat,
)


def register_all(router, app) -> None:
    for module in MODULES:
        module.register(router, app)

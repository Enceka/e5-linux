#!/usr/bin/env python3
"""Respect wired charger property contracts; do not emulate unsupported setters."""
from pathlib import Path


def apply(kernel):
    path = Path(kernel)/'drivers/power/supply/charger-manager.c'
    source = path.read_text()
    marker = 'Only chargers declaring PRESENT writable consume this notification.'
    if marker not in source:
        start = source.index('static void cm_set_charger_present(')
        end = source.index('\n}', start)
        body = source[start:end]
        anchor = '\t\tval.intval = present;'
        if body.count(anchor) != 1:
            raise ValueError('Unknown charger PRESENT notification path')
        body = body.replace(anchor, '''\t\t/* Only chargers declaring PRESENT writable consume this notification.
\t\t * AW32257 has no setter; BQ2560x explicitly advertises one. */
\t\tif (!psy->desc->property_is_writeable ||
\t\t    !psy->desc->property_is_writeable(psy, POWER_SUPPLY_PROP_PRESENT)) {
\t\t\tpower_supply_put(psy);
\t\t\tcontinue;
\t\t}

''' + anchor)
        source = source[:start]+body+source[end:]
    marker = 'A wired-only board has no wireless type to clear.'
    if marker not in source:
        start = source.index('static void try_wireless_charger_enable(')
        anchor = '\tret = cm_set_primary_charge_wirless_type(cm, enable);'
        at = source.index(anchor, start)
        source = source[:at]+'''\t/* A wired-only board has no wireless type to clear. */
\tif (!cm->desc->psy_wl_charger_stat || !cm->desc->psy_wl_charger_stat[0])
\t\treturn;

'''+source[at:]
    path.write_text(source)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])

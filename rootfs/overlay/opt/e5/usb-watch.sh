#!/bin/sh
# The USB gadget back on the host after a replug, or when the host never
# recognised it (docs/STATUS.md, FINDINGS 26/28).  A cable's extcon event can
# leave the gadget disconnected (soft_connect 0, the UDC "not attached"), and a
# gadget that is attached but that the host never enumerated looks the same from
# the device side -- the board has its network and serial console wired to this
# same gadget, so both mean "connected to a computer, but not recognised".
#
# While a cable is in (an extcon reports USB=1) from a computer's port (the
# charger sees SDP or CDP, not a wall charger's DCP) the gadget is driven back:
#
#   * the UDC "not attached": connect it again (soft_connect);
#   * the UDC attached but not "configured" for a few polls: a soft replug --
#     disconnect, then connect -- so the host enumerates it afresh.
#
# soft_connect only moves the pull-up; the usb0 netdev stays up, which the NCM
# function needs ("usb0 must never go down", docs/FINDINGS.md 28).  At most a
# few attempts per plug, so a genuinely broken host port is not hammered.  Run
# by procd (OpenWrt, /etc/init.d/e5-usb-watch) and by e5-usb-watch.service
# (Debian); /usr/libexec/e5-usb-watch on OpenWrt execs this.
set -u

# the board has one USB device controller; it is up before the gadget is bound,
# but wait for it rather than exiting into a restart loop at boot
n=0
while [ -z "$(ls /sys/class/udc 2>/dev/null)" ]; do
	n=$((n + 1))
	[ "$n" -gt 60 ] && { logger -t e5-usb-watch "no USB device controller"; exit 0; }
	sleep 1
done
UDC=/sys/class/udc/$(ls /sys/class/udc | head -1)
log() { logger -t e5-usb-watch "$*"; }

vbus() {
	for e in /sys/class/extcon/*/state; do
		grep -qx 'USB=1' "$e" 2>/dev/null && return 0
	done
	return 1
}
# the charger's port type, bracketed in usb_type: [SDP] or [CDP] is a host
host_port() {
	for p in /sys/class/power_supply/*/usb_type; do
		[ "$(cat "${p%/usb_type}/online" 2>/dev/null)" = 1 ] || continue
		grep -qE '\[(SDP|CDP)\]' "$p" 2>/dev/null && return 0
	done
	return 1
}
state() { cat "$UDC/state" 2>/dev/null; }

missed=0 attempts=0
while :; do
	if vbus && host_port; then
		st=$(state)
		if [ "$st" = configured ]; then
			missed=0 attempts=0
		else
			missed=$((missed + 1))
			# ~6 s for a host that is going to enumerate on its own, then up to
			# 5 tries per plug
			if [ "$missed" -ge 3 ] && [ "$attempts" -lt 5 ]; then
				missed=0 attempts=$((attempts + 1))
				if [ "$st" = "not attached" ]; then
					echo connect > "$UDC/soft_connect" 2>/dev/null
					log "cable in, the gadget was not attached: connected again"
				else
					# attached, but the host has not enumerated it: a fresh attach
					echo disconnect > "$UDC/soft_connect" 2>/dev/null
					sleep 1
					echo connect > "$UDC/soft_connect" 2>/dev/null
					log "cable in, the gadget stuck at ${st:-?}: reconnected"
				fi
				sleep 8
			fi
		fi
	else
		missed=0 attempts=0
	fi
	sleep 2
done

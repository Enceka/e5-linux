# SC2355 firmware owns SAE authentication; hostapd owns the four-way handshake.
# Called inside hostapd_set_bss_options(), before encryption defaults are set.
unisoc_sae_bss_options() {
	case "$auth_type" in
		sae|psk-sae) ;;
		*) return 0 ;;
	esac
	# PMF=0 from an earlier WPA2 profile is invalid for SAE. Normalize the
	# generated configuration without rewriting the user's unrelated UCI.
	case "$auth_type:$ieee80211w" in
		sae:0|sae:1) ieee80211w=2 ;;
		psk-sae:0) ieee80211w=1 ;;
	esac
	local module
	module=$(readlink -f "/sys/class/ieee80211/$phy/device/driver/module" 2>/dev/null || true)
	case "$module" in
		*/sprd_wlan_combo) ;;
		*) return 0 ;;
	esac
	append bss_conf 'unisoc_sae=1' "$N"
	# This BSP password-entry ABI has no negotiated H2E mechanism. Leave
	# explicit settings intact; the driver rejects unsupported H2E clearly.
	set_default sae_pwe 0
	# The firmware association event cannot carry RSN Selection to hostapd.
	rsn_override=0
}

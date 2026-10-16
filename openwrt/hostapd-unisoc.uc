// Firmware-SME configuration shared by the OpenWrt ucode AP generator.
export function configure(config, module) {
	if (!(config.auth_type in [ 'sae', 'psk-sae' ]))
		return;
	if (config.auth_type == 'sae')
		config.ieee80211w = 2;
	else if (!config.ieee80211w)
		config.ieee80211w = 1;
	if (module != '/sys/module/sprd_wlan_combo')
		return;
	config.unisoc_sae = 1;
	config.sae_pwe ??= 0;
	// This legacy SME does not report the RSN Selection extension in its
	// association event. Advertising RSN Override then breaks message 2/4.
	config.rsn_override = 0;
	config.rsn_override_pairwise = null;
	config.rsn_override_key_mgmt = null;
	config.rsn_override_mfp = null;
};

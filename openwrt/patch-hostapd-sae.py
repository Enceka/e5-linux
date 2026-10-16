#!/usr/bin/env python3
"""Idempotent patches for the pinned OpenWrt 25.12 hostapd and wifi-scripts."""
from pathlib import Path
import argparse


def replace(path, old, new):
    text = path.read_text(encoding='utf-8')
    if new in text:
        return
    if text.count(old) != 1:
        raise ValueError('Unexpected hostapd source: ' + str(path) + ': ' + old[:65])
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def patch_source(root):
    root = Path(root)
    replace(root / 'src/ap/ap_config.h', '\tint sae_require_mfp;\n',
            '\tint sae_require_mfp;\n\tint unisoc_sae; /* trusted firmware PMK indication */\n')
    replace(root / 'hostapd/config_file.c',
            '\t} else if (os_strcmp(buf, "sae_require_mfp") == 0) {',
            '\t} else if (os_strcmp(buf, "unisoc_sae") == 0) {\n'
            '\t\tif (os_strcmp(pos, "0") && os_strcmp(pos, "1"))\n'
            '\t\t\treturn 1;\n\t\tbss->unisoc_sae = atoi(pos);\n'
            '\t} else if (os_strcmp(buf, "sae_require_mfp") == 0) {')
    path = root / 'src/ap/drv_callbacks.c'
    replace(path, '#include "nan_usd_ap.h"\n',
            '#include "nan_usd_ap.h"\n#include "unisoc_sae.h"\n')
    replace(path, '\t\twpa_auth_set_rsn_selection(sta->wpa_sm, elems.rsn_selection,',
            '''#ifdef CONFIG_SAE
		if (unisoc_sae_import(hapd, sta, req_ies, req_ies_len) < 0) {
			wpa_printf(MSG_INFO, "Unisoc SAE: missing or invalid firmware key indication");
			reason = WLAN_REASON_UNSPECIFIED;
			goto fail;
		}
#endif
		wpa_auth_set_rsn_selection(sta->wpa_sm, elems.rsn_selection,''')
    path = root / 'src/drivers/driver_nl80211_event.c'
    replace(path, 'wpa_hexdump(MSG_DEBUG, "nl80211: Assoc Req IEs",',
            'wpa_hexdump_key(MSG_DEBUG, "nl80211: Assoc Req IEs",')
    (root / 'src/ap/unisoc_sae.h').write_bytes(
        Path(__file__).with_name('hostapd-unisoc-sae.h').read_bytes())
    replace(root / 'src/ap/beacon.c',
            '\t/* If SAE offload is enabled, provide password to lower layer for',
            '''	/* This BSP ABI has no H2E/group negotiation fields. Fail clearly
	 * rather than advertise mechanisms the firmware cannot be configured for.
	 */
	if (hapd->conf->unisoc_sae &&
	    (hapd->conf->wpa_key_mgmt & WPA_KEY_MGMT_SAE) &&
	    (!(hapd->iface->drv_flags2 & WPA_DRIVER_FLAGS2_SAE_OFFLOAD_AP) ||
	     (hapd->conf->sae_pwe != SAE_PWE_HUNT_AND_PECK &&
	      hapd->conf->sae_pwe != SAE_PWE_FORCE_HUNT_AND_PECK) ||
	     (hapd->conf->sae_groups &&
	      (hapd->conf->sae_groups[0] != 19 || hapd->conf->sae_groups[1])))) {
		wpa_printf(MSG_ERROR, "Unisoc SAE: requires firmware offload, hunting-and-pecking and group 19");
		return -1;
	}
	/* If SAE offload is enabled, provide password to lower layer for''')


def patch_wifi(root):
    root = Path(root)
    path = root / 'lib/netifd/hostapd.sh'
    replace(path, 'hostapd_set_bss_options() {',
            '. /lib/netifd/hostapd-unisoc.sh\n\nhostapd_set_bss_options() {')
    replace(path, '\t[ -n "$spp_amsdu" ] && append bss_conf "spp_amsdu=$spp_amsdu" "$N"\n',
            '\t[ -n "$spp_amsdu" ] && append bss_conf "spp_amsdu=$spp_amsdu" "$N"\n'
            '\n\tunisoc_sae_bss_options\n')
    (root / 'lib/netifd/hostapd-unisoc.sh').write_bytes(
        Path(__file__).with_name('hostapd-unisoc.sh').read_bytes())
    # OpenWrt 25.12 normally uses the ucode generator; the shell path above
    # remains available to builds that deliberately select legacy scripts.
    ucode = root.parent / 'files-ucode/usr/share/ucode/wifi'
    path = ucode / 'ap.uc'
    replace(path, "import * as iface from 'wifi.iface';\n",
            "import * as iface from 'wifi.iface';\n"
            "import { configure as unisoc_sae_config } from 'wifi.unisoc-sae';\n")
    replace(path, '\tiface_auth_type(config);',
            "\tunisoc_sae_config(config, fs.realpath(`/sys/class/ieee80211/${data.phy}/device/driver/module`));\n"
            "\tif (config.unisoc_sae)\n\t\tappend('unisoc_sae', config.unisoc_sae);\n"
            '\tiface_auth_type(config);')
    (ucode / 'unisoc-sae.uc').write_bytes(
        Path(__file__).with_name('hostapd-unisoc.uc').read_bytes())


def patch_reload(root):
    root = Path(root)
    # SET_BEACON has no crypto-settings callback in cfg80211. In-place BSS
    # reloads cannot update the firmware password; restart only when an SAE
    # BSS configuration actually changes, not on each ordinary reload.
    replace(root / 'hostapd.uc',
            '\tif (is_equal(old_config.bss, config.bss))\n\t\treturn true;\n',
            '''\tif (is_equal(old_config.bss, config.bss))
		return true;

	/* A changed firmware-SAE BSS needs START_AP with its new password. */
	for (let cfg in [ old_config, config ])
		for (let bss in cfg.bss ?? [])
			for (let line in bss.data ?? [])
				if (line == 'unisoc_sae=1')
					return false;
''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['source', 'wifi', 'reload'])
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    {'source': patch_source, 'wifi': patch_wifi, 'reload': patch_reload}[args.kind](args.root)

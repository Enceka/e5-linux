/* SPDX-License-Identifier: BSD-3-Clause */
/* Recovered from the Unisoc Android hostapd (E5), not an on-air extension.
 * The firmware appends dd 34 40 45 da 04 <PMK:32> <PMKID:16> to NEW_STATION.
 * Only consume it on explicitly opted-in firmware-SME interfaces. WPA2 and
 * other drivers must never accept a peer-supplied IE as an authentication key.
 */
#ifdef CONFIG_SAE
#include "pmksa_cache_auth.h"

static int unisoc_sae_import(struct hostapd_data *hapd, struct sta_info *sta,
			     const u8 *ies, size_t ies_len)
{
	const u8 *rsn, *key_ie, *pmk = NULL, *pmkid = NULL;
	struct wpa_ie_data parsed;
	struct rsn_pmksa_cache_entry *entry;
	struct sae_data *sae;
	int i;

	if (!hapd->conf->unisoc_sae ||
	    !(hapd->conf->wpa_key_mgmt & WPA_KEY_MGMT_SAE))
		return 0;
	if (!(hapd->iface->drv_flags2 & WPA_DRIVER_FLAGS2_SAE_OFFLOAD_AP))
		return -1;
	rsn = get_ie(ies, ies_len, WLAN_EID_RSN);
	if (!rsn || wpa_parse_wpa_ie_rsn(rsn, rsn[1] + 2, &parsed))
		return -1;
	if (parsed.key_mgmt != WPA_KEY_MGMT_SAE) {
		/* A peer may reassociate with WPA2 after previously using SAE. */
		if (sta->sae) {
			sae_clear_data(sta->sae);
			bin_clear_free(sta->sae, sizeof(*sta->sae));
			sta->sae = NULL;
		}
		sta->auth_alg = WLAN_AUTH_OPEN;
		wpa_auth_set_auth_alg(sta->wpa_sm, WLAN_AUTH_OPEN);
		return 0;
	}
	if (!(parsed.capabilities & WPA_CAPABILITY_MFPC))
		return -1;

	key_ie = get_vendor_ie(ies, ies_len, 0x4045da04);
	if (key_ie) {
		if (key_ie[1] != 4 + SAE_PMK_LEN + PMKID_LEN)
			return -1;
		if (get_vendor_ie(key_ie + key_ie[1] + 2,
				  ies + ies_len - (key_ie + key_ie[1] + 2),
				  0x4045da04))
			return -1;
		pmk = key_ie + 6;
		pmkid = pmk + SAE_PMK_LEN;
	} else {
		/* A real PMKSA reassociation can omit a fresh firmware key.
		 * Never substitute the ordinary WPA2 PSK or a stale station key.
		 */
		for (i = 0; i < parsed.num_pmkid; i++) {
			entry = wpa_auth_pmksa_get(hapd->wpa_auth, sta->addr,
						 parsed.pmkid + i * PMKID_LEN);
			if (entry && entry->akmp == WPA_KEY_MGMT_SAE &&
			    entry->pmk_len == SAE_PMK_LEN) {
				pmk = entry->pmk;
				pmkid = entry->pmkid;
				break;
			}
		}
		if (!pmk)
			return -1;
	}
	sae = os_zalloc(sizeof(*sae));
	if (!sae)
		return -1;
	os_memcpy(sae->pmk, pmk, SAE_PMK_LEN);
	os_memcpy(sae->pmkid, pmkid, PMKID_LEN);
	sae->pmk_len = SAE_PMK_LEN;
	sae->akmp = WPA_KEY_MGMT_SAE;
	sae->state = SAE_ACCEPTED;
	if (!hapd->conf->disable_pmksa_caching &&
	    wpa_auth_pmksa_add_sae(hapd->wpa_auth, sta->addr, sae->pmk,
				  sae->pmk_len, sae->pmkid, WPA_KEY_MGMT_SAE,
				  false, sta->vlan_id) < 0) {
		bin_clear_free(sae, sizeof(*sae));
		return -1;
	}
	if (sta->sae) {
		sae_clear_data(sta->sae);
		bin_clear_free(sta->sae, sizeof(*sta->sae));
	}
	sta->sae = sae;
	sta->auth_alg = WLAN_AUTH_SAE;
	wpa_auth_set_auth_alg(sta->wpa_sm, WLAN_AUTH_SAE);
	wpa_auth_add_sae_pmkid(sta->wpa_sm, sae->pmkid);
	return 0;
}
#endif

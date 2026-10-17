#!/bin/sh
# Requires real OpenWrt jsonfilter. All WAN/APN/AT replies below are fixtures.
set -eu
lib=${1:?unisoc-modem directory required}
. "$lib/dashboard-network.sh"
eval "$(sed -n '/^qos_fragment() {/,/^}/p' "$lib/cell")"
checks=0
check() { [ "$1" = "$2" ] || { echo "FAIL expected <$1>, got <$2>" >&2; exit 1; }; checks=$((checks+1)); }
uci() { echo wan; }
ubus() { printf '%s\n' "$LATEST"; }
t3() { printf '%s\n' "$STATUS"; }
at() { check AT+CGEQOSRDP=4 "$1" >&2; printf '%s\n' "$REPLY"; }
WAN='{"up":true,"l3_device":"sipa_eth3","uptime":42,"inactive":{"l3_device":"sipa_eth0"}}'
LATEST=$WAN
STATUS='{"ok":1,"apn":"CMIOT5G","source":"sim","data_sim":0}'
REPLY='+CGEQOSRDP: 1,9,0,0,0,0,1,1
+CGEQOSRDP: 4,8,0,0,0,0,524000,62000OK'
check sipa_eth3 "$(dash_data_device "$WAN" sipa_eth0)"
check 4 "$(dash_data_cid sipa_eth3 0)"
check 4 "$(dash_data_cid sipa_eth11 1)"
check CMIOT5G "$(dash_apn /unused 0)"
check '{"qci":8,"dl":524.0,"ul":62.0}' "$(qos_fragment "$(dash_active_qos "$WAN" 0)")"
WAN='{"up":true,"l3_device":"sipa_eth11","uptime":42}'; LATEST=$WAN
check '{"qci":8,"dl":524.0,"ul":62.0}' "$(qos_fragment "$(dash_active_qos "$WAN" 1)")"
LATEST='{"up":true,"l3_device":"sipa_eth11","uptime":1}'
check null "$(qos_fragment "$(dash_active_qos "$WAN" 1 || :)")"
LATEST='{"up":true,"l3_device":"sipa_eth11"}'
check null "$(qos_fragment "$(dash_active_qos "$WAN" 1 || :)")"
LATEST='{"up":true,"l3_device":"sipa_eth11","uptime":44}'
check '{"qci":8,"dl":524.0,"ul":62.0}' "$(qos_fragment "$(dash_active_qos "$WAN" 1)")"
LATEST='{"up":true,"l3_device":"sipa_eth12"}'
check null "$(qos_fragment "$(dash_active_qos "$WAN" 1 || :)")"
at() { echo 'Unexpected AT request' >&2; exit 9; }
check null "$(qos_fragment "$(dash_active_qos '{"up":false,"l3_device":"sipa_eth3"}' 0 || :)")"
check null "$(qos_fragment "$(dash_active_qos '{"up":true}' 0 || :)")"
check null "$(qos_fragment "$(dash_active_qos '{"up":true,"l3_device":"sipa_eth11"}' 0 || :)")"
STATUS='{"ok":0,"error":"apn_identity"}'
check '' "$(dash_apn /unused 0 || :)"
STATUS='{"ok":1,"source":"default","data_sim":0}'
check '' "$(dash_apn /unused 0 || :)"
STATUS='{"ok":1,"apn":null,"source":"default","data_sim":0}'
check '' "$(dash_apn /unused 0 || :)"
STATUS='{"ok":1,"apn":"","source":"default","data_sim":0}'
check '(SIM default)' "$(dash_apn /unused 0)"
check '' "$(dash_apn /unused 1 || :)"
check null "$(qos_fragment '4,invalid,0,0,0,0,1,1')"
check '{"qci":8,"dl":null,"ul":null}' "$(qos_fragment '4,8,0,0,0,0,bad,-1')"
echo "PASS dashboard APN/CID: $checks checks with real jsonfilter and shell/awk"

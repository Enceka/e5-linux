#!/bin/sh
# Read-only dashboard helpers shared by E5 and MU300. netifd owns the data
# interface; APN selection owns per-SIM profiles. Never dial or change UCI here.
dash_json() { jsonfilter -s "$1" -e "$2" 2>/dev/null; }

dash_live_device() {
    local device
    device=$(dash_json "$1" '@.l3_device')
    [ -n "$device" ] || device=$(dash_json "$1" '@.device')
    case "$device" in ''|*[!a-zA-Z0-9_.:-]*|.|..) return 1 ;; esac
    [ "${#device}" -le 15 ] || return 1
    printf '%s\n' "$device"
}

dash_data_device() {
    local snapshot=$1 fallback=${2:-} device
    device=$(dash_live_device "$snapshot")
    [ -n "$device" ] || device=$fallback
    [ -n "$device" ] || device=sipa_eth0
    case "$device" in *[!a-zA-Z0-9_.:-]*|.|..) return 1 ;; esac
    [ "${#device}" -le 15 ] || return 1
    printf '%s\n' "$device"
}

dash_wan_status() {
    local iface
    iface=$(uci -q get unisoc_modem.main.data_interface 2>/dev/null)
    iface=${iface:-wan}
    case "$iface" in *[!a-zA-Z0-9_]*) return 1 ;; esac
    [ "${#iface}" -le 32 ] || return 1
    ubus -t 2 call "network.interface.$iface" status 2>/dev/null
}

dash_data_cid() {
    # SIPA has eight CID ports per card. SIM2's sipa_eth11 is its CID4,
    # not CID12. Unknown names or another SIM's interface are not guessed.
    local device=$1 slot=$2 number
    case "$device" in sipa_eth[0-9]|sipa_eth1[0-5]) ;; *) return 1 ;; esac
    number=${device#sipa_eth}
    case "$slot:$number" in
        0:[0-7]) ;;
        1:[89]|1:1[0-5]) number=$((number-8)) ;;
        *) return 1 ;;
    esac
    printf '%d\n' "$((number+1))"
}

dash_apn() {
    # status returns only public selection fields, without credentials,
    # capability scans, connection changes, or synchronous modem AT requests.
    local helper=$1 slot=${2:-} state apn source
    state=$(t3 "$helper" status) || return 1
    [ "$(dash_json "$state" '@.ok')" = 1 ] || return 1
    case "$slot" in 0|1) [ "$(dash_json "$state" '@.data_sim')" = "$slot" ] || return 1 ;; esac
    source=$(dash_json "$state" '@.source')
    case "$source" in sim|auto|network|default) ;; *) return 1 ;; esac
    apn=$(dash_json "$state" '@.apn') || return 1
    [ "${#apn}" -le 100 ] || return 1
    case "$apn" in *[!a-zA-Z0-9.-]*) return 1 ;; esac
    [ -n "$apn" ] || apn='(SIM default)'
    printf '%s\n' "$apn"
}

dash_active_qos() {
    local snapshot=$1 slot=$2 device cid reply latest age latest_age
    [ "$(dash_json "$snapshot" '@.up')" = true ] || return 1
    device=$(dash_live_device "$snapshot") || return 1
    cid=$(dash_data_cid "$device" "$slot") || return 1
    age=$(dash_json "$snapshot" '@.uptime')
    case "$age" in ''|*[!0-9]*) return 1 ;; esac
    # at() is the collector's existing serialized, SIM-scoped adapter.
    reply=$(at "AT+CGEQOSRDP=$cid" 2) || return 1
    latest=$(dash_wan_status) || return 1
    [ "$(dash_json "$latest" '@.up')" = true ] || return 1
    [ "$(dash_live_device "$latest")" = "$device" ] || return 1
    # netifd resets uptime on every new connection, including redials that
    # reuse the same SIPA port. Do not publish the previous bearer's QoS.
    latest_age=$(dash_json "$latest" '@.uptime')
    case "$latest_age" in ''|*[!0-9]*) return 1 ;; esac
    [ "$latest_age" -ge "$age" ] || return 1
    printf '%s\n' "$reply" | tr -d '\r' | awk -F',' -v cid="$cid" '
        BEGIN { OFS="," }
        /^\+CGEQOSRDP:/ {
            sub(/^\+CGEQOSRDP:[[:space:]]*/, ""); sub(/OK[[:space:]]*$/, "")
            for(i=1;i<=NF;i++)gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
            if($1 !~ /^[0-9]+$/ || $1+0 != cid+0 || $2 !~ /^[0-9]+$/ || $2+0<1 || $2+0>255)next
            print; exit
        }'
}

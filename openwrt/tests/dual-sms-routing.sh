#!/bin/sh
# Only inside a disposable container: replaces the receive tool and UCI config.
set -eu
[ "${E5_SMS_DISPOSABLE:-}" = 1 ] || { echo 'Run in a disposable OpenWrt container with E5_SMS_DISPOSABLE=1' >&2; exit 2; }
TOOL=${1:?SMS tool path}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export E5_SMS_ROUTING_TEST=$T
mkdir -p /usr/libexec /etc/config
cat > /usr/libexec/e5-sms-receive <<'EOF'
#!/bin/sh
case "$1" in
list) echo '{"dual_sim":true,"slots":{"0":{"ok":true},"1":{"ok":true}},"messages":[{"id":1000000000,"card":0,"sim":"SIM1","number":"10086","text":"card one","state":"received","direction":"in","time":"2026-10-05T20:00:00+08:00"},{"id":1000000001,"card":1,"sim":"SIM2","number":"10010","text":"quoted \"中文\"\n& +","state":"received","direction":"in","time":"2026-10-05T20:01:00+08:00"}]}' ;;
get) echo '{"id":1000000001,"card":1,"sim":"SIM2","number":"10010","text":"quoted \"中文\"\n& +","state":"received","direction":"in","time":"2026-10-05T20:01:00+08:00"}' ;;
*) exit 1 ;;
esac
EOF
cat > "$T/mmcli" <<'EOF'
#!/bin/sh
case " $* " in
*' --messaging-list-sms '*) echo '{"modem.messaging.sms":["/org/freedesktop/ModemManager1/SMS/0","/org/freedesktop/ModemManager1/SMS/7"]}' ;;
*'/SMS/0 '*) echo '{"sms":{"content":{"text":"duplicate incoming"},"properties":{"pdu-type":"deliver","state":"received"}}}' ;;
*'/SMS/7 '*) echo '{"sms":{"content":{"text":"sent fixture"},"properties":{"pdu-type":"submit","state":"sent"}}}' ;;
*' -m any '*) echo '{"modem":{"generic":{"state":"connected"}}}' ;;
*) exit 1 ;;
esac
EOF
cat > "$T/curl" <<'EOF'
#!/bin/sh
for arg in "$@"; do
 case "$arg" in @*) cat "${arg#@}" > "$E5_SMS_ROUTING_TEST/body" ;; https://*) echo "$arg" > "$E5_SMS_ROUTING_TEST/url" ;; esac
done
printf 204
EOF
chmod 755 /usr/libexec/e5-sms-receive "$T/mmcli" "$T/curl"
export PATH="$T:$PATH"
cat > /etc/config/e5-notify <<'EOF'
config forward 'forward'
 option mode 'shared'
 option enabled '1'
 option url 'https://shared.invalid/{sim}?text={text}'
 option method 'POST'
 option body '{"text":"{text}","sim":"{sim}"}'
 option content_type 'application/json'
config forward 'forward_sim1'
 option enabled '1'
 option url 'https://sim1.invalid/{sim}'
config forward 'forward_sim2'
 option enabled '1'
 option url 'https://sim2.invalid/{sim}?text={text}'
 option method 'POST'
 option body '{"text":"{text}","sim":"{sim}"}'
 option content_type 'application/json'
EOF
ucode "$TOOL" list > "$T/list"
ucode "$TOOL" forward 1000000001 > "$T/result"
ucode - "$T" <<'UC'
let fs=require('fs'),t=ARGV[0];
let list=json(fs.readfile(t+'/list')); assert(length(list.messages)==3,'duplicate MM incoming object');
assert(length(filter(list.messages,m=>m.sim=='SIM2'))==1,'source SIM missing');
let result=json(fs.readfile(t+'/result')); assert(result.ok,'shared forwarding failed');
assert(index(fs.readfile(t+'/url'),'https://shared.invalid/SIM2?')==0,'shared target/origin mismatch');
let body=json(fs.readfile(t+'/body')); assert(body.sim=='SIM2' && body.text=='quoted "中文"\n& +','JSON escaping/origin mismatch');
UC
uci set e5-notify.forward.mode=per_sim
uci commit e5-notify
ucode "$TOOL" forward 1000000001 > "$T/result"
ucode - "$T" <<'UC'
let fs=require('fs'),t=ARGV[0];
assert(json(fs.readfile(t+'/result')).ok,'per-SIM forwarding failed');
assert(index(fs.readfile(t+'/url'),'https://sim2.invalid/SIM2?')==0,'used selected data SIM instead of origin');
assert(index(fs.readfile(t+'/url'),'%E4%B8%AD%E6%96%87')>=0,'UTF-8 URL encoding failed');
UC
uci set e5-notify.forward_sim2.enabled=0
uci commit e5-notify
rm "$T/url"
ucode "$TOOL" forward 1000000001 > "$T/result"
ucode - "$T" <<'UC'
let fs=require('fs'),t=ARGV[0];
assert(json(fs.readfile(t+'/result')).skipped,'disabled SIM profile ignored');
assert(!fs.stat(t+'/url'),'disabled profile sent a request');
print('Dual-SIM listing, origin routing, shared/per-card profiles, escaping and disabled forwarding checks passed\n');
UC

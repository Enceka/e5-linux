#!/bin/sh
# Run on OpenWrt (ucode + fs/uci modules). Never contacts the real modem:
# a private PATH supplies mmcli fixtures to the production SMS command.
set -eu
TOOL=${1:-/usr/libexec/e5-sms}
TEST_DIR=$(mktemp -d)
trap 'rm -r "$TEST_DIR"' EXIT
cat > "$TEST_DIR/mmcli" <<'SH'
#!/bin/sh
case " $* " in
*' --messaging-list-sms '*)
    if [ "${E5_SMS_TEST_EMPTY:-0}" = 1 ]; then
        echo '{"modem.messaging.sms":[]}'
    else
        echo '{"modem.messaging.sms":["/org/freedesktop/ModemManager1/SMS/0","/org/freedesktop/ModemManager1/SMS/7"]}'
    fi ;;
*'/SMS/0 '*)
    echo '{"sms":{"content":{"number":"10086","text":"test \"quoted\"\n测试"},"properties":{"pdu-type":"deliver","state":"received","timestamp":"2026-10-01T12:00:00+08:00"}}}' ;;
*'/SMS/7 '*)
    echo '{"sms":{"content":{"number":"10086","text":"sent fixture"},"properties":{"pdu-type":"submit","state":"sent","timestamp":"2026-10-01T11:00:00+08:00"}}}' ;;
*' -m any '*)
    echo '{"modem":{"generic":{"state":"connected"},"3gpp":{"operator-name":"Example"}}}' ;;
*) exit 1 ;;
esac
SH
chmod 755 "$TEST_DIR/mmcli"
PATH="$TEST_DIR:$PATH" ucode "$TOOL" list > "$TEST_DIR/messages.json"
E5_SMS_TEST_EMPTY=1 PATH="$TEST_DIR:$PATH" ucode "$TOOL" list > "$TEST_DIR/empty.json"
ucode - "$TEST_DIR" <<'UC'
let fs = require('fs');
let full = json(fs.readfile(ARGV[0] + '/messages.json'));
let empty = json(fs.readfile(ARGV[0] + '/empty.json'));
if (full.error || length(full.messages) != 2)
	die('nonempty inbox failed');
if (full.messages[0].id != 0 || full.messages[1].id != 7)
	die('SMS object-path IDs or newest-first ordering failed');
if (full.messages[0].text != 'test "quoted"\n测试' || full.messages[0].direction != 'in' ||
    full.messages[1].direction != 'out')
	die('text or message direction failed');
if (empty.error || length(empty.messages) != 0)
	die('empty inbox failed');
print('SMS listing: full paths, ID zero, UTF-8, quotes/newline, directions, ordering and empty inbox pass\n');
UC

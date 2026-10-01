#!/system/bin/sh
# Read-only stock Android audio reference. Run via adb shell su -c; all calls
# must be placed/ended by the user. Do not read the HAL's audio_pipe_voice.
set -u
BASE=${1:-/data/local/tmp/e5-call-reference}
mkdir -p "$BASE"
MIX=
for f in /vendor/bin/tinymix /system/bin/tinymix /system/xbin/tinymix; do
    [ -x "$f" ] && { MIX=$f; break; }
done
snapshot() {
    tag=$1
    echo "snapshot $tag $(date)" >> "$BASE/events.txt"
    { date; uname -a; cat /proc/asound/cards; cat /proc/asound/pcm; } > "$BASE/$tag-hardware.txt" 2>&1
    if [ -n "$MIX" ]; then "$MIX" -D 0 > "$BASE/$tag-mixer.txt" 2>&1; fi
    dumpsys audio > "$BASE/$tag-audio.txt" 2>&1
    dumpsys media.audio_flinger > "$BASE/$tag-flinger.txt" 2>&1
    dumpsys telephony.registry > "$BASE/$tag-telephony.txt" 2>&1
    {
        for f in /proc/asound/card*/pcm*/sub*/status /proc/asound/card*/pcm*/sub*/hw_params; do
            [ -f "$f" ] && { echo "$f"; cat "$f"; }
        done
    } > "$BASE/$tag-pcm.txt" 2>&1
    {
        find /sys/kernel/debug/asoc -type f -path '*/dapm/*' 2>/dev/null |
        while IFS= read -r f; do echo "$f"; cat "$f"; done
    } > "$BASE/$tag-dapm.txt" 2>&1
    dmesg > "$BASE/$tag-dmesg.txt" 2>&1
}
uname -a > "$BASE/kernel.txt"
getprop ro.build.fingerprint > "$BASE/build.txt"
echo "tinymix=$MIX" > "$BASE/tools.txt"
logcat -v threadtime -T 1 > "$BASE/logcat.txt" 2>&1 &
LOGPID=$!
trap 'kill "$LOGPID" 2>/dev/null || :' EXIT
trap 'exit 0' INT TERM
snapshot idle
echo "READY: manual call only" >> "$BASE/events.txt"
end=$(( $(date +%s) + 1200 ))
active=0
count=0
while [ "$(date +%s)" -lt "$end" ]; do
    # Android MODE_IN_CALL=2. Telephony registry also identifies OFFHOOK=2.
    if dumpsys telephony.registry | grep -q 'mCallState=2'; then
        if [ "$active" = 0 ]; then
            count=$((count + 1))
            active=1
            snapshot "call-$count-early"
            sleep 3
            snapshot "call-$count-active"
            echo "CAPTURED manual call $count" >> "$BASE/events.txt"
        fi
    elif [ "$active" = 1 ]; then
        active=0
        snapshot "call-$count-ended"
        echo "ENDED manual call $count" >> "$BASE/events.txt"
    fi
    sleep 1
done

#!/bin/sh
# M7: where a silent playback stops, on the device (OpenWrt, 5.15 or a mainline trial):
# the card, the PA (aw87xxx over i2c), the DAPM path, the PCM while a tone plays, the kernel's lines.
#
#   tools/e5-telnet.py "sh /tmp/audio-diag.sh > /tmp/audio-diag.txt 2>&1"   (after copying it over)
#
# Plays e5-volume's beep eight times at the volume set now, through hw:<card>,3 (FE_FAST_P, as e5-volume does).
# Reads only, besides the tone, debugfs being mounted, and PulseAudio stopped for the time of the tone
# (it holds the card).  (whole seconds: OpenWrt's busybox sleep takes no fractions)
c=$(sed -n 's/^ *\([0-9]*\) \[sprdphone.*/\1/p' /proc/asound/cards | head -1)
echo "== kernel $(uname -r); card ${c:-none}"
cat /proc/asound/cards; cat /proc/asound/pcm
[ -n "$c" ] || exit 1
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
echo "== aw87xxx"
for d in /sys/bus/i2c/drivers/aw87xxx*/*-*; do
	[ -d "$d" ] || continue
	echo "$d"; for a in profile hwen drv_ver; do echo "  $a: $(cat $d/$a 2>&1 | tr '\n' ' ')"; done
done
ls /lib/firmware/aw87xxx_acf.bin 2>&1
echo "== mixer (non-default looking controls)"
amixer -c "$c" contents 2>/dev/null | awk '/^numid/{n=$0} /: values=/{print n" "$0}' | head -150
echo "== the tone"
f=/usr/share/e5/beep.wav
n0=$(dmesg | wc -l)
pa=; pidof pulseaudio >/dev/null && pa=1 && /etc/init.d/e5-pulseaudio stop && sleep 1
# (the beep, over and over, for 4 s: long enough to look at the stream while it runs)
( i=0; while [ $i -lt 8 ]; do aplay -v -D "hw:$c,3" "$f"; echo "aplay rc=$?"; i=$((i + 1)); done >/tmp/.aplay 2>&1 ) &
sleep 2
echo "-- during: pcm status"
for s in /proc/asound/card$c/pcm*p/sub0; do echo "$s: $(tr '\n' ' ' < $s/status)"; done
sleep 1
for s in /proc/asound/card$c/pcm*p/sub0; do echo "$s: $(tr '\n' ' ' < $s/status)"; done
echo "-- during: DAPM widgets that are on"
for w in /sys/kernel/debug/asoc/*/dapm/* /sys/kernel/debug/asoc/*/*/dapm/*; do
	[ -f "$w" ] || continue
	head -1 "$w" 2>/dev/null | grep -q ": On" && echo "$w: $(head -1 $w)"
done | sed 's|/sys/kernel/debug/asoc/||' | head -80
echo "-- during: aw87xxx"
for d in /sys/bus/i2c/drivers/aw87xxx*/*-*; do [ -d "$d" ] && echo "  profile: $(cat $d/profile 2>&1 | tr '\n' ' ')"; done
echo "-- interrupts (dma, mcdt, vbc, agdsp)"
grep -i -E "dma|mcdt|vbc|agdsp|aud" /proc/interrupts
wait
cat /tmp/.aplay
[ -n "$pa" ] && /etc/init.d/e5-pulseaudio start
echo "== dmesg during the tone"
dmesg | tail -n +$((n0 + 1))
echo "== dmesg of the boot: audio"
logread 2>/dev/null | grep -i -E "aw87|sprd-codec|sprd_codec|vbc|agdsp|audcp|sprd-card|asoc|snd|mcdt|pcm|hook" | tail -120

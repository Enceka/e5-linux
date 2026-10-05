#!/system/bin/sh
MODDIR=${0%/*}
exec /data/adb/magisk/busybox sh "$MODDIR/switch.sh" reboot

#!/bin/sh
# Apply the ownership/mode Android's ueventd.rc gives each device node.
# modem_control drops to uid system (1000) before it opens them, and devtmpfs
# hands everything to Linux as root:root 0660, so without this the modem boot
# fails on the first partition it touches.
RC=/opt/e5/android/vendor/etc/ueventd.rc
[ -r "$RC" ] || exit 0
uid_of() {
  case "$1" in
    root) echo 0;; system) echo 1000;; radio) echo 1001;; bluetooth) echo 1002;;
    graphics) echo 1003;; input) echo 1004;; audio) echo 1005;; camera) echo 1006;;
    log) echo 1007;; wifi) echo 1010;; adb) echo 1011;; install) echo 1012;;
    media) echo 1013;; dhcp) echo 1014;; sdcard_rw) echo 1015;; vpn) echo 1016;;
    gps) echo 1021;; media_rw) echo 1023;; mtp) echo 1024;; shell) echo 2000;;
    *) echo "";;
  esac
}
while read -r path mode user group; do
  case "$path" in /dev/*) ;; *) continue;; esac
  u=$(uid_of "$user"); g=$(uid_of "$group")
  [ -n "$u" ] || continue
  [ -n "$g" ] || g=$u
  for f in $path; do
    [ -e "$f" ] || continue
    chown "$u:$g" "$f" 2>/dev/null
    chmod "$mode" "$f" 2>/dev/null
  done
done < "$RC"
exit 0

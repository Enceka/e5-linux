#!/bin/sh
# Feed cfg80211's pending regulatory.db request (and its signature) while it waits in
# the sysfs firmware fallback, then reload.  Late calls cannot work: the request is
# one-shot at boot, and without it the domain stays world/00 (all channels NO-IR).
for f in regulatory.db regulatory.db.p7s; do
    src=/lib/firmware/$f
    [ -e "$src" ] || continue
    s=/sys/class/firmware/$f
    [ -d "$s" ] || continue
    echo 1 > "$s/loading" && cat "$src" > "$s/data" && echo 0 > "$s/loading" && echo "fed $f"
done
iw reg reload 2>/dev/null || true
sleep 1
iw reg set CN 2>/dev/null || true
iw reg get 2>/dev/null | head -3

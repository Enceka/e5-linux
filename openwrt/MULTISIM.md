# E5 dual-SIM telephony work

2026-10-05: two China Unicom cards are independently detected (operator codes
46001 and 46006). A legacy locally cached ModemManager APK lacked the SIM-slot
implementation even though the image sources contained it. Rebuilding and
updating the daemon exposes two SIM object paths, with slot 1 still selected
for data. `build-rootfs.sh` now requires the APK/source checksum record created
by `build-modemmanager.sh`; an old unverified APK stops packaging. This slot
enumeration fix is separate from the application event transport below.

## Verified dual standby and remaining application work (2026-10-05)

With two China Unicom SIMs and SIM 1 carrying data, manual SMS requests to both
numbers reached their own SIM storage without switching the data SIM or
restarting ModemManager. SIM 2 received the test message at 19:20:38 UTC+8;
SIM 1 received its test message at 19:21:58 UTC+8. These were checked through
per-card storage metadata; message contents and verification codes were not
decoded or recorded. SIM 1 held one message, SIM 2 held four including three
older messages. This verifies the CP's dual-standby SMS reception in this test.

## Application support

The new `sipc_wwan` exposes `/sys/bus/platform/devices/*/sms_events`: a
sequence-numbered snapshot of the latest 64 `+CMTI` storage arrivals, each
with its URC channel hint. `poll(POLLPRI)` wakes `e5-sms-receive`; no secondary
URCs are mixed into ModemManager's primary reply stream. The secondary radio
needs `CNMI=2,1,0,0,0`, configured without changing its RF or data selection.
The E5 CP can route both SIMs' CMTI to the primary URC ring when CNMI is
configured through its command port. An event therefore triggers an immediate
scan of **both** storages; the returned PDU's card-addressed storage establishes
its origin. The snapshot's channel hint is not treated as message provenance.
A bounded scan recovers missed events and supports older kernels.

`e5-sms-receive` reads both SIM storages through `e5-at` and ModemManager,
restores the primary AT context, and stores a private durable inbox in
`/etc/e5-sms`. Existing messages form a silent baseline; new messages alert
once, with multipart completion and stable IDs across reboots. SIM identity
and PDU fingerprints prevent deleting a different message at a reused index.
Updating an OpenWrt image keeps this inbox. The information screen shows the
source card in lists, details and alerts. The user confirmed both cards'
notifications and source labels on 2026-10-05.

LuCI merges/filter both inboxes, replies using the message's origin card, and
supports `shared` or `per_sim` forward profiles. Forward routing uses the
stored message origin, not the selected data SIM; switching profile modes
retains inactive settings. HTTP tests use mocked curl, without external sends.

ModemManager r915 adds the authorized `+E5SMS=<card>,<PDU>` command. It queues
an explicitly card-addressed CMGS and immediately queues the raw PDU after
the prompt, using the same port/queue as upstream SMS sending. `e5-sms-send`
sets the selected card's SMSC, encodes GSM7 or UTF-16 (including multipart),
records sent messages with origin SIM, and restores the primary context.
It never calls SPSWDATA, SetPrimarySimSlot, e5-sim or WAN restart. Partial
submission reports how many parts succeeded and does not retry automatically.
The user confirmed sends from SIM1 and SIM2 with correct originating numbers
on 2026-10-05. The data SIM remained SIM1 and WAN stayed up. Replies to both
cards produced driver events (including SIM2 on the primary URC channel) and
source-labelled notifications. The receiver now resolves either channel hint
against both storages immediately. Unit tests cover both paths without sending
real SMS, plus UTF-16 SMSC replies and the LuCI string-valued card argument.

## Remaining voice integration

The CP starts both SIM radio stacks, but Linux still publishes one AT port
and one ModemManager modem. `e5-sim` remains the explicit **data SIM** switch.
Receiving calls on both numbers and selecting the outgoing call SIM require
retaining the secondary call URCs, identifying each call's card, routing basic
ATD/ATA/ATH and CLCC to that context, and selecting its audio path. The SMS
work does not establish this voice support or two simultaneous active calls.
Keep the existing per-card band restrictions: untested RF settings previously
triggered CP assertions. No calls are placed automatically during testing.

Upstream `SetPrimarySimSlot` selects a primary SIM and may recreate the modem;
its presence alone does not implement per-operation SMS/voice selection:
https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml

Android exposes subscription/slot-specific radio services, rather than asking
the user to restart telephony for each message:
https://android.googlesource.com/platform/frameworks/opt/telephony/+/refs/heads/main/src/java/com/android/internal/telephony/RIL.java

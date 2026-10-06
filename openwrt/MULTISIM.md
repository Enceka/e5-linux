# E5 dual-SIM telephony work

2026-10-05: two China Unicom cards are independently detected (operator codes
46001 and 46006). A legacy locally cached ModemManager APK lacked the SIM-slot
implementation even though the image sources contained it. Rebuilding and
updating the daemon exposes two SIM object paths, with slot 1 still selected
for data. `build-rootfs.sh` now requires the APK/source checksum record created
by `build-modemmanager.sh`; an old unverified APK stops packaging. This slot
enumeration fix is separate from the application event transport below.

## Single-SIM cold boot (2026-10-06)

A fresh install with only physical SIM2 inserted exposed two separate faults:
`e5-sim` used util-linux `flock -w`, which OpenWrt's BusyBox rejects, and the
Unisoc cold power sequence activated the empty SIM1 protocol stack, causing
the CP to assert at `mnphone_api.c:7048`. MM r918 probes both addressed CPIN
contexts and skips power/mode activation only for an explicitly absent SIM.
Unknown/busy replies are not treated as absence. The sequence preserves the
vendor dual-card order and restores the selected card's AT context.

Before WWAN/ModemManager owns the channel, `e5-sim-probe` queries presence
without activating RF or submitting PINs. It waits for both channel opening
and AT readiness: the spipe node can exist while open still returns ENODEV.
An empty preferred slot falls back only to a positively inserted other slot;
two inserted cards retain the user's data-card preference. The selected slot
is persisted and used to load `sipc_wwan`.

Hardware verification started with preference SIM1 and only SIM2 inserted.
After reboot, both configuration/runtime selected card 1 (physical SIM2),
MM exposed primary slot 2, and its power plan was SIM1 absent/SIM2 present.
WAN connected through `sipa_eth8` with the automatic `cbnet` APN; three IPv4
ping replies were received and no new CP assertion was logged. IPv6 WAN also
reached the up state. No call or SMS was initiated during this test.

LuCI previously filtered empty slots, then labelled the remaining array from
one, incorrectly showing the SIM2 object as SIM1. It now preserves physical
slot positions, labels empty slots, reports temporary SIM query failures
separately, and shows the selected data SIM. Tests cover both single slots,
dual/empty slots, locked/busy cards, channel readiness, BusyBox contention,
the production MM power plan and LuCI rendering.

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

## Dual-SIM voice implementation (hardware validation in progress)

ModemManager r917 extends native call creation with `sim-slot=1|2` and exposes
read-only `Call.SimSlot` (0 unknown, 1/2 known). `mmcli -J -o CALL` reports it as
`call.properties.sim-slot`. Applications still use CreateCall, Call.Start,
Call.Accept and Call.Hangup. A call's source slot remains independent of the
selected primary/data SIM; no WAN restart or SPSWDATA is involved.

The Unisoc adapter reads both addressed CLCC lists and gives the combined
snapshot to the existing MM call tracker. Matching includes source slot so
identical phone numbers and native CLCC indices on two cards do not collide.
Inactive created objects and commands waiting in the AT queue are not ended
by an idle snapshot; reused incoming indices create a fresh call identity.
An active card whose query fails is retained rather than reported as empty.
Incoming-call timeout is disabled: explicit modem state establishes its end.

The driver exposes `call_events`, retaining 64 RING/STATE/END/DIAL hints from
both URC channels and the command reply channel, without phone numbers or raw
payloads. poll(POLLPRI) triggers an immediate addressed refresh; a three-second
fallback also discovers calls on older kernels. Channel hints never determine
message/call origin. Generic ambiguous RING/CLIP/NO CARRIER handlers cannot
assign a secondary call to the data card or end an unrelated call.

The phone plugin 1.5 adds a keypad-accessible SIM selector, call-source labels,
source-labelled notifications and a choice between displayed calls. The audio
watcher receives the same source information and restarts the shared hostless
frontend when the active radio changes. Notification polls and audio watchers
never start, answer or end calls.

There is one shared voice frontend. A new dial while another call exists, or
an accept while another call is active, returns a busy error; it never hangs
up the other call automatically. Source-free multiparty/global supplementary
operations are not exposed by this adapter. This implements dual standby and
per-call selection, not two simultaneously active voice calls.

The feature is deployed on kernel `6.18.54-e5-00072-g020b970e351e`, MM r917 and
phone 1.5. The local creation-only test confirms an inactive SIM2 object with
no dial, then removes exactly that object. Unit checks compile the production
matching/routing functions against an in-memory model; UI tests intercept all
call requests. The initial SIM2 dial exposed a stale-snapshot race: CP had an active call
while an older empty snapshot marked its MM object terminated. r917 records
the snapshot acquisition epoch and dial completion epoch; older snapshots
cannot end that call, and an unindexed new dial gets a short state-acquisition
grace period. Replies containing CLCC records that fail decoding are errors,
never empty lists. The user confirmed SIM2 outgoing downlink after this fix;
The user also confirmed the SIM2 incoming alert. Incoming-call answer/audio,
upstream audio and a sustained 30-second test have not been verified; the user
explicitly deferred upstream testing for now.

Keep the existing per-card band restrictions: untested RF settings previously
triggered CP assertions. Actual calls are always operated manually by the user.

Upstream `SetPrimarySimSlot` selects a primary SIM and may recreate the modem;
its presence alone does not implement per-operation SMS/voice selection:
https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml

Android exposes subscription/slot-specific radio services, rather than asking
the user to restart telephony for each message:
https://android.googlesource.com/platform/frameworks/opt/telephony/+/refs/heads/main/src/java/com/android/internal/telephony/RIL.java

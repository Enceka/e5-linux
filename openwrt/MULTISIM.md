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

The Linux/application path is still incomplete: ModemManager exposed only
one received SMS object and the notification service reported only the SIM 1
arrival. SIM 2's new message remained in its own storage, accessible by an
explicit card-addressed query. A visible inactive SIM object means it is not
the selected primary SIM; it does not by itself mean the CP radio is off.
Incoming calls to both numbers and SIM selection for outgoing operations have
not been verified by this SMS test.

The CP already starts both SIM radio stacks. Linux currently publishes one AT
port and one ModemManager modem at a time. `sipc_wwan` merges the selected
SIM URCs and reads/discards the other URC ring to avoid filling the CP buffer.
`e5-sim` stops WAN/ModemManager and changes the port, and `e5-sms send ... CARD`
uses that switch. Thus selecting the sending SIM also changes the data SIM.

The remaining target is application support for that dual standby: either SIM
can notify incoming SMS/calls at idle,
and the user can choose a SIM for each send/dial independently of the data SIM.
This does not imply two simultaneous active voice calls.

Work order:

1. Compare Android RIL per-SIM command and URC rings, including basic ATD/ATH
   commands. Extended commands currently receive SPACTCARD prefixes; basic
   commands do not. Validate serialization and which channel receives replies.
2. Publish two independently identifiable AT/URC endpoints, or retain explicit
   SIM identity in a multiplexed transport. Continue draining every CP ring,
   but dispatch its data instead of discarding the secondary SIM events.
3. Extend the Unisoc ModemManager integration to keep two live SIM contexts.
   Two ports under one physical parent are not automatically two independent
   modems: grouping, initialization, SIM identity and shared RF state need work.
4. Give every SMS/call an origin SIM. Merge inboxes without ID collisions;
   route sends/dials to the selected context without restarting the modem or
   changing SPSWDATA. Keep primary data selection as a separate operation.
5. Validate incoming SMS/calls to each SIM while the other carries data,
   multipart SMS, reboot recovery, absent/locked SIMs, and call/data coexistence.
   Keep the existing per-card band restrictions while testing; enabling a SIM
   with untested RF settings previously triggered CP assertions.

Upstream `SetPrimarySimSlot` selects a primary SIM and may recreate the modem;
its presence alone does not implement per-operation SMS/voice selection:
https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml

Android exposes subscription/slot-specific radio services, rather than asking
the user to restart telephony for each message:
https://android.googlesource.com/platform/frameworks/opt/telephony/+/refs/heads/main/src/java/com/android/internal/telephony/RIL.java

The remaining dual-SIM integration must receive and identify both SIMs'
unsolicited events in Linux and route per-operation commands. CP reception
already works in the SMS test above; UI selection alone does not complete
the application notification and routing path.

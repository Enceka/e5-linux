# E5 dual-SIM telephony work

The CP already starts both SIM radio stacks. Linux currently publishes one AT
port and one ModemManager modem at a time. `sipc_wwan` merges the selected
SIM URCs and reads/discards the other URC ring to avoid filling the CP buffer.
`e5-sim` stops WAN/ModemManager and changes the port, and `e5-sms send ... CARD`
uses that switch. Thus selecting the sending SIM also changes the data SIM.

The target is dual standby: either SIM can notify incoming SMS/calls at idle,
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

Dual-SIM implementation is a driver/telephony integration project. The first
milestone should be receiving and identifying both SIMs' unsolicited events;
UI selection alone cannot establish that behavior.

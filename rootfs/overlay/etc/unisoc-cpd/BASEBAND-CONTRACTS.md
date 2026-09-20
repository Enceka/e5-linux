# Baseband contracts (W0)

This is the differential table from the plan's workstream W0: what the vendor
side does on one platform, captured from the device, and what the Linux side is
expected to reproduce.  It is the document the rest of `unisoc-cpd` is written
against — a capability is not implemented here until its contract is written
down.

Provenance of each row is marked:

* **measured** — read off the device during the capture below;
* **ported** — inherited from `mu300-linux`, the sibling port of the same CP
  family, and not re-measured here;
* **researched** — found by researching this CP generation's extended AT
  surface; the shape is what to try first, not a promise, because it has not
  necessarily been sent to a handset yet;
* **open** — not established yet.

## 1. Capture: what was read, and from where

The capture was taken on the Android side (slot a), with the phone fully
booted and registered, because that is the state in which the vendor daemons
have finished configuring the CP — including whatever the RIL wrote into modem
NV, which the Linux side then inherits by booting slot a's images.

Commands used (read-only):

```sh
adb shell 'su -c "ps -A -o PID,USER,NAME,ARGS"'
adb shell 'su -c "ls -l /dev | grep -Ei \"stty|slog|dump|modem|pmsys|stime|sipa\""'
adb shell 'su -c "ls -l /dev/block/by-name"'
adb shell 'su -c "ls -l /proc/<pid>/fd"'          # per vendor daemon
adb shell 'su -c "grep -i mailbox /proc/interrupts"'
adb shell 'su -c "getprop | grep -Ei \"radio|modem\""'
```

## 2. Channels

| channel | node | type | owner on the vendor side | owner on ours |
| --- | --- | --- | --- | --- |
| AT command | `/dev/stty_nr1` | char 489,1 | `urild` (holds it for the whole boot) | `unisoc-cpd` (`profile.channels.cmd`) |
| URC | `/dev/stty_nr0` | char 489,0 | `urild` | `unisoc-cpd` (`profile.channels.urc`) |
| CP log spool | `/dev/slog_ch`, `/dev/slog_nr`, `/dev/slog_phy`, `/dev/slog_pm` | char 495,0 / 485,0 / 484,0 / 498,0 | `slogmodem`, `vendor.sprd.hardware.cplog_svc-service` | not yet drained — W1 |
| CP dump spool | `/dev/cp_dump` | char 10,123 | `sprd_cp_dump` path via the vendor HAL | not yet drained — W1 |
| time sync | `/dev/stime_ch`, plus `/dev/sprd_time_sync` and `/dev/spipe_nr8` | char 492,0 | `refnotify` | `e5-refnotify.service` today; not understood — W1 |
| mailbox | `64600000.mailbox` | GICv3 75/76/77 | kernel | kernel |
| data | `sipa_eth0` … `sipa_eth15` | netdev | `sipa` + RIL | `profile.data.ifname` |
| modem control | `/dev/modem` (481,0), `/dev/pmsys` (483,0) | char | `modem_control` | `e5-vendor.service` (chroot) |
| NV service | `/dev/snv_nr` | char | `cp_diskserver` | `e5-cp_diskserver.service` (chroot) |

**The rule the numbers imply.** On the vendor side `urild` opens `stty_nr0..5`
and `stty_nr13/14` at start-up and never closes them. The AT channel is a
*queue*, not a stream: a reader that opens, asks, and closes leaves the
backlog for the next reader, and a second concurrent reader gets nothing. Two
consequences, both of them in the core:

1. one owner per channel, enforced with an `flock` (`core/channel.rs`), so a
   second reader fails loudly instead of silently starving;
2. the channel is drained continuously by a reader thread, so a URC burst is
   never handed to the next command as its response.

## 3. URC dialect

Measured on the URC channel with nobody holding it: opening it dumps the
backlog that accumulated since the last reader.

```
+SIND: 1
+SIND: 10,"SM",1,"FD",1,...
+ECIND: 3,0,0,1
+ECIND: 3,6,1
+CMGW: ME is full
+PRENWINFU:"46001"
+CREG: 2
+CEREG: 2
+CSQ: 255,99                     (periodic, ~1/10 s when idle)
+CESQ: 99,99,255,255,255,255,75,67,73
+CGEV: ME PDN ACT 1               (bearer events)
+SPPCODATA: 1
```

A 45 s read produced tens of lines; an 8 s read produced 63 (~6 lines/s).
`profile.at.urc_prefixes` carries this list (the generation default in
`core/profile.rs`), and `core/at.rs` uses it to decide whether a `+XXX:` line
belongs to the command in flight or to the unsolicited stream.

### The two failure modes this layer exists for

Both were measured on 2026-09-18 and are the reason the daemon is shaped the
way it is:

* **`CP assert ... The queue was full`** at ~9.5 min: an empty run (no AT at
  all) passed 17 minutes with zero asserts, so the assert was *our* AT volume,
  not the firmware. The fix is pacing: a command channel is never written
  twice inside `profile.at.pace_seconds`.
* **AT dies without an assert**: both channels went silent while `sipa_eth0`
  kept passing traffic. So "the AT channel is dead" and "the CP asserted" are
  different events, and a watchdog has to key on AT's silence — which is why
  `link` probes with a real command and counts `probe_failures` separately from
  `commands`.

## 4. The AT command set

### 4.1 Standard (27.007 / 27.005), measured or ported

| purpose | command | notes |
| --- | --- | --- |
| liveness | `AT` | the probe `link` uses |
| SIM | `AT+CPIN?` → `+CPIN: READY` | `AT+CPIN="<pin>"` to unlock |
| SIM identity | `AT+CIMI`, `AT+CCID` | read-only; **no IMEI path exists in this program** |
| radio | `AT+CFUN?` → `+CFUN: 1` | a cold CP can read `1` with the stack still down |
| stack on | `AT+SFUN=2`, `AT+SFUN=4` | the vendor-specific "really turn the stack on"; **after a RIL shutdown parks the radio at `+CFUN: 0`, this pair alone sets `+CFUN: 1` but does not register — the cold cycle `AT+CFUN=0` then `SFUN=2/4` is what does (measured, FINDINGS §25.3)** |
| stack cycle | `AT+SFUN=5`, `AT+SFUN=3` | **avoid**: leaves this modem's SIM undetected until reboot |
| registration | `AT+CEREG?`, `AT+CREG?`, `AT+CGATT?` | AcT is the 5th field: 11 = NR SA, 13 = EN-DC |
| signal | `AT+CSQ`, `AT+CESQ` | `+CESQ: rxlev,ber,rscp,ecno,rsrq,rsrp,ssrsrq,ssrsrp,sssinr`; index→dBm is `idx-140` for RSRP, and **255 means "not reported", not `idx 255` (measured: an unregistered CP answers 255 in every field)** |
| operator | `AT+COPS?`, `AT+COPS=?`, `AT+COPS=0` | a full scan takes tens of seconds |
| SMS | `AT+CMGF=1`, `AT+CMGL="ALL"`, `AT+CMGR=<i>`, `AT+CMGD=<i>`, `AT+CMGS="<n>"` | `+CMGS` answers with a bare `>` continuation prompt |
| USSD | `AT+CUSD=1,"<code>",15` | `+CUSD: 0,"...",15` |
| voice | `ATD<n>;`, `ATA`, `ATH`, `AT+CLCC`, `AT+VTS="<d>"` | CS only |
| PDP | `AT+CGDCONT=1,"IPV4V6","<apn>"`, `AT+CGACT=1,1`, `AT+CGCONTRDP=1`, `AT+CGDATA="M-ETHER",1` | `+CGCONTRDP` fields: `cid,bearer,apn,"addr.mask",gw,dns1,dns2` |

Measured bearer, for reference:

```
AT+CGDCONT=1,"IPV4V6","3gnet"    -> OK
AT+CGACT=1,1                     -> OK
AT+CGCONTRDP=1                   -> 3gnet.MNC006.MCC460.GPRS,
                                    10.105.136.142/255.0.0.0, DNS 58.240.57.33 221.6.4.66
AT+CGDATA="M-ETHER",1            -> CONNECT
+COPS: 0,2,"46001",11            (NR SA)
```

### 4.2 Generation-specific extensions — researched

These are what makes the "contract belongs to the baseband generation" claim
true, and they live in `src/unisoc_at.rs` with the bit-mask tables and tests.
All of them came out of researching the modem's own AT surface, and none of
them has been sent to a handset yet.

| purpose | command | shape |
| --- | --- | --- |
| camped RAT | `AT+SPRAT?` → `+SPRAT: LTE 32` | the name token is unreliable; the number moves with the camped RAT |
| LTE band lock | `AT+SPLBAND=1,<49-64>,<33-48>,<17-32>,<1-16>,<65-80>` | one bit per band inside its 16-band group |
| LTE band read | `AT+SPLBAND=0` | same five words back |
| NR band lock | `AT+SPLBAND=2,<v1>,0,<v3>,<super>` | tables `NR_BAND_VALUE1` / `NR_BAND_VALUE3` / `NR_SUPER_BAND` |
| NR band read | `AT+SPLBAND=3` | words 0, 2 and 3 are the masks |
| LTE band unlock | `AT+SPLBAND=1,0,0,0,0,0` | all words zero |
| NR band unlock | `AT+SPLBAND=2,0,0,0,0` | all words zero |
| cell lock | `AT+SPFORCEFRQ=<12\|16>,6,<freq>,<pci>` | 12 = LTE, 16 = NR |
| cell unlock / read | `AT+SPFORCEFRQ=<12\|16>,4` / `,3` | `+SPFORCEFRQ: <rat>,3,<freq1>,<pci1>,…` |
| 5G SA / NSA | `AT+SP5GRAN?` / `AT+SP5GRAN=<0\|1>` | 1 = SA allowed, 0 = NSA only |
| 5G registration | `AT+C5GREG?` | `+C5GREG: <n>,<stat>,…` |
| VoLTE | `AT+CAVIMS?` / `AT+CAVIMS=<0\|1>` | 1 = enabled |
| VoNR | `AT+SP5GCMDS="get nr synch_param",42` / `"set nr param",45,<s>` | quoted vendor sub-command |
| UE usage setting | `AT+CEUS?`, `AT+CEMODE?` | `CEUS=1`/`CEMODE=2` = voice-centric, `=0`/`=1` = data-centric |
| engineering mode | `AT+SPENGMD=0,^…` | neighbour cells; parsed shapes not yet implemented |

**Correction to an earlier finding.** A previous note in this project said
band locking was "not reachable over AT on this CP generation" because
`AT+SPRAT=<n>` is `+CME ERROR: 4` and `NSACFG`/`SNRCFG`/`SBAND`/`WS46` do not
exist. That is true of those commands, but it is the wrong conclusion: the
band lock is `AT+SPLBAND`, and the cell lock is `AT+SPFORCEFRQ`. Both are
implemented in the `band` capability, which reads the lock back after writing
it — a lock that did not take must not look like one.

### 4.3 Deliberately absent

* **Band/RAT preference in NV.** `persist.vendor.modem.nr.enable`,
  `persist.vendor.radio.modem.config` and friends are written by the vendor
  RIL. The Linux side inherits them by booting slot a's images
  (`vendor-start.sh` rewrites the slot suffix), which is why the profile has
  its own `boot.active_slot`.
* **IMEI, NV writes.** Not absent — guarded; the contract lives in §8
  (`imei read`/`probe`/`write`, `nv backup`/`restore`).

## 5. Boot, NV and slot contract

| item | value | provenance |
| --- | --- | --- |
| CP boot | `modem_control` in a chroot, `exec`'d directly so `current->comm == "modem_control"` | measured |
| partitions | `nr_modem_a/b`, `nr_phy_a/b`, `nr_fixnv1_a/b`, `nr_fixnv2_a/b`, `nr_deltanv_a/b`, `nr_runtimenv1/2`, `prodnv`, `calinv` | measured |
| NV persistence | `cp_diskserver` (chroot), node `/dev/snv_nr` | measured |
| time sync | `refnotify`, `/dev/stime_ch` + `/dev/sprd_time_sync` + `/dev/spipe_nr8` | measured (files open) |
| slot selection | `sprdboot.slot_suffix` / `androidboot.slot_suffix`, rewritten to `_a` | ported |
| `_b` name remap | `nr_*_b` → `nr_*_a` unless `/etc/e5/modem-slot` says `current` | ported |

## 6. Kernel-side contract

| item | value | provenance |
| --- | --- | --- |
| mailbox interrupts | `GICv3 75/76/77` on `64600000.mailbox`, three lines | measured |
| mailbox counters | three lines, 0 / 31020+1741 / 22 as first-CPU counts at capture time | measured |
| data path | `sipa_eth0` is raw IP and NOARP; the driver hands up wrong hardware checksums, so RX offload must be disabled | ported |
| CP assert signature | `CP assert` in the kernel log; `profile.telemetry.assert_pattern` | measured |
| power | the PMIC watchdog resets an unattended session; `sprd_pmic_wdt.ko` must be staged | measured |

## 7. Open questions

* `/dev/stime_ch` is opened by `refnotify` and has not been understood: is it a
  request/response channel the CP needs served, or can it be left to the vendor
  daemon permanently? (W1, risk row in the plan.)
* The log and dump spools are named here but nothing in `unisoc-cpd` drains
  them yet; `diag spools` only reports presence and size.
* `AT+SPENGMD` neighbour-cell parsing was found during the research but is not
  implemented; it is the cheapest path to the A4 comparison against Android's
  `mCellInfo`.
* The AT command channel used by `urild` might be a RIL-framed channel rather
  than plain AT on this boot — the plain-AT behaviour was measured on the
  Linux side, where the same `modem_control` had been started by us.
* Does `/dev/sdiag_nr` come up under our kernel, and does the captured read
  template answer with the same shape there? On the Android side both are
  measured (§8); under our Linux they have not run yet — `imei read` is the
  experiment.
* The guarded write has run on the unit (Android side, RIL stopped for an
  exclusive channel transfer, diag read-back verified — §8.3).  The same
  write from the Linux side, where the daemon owns the channel without any
  transfer, is still to be exercised.

## 8. Identity and NV writes (guarded)

The plan carries exactly one red line — **never two readers on one AT
channel** — and this section is written to live inside it: identity and NV
writes are not forbidden, they are *guarded*, because the accident a raw
block device invites is one command away (a bad write into `fixnv` is a
modem that never registers again, and an identity write is not undoable by
the network), so every path here refuses until each guard passes.

Provenance: **measured** on the unit, Android side, 2026-09-20 — the diag
read of all three identity items, and a guarded write verified by diag
read-back, both ran.  Not yet exercised under our kernel (open items above).

### 8.1 Reading the identity (diag NV reads)

| item | value | provenance |
| --- | --- | --- |
| channel | `/dev/sdiag_nr` | **measured** (Android side, 2026-09-20: `crw-rw---- system system`, major 490) |
| read request | `7E 00 00 00 00 0A 00 <id_hi> <id_lo> 00 00 7E` — fixed bytes except the item id | **measured** — the captured template answers on the unit (2026-09-20); the meaning of the fields beyond the id is still not established |
| identity items | IMEI0 (SIM slot 1) `5E81`, IMEI1 (SIM slot 2) `5E82`, spare `5E90` — **zero-based**, the CP's and Android's own naming | measured (items answer); the naming convention is the owner's pin: 卡槽1 = IMEI0, 卡槽2 = IMEI1 |
| reply | record marker `74 00 5E 01`, then up to 8 BCD bytes, **low nibble first**, `A` as the odd-length filler | **measured** — replies parse and Luhn-check on the unit |
| decode | first 15 digits after the filler is dropped, then Luhn-checked | — |

Measured on the unit (Android side, root, 2026-09-20): `imei read` returned
`imei0 (5E81) = <imei>` — 15 digits, Luhn-valid — while `5E82` and
`5E90` read all-zero: SIM slot 2 is not individually provisioned on this unit.
The one-based labels an earlier capture used ("IMEI1/2/3") are exactly the
off-by-one this table exists to pin down: the CP counts identity slots from
zero, and `{index}` in a write template substitutes that zero-based value.

`imei read` drives this through `core/identity.rs` and reports exactly what
came back — a Luhn-invalid decode is printed loudly, never silently accepted —
because the template is a contract to verify, not a guarantee.

### 8.2 The AT identity surface (probe first)

`imei probe` sends the read-form commands the profile lists and records the
raw answers.  Per the W5 rule it only reports what the CP accepted; **a write
template is never derived from probe answers**.  The write dialect is a
property of the firmware build, and on this unit it was pinned not by probing
but by the owner, from the factory tool that provisioned it:

> `AT+SPIMEI=<slot>,"<imei>"` — slot **zero-based** (SIM slot 1 = 0,
> SIM slot 2 = 1).

That is recorded once in `[imei].write_command` (`{index}` substitutes the
zero-based slot, `{imei}` the value), and the write path is armed on it.  For
per-slot *reads*, this surface routes whole commands with the `SPACTCARD`
multiplexer: `AT+SPACTCARD=<phoneId>;AT+CGSN` executes against that card's
context — both forms sit in the profile's probe list.  Caveat, measured on
the unit: SPACTCARD routing only ever serves the **active** card, so a
per-slot AT read is not a way to see a second slot's identity.  The diag NV
items stay the only per-slot read (and an empty slot-2 item means the CP
falls back to slot 1's value, which is what "both slots the same" looked
like here).

One consequence of the ownership rule: in vendor mode the Android RIL
(`urild`) owns the AT channel, so on the Android side `imei write` fails at
channel ownership — loudly, and before anything is sent.  The guarded write
belongs where the daemon owns the channel: the Linux side; or, on Android,
an explicit ownership *transfer* (stop the RIL, write, verify, start it
again) — never a second concurrent reader.

### 8.3 The write guards (all mandatory, all recorded in the run summary)

1. `[nv].readonly = false` in the profile — the owner's decision, in data.
2. `[imei].write_command` set — no template, no write, nothing guessed.
3. 15 digits, Luhn-valid — `--allow-bad-checksum` exists for lab dummy values
   and is itself recorded when used.
4. A fresh `nv backup` first: every NV partition of the profile, both slots,
   into one directory with a `manifest.json` of sha256 digests.
5. The CP's ACK is not trusted: `imei write` re-reads the item over diag and
   fails unless the read-back equals the written value.

Measured end-to-end on the unit (Android side, 2026-09-20, with the RIL
stopped for an exclusive channel transfer and restarted after): the full
backup → write → read-back chain ran clean — the CP answered OK to the
pinned dialect and the diag read-back matched, for a restore to the
Luhn-valid value the unit carried before an off-by-one factory rewrite.

`nv restore` is the only raw write path: an exact image, sha256-vouched by
the backup manifest or `--sha256`, byte-exact partition size, `--yes`, both
slots by default, re-read and re-hashed after the write.  There is still no
in-place NV editing: `fixnv` carries internal checksums the CP's NV service
maintains, and hand-edited bytes are how a modem loses its calibration.

### 8.4 Legitimate use, plainly

These paths exist for your own development hardware: restoring an identity
lost to a bad flash, or programming a lab IMEI into a device that has none.
The IMEI is network identity — operators blacklist by it, and altering a
device's identity to disguise it is a crime in a number of jurisdictions.
Keep the factory value from the label or from the first backup you ever take;
every write lands in the run summary with what and when.

## 9. The control plane as a service (G2)

G2 is the point at which the daemon stops answering questions *about* the modem
and starts being the thing that answers *for* it.  On the Android side that
seat is held by `urild`: it opens `/dev/stty_nr1` and `/dev/stty_nr0` at
start-up, holds them for the whole boot, reads the unsolicited stream
continuously, and every other component asks *it*.  The SIPC channel allows
only one reader (§2), so the seat cannot be shared — it can only be taken
over.  Provenance for this section: the channel behaviour and the URC lines
are **measured** (§2, §3); the decoding table and the request/response shape
are **researched**, on the same basis as §4.2 — the shape to try first.

**This section has now been exercised on the device**: 2026-09-20, Android
slot a, with the daemon as the only reader of both channels after
`stop vendor.ril-daemon` — ownership, `link`, `sim`, `band`, `serve` + socket
clients, and URC decoding all measured working; the ownership *transfer*
procedure picked up one rule and the stack bring-up one requirement
(FINDINGS §25).  Still open: the same on the Linux side, where the daemon has
not yet been the owner at boot.

### 9.1 Ownership over a boot, not over a command

| | vendor side | ours (G2) |
| --- | --- | --- |
| who owns `nr1`/`nr0` | `urild`, for the lifetime of the boot | `unisoc-cpd serve`, for the lifetime of the boot |
| how a request arrives | the RIL's own socket, framework above it | a unix socket, default `<state-dir>/cmd.sock` |
| a second *caller* | served by the RIL | served by `serve`, over the socket |
| a second *reader* | not possible — the RIL never closes the port | refused loudly, `ChannelBusy`, exit 3 (§2) |
| the unsolicited stream | read forever, turned into framework notifications | read forever, decoded into the events of §9.2 |

That shape is what the acceptance matrix actually needs: A2–A6 can be run as
many times as wanted without ever releasing the channel, so the one-owner rule
holds across the whole measurement window instead of across one command.
`serve` also keeps the W1 duties alive while it works — an idle probe (a real
`AT`, counted under `at.probes`, never under `at.commands`) runs whenever
nothing else has touched the CP for `at.idle_probe_seconds`, and `state`
reports `last_ok_age_s`, the number a watchdog keys on, because an open
channel and an answering CP are two different facts (FINDINGS §22).

### 9.2 The unsolicited stream, decoded

The lines are the measured dump of §3; the per-line shapes below are what
`core/urc.rs` commits to.  A line the decoder does not know is kept as
`urc-other` with its text, never dropped: "the stream carried something we did
not decode" is evidence, and silence is not.

| URC | meaning | decoded as |
| --- | --- | --- |
| `+SIND: <code>[,<detail>…]` | SIM / storage indication (1 = SIM, 10 = ME storage) | `urc-sim-indication {code, detail}` |
| `+CPIN: <state>` | SIM state (`READY`, `SIM PIN`, …) | `urc-sim-state {state}` |
| `+CREG:`/`+CGREG:`/`+CEREG:`/`+C5GREG:` | CS / GPRS / EPS / 5G registration | `urc-registration {domain, status, act}` — `status` is field 2 of the measured `2,1,…` shape, `act` field 5 (7 = LTE, 11 = NR SA, 13 = EN-DC) |
| `+CSQ: <rssi>,<ber>` | signal strength, raw indexes | `urc-signal {rssi, ber}` |
| `+CESQ: …9 fields…` | signal quality | `urc-signal {rssi, ber, rsrp, rsrq, sinr}`, by the same decoder `signal` uses |
| `+CGEV: …` | bearer event (PDN ACT/DEACT, detach) | `urc-bearer {text}` |
| `+CMTI: "<storage>",<index>` | a message arrived into storage — **the MT SMS signal** | `urc-new-message {storage, index}` |
| `+CMGW: ME is full` | message storage full | `urc-message-storage {text}` |
| `RING` / `+CRING: <type>` | an incoming call | `urc-incoming-call {ring}` |
| `+CLIP: "<number>",<type>…` | caller identity | `urc-caller-id {number, address_type}` |
| `+CUSD: <status>,"<text>"[,<dcs>]` | USSD answer or network notification | `urc-ussd {status, text}` |
| `+SPERROR: …` | this generation's own error report | `urc-sp-error {code, text}` |
| anything else (`+ECIND:`, `+SPPCODATA:`, `+PRENWINFU:` …) | not decoded yet | `urc-other {line}`, kept verbatim |

Deliberately **not** here, and why:

* `+CMT:` / `+CDS:` (a message delivered inline) map to `urc-other`.  Inline
  delivery only happens when `AT+CNMI` asks for it; the measured path on this
  generation is `+CMTI:` into storage, and the daemon does not set `CNMI`.
* PDU mode.  The daemon sets `AT+CMGF=1` once at start-up and reports
  `text_mode` in `state`; if the CP refuses text mode it announces messages
  without reading them rather than handing back hex dressed up as text.
* Auto-delete.  Reading a message moves it to `REC READ` and that is all —
  deletion stays with the operator (`sms delete`), because a daemon that
  tidies up storage can destroy the evidence of its own misreading.
* `+ECIND:` (`3,0,0,1`, `3,6,1` measured) stays `urc-other`: its fields are not
  established, so guessing them would be worse than reporting them raw.
* MT call control (`urc-incoming-call` → `ATA`) and a D-Bus/ModemManager face
  in front of the socket, which is what lets `gnome-calls`/`chatty` use any of
  this (plan, `core/api`).

### 9.2.1 Acting on `+CMTI:` — the MT message path

The announcement and the read are deliberately two steps.  A `+CMTI:` can
arrive *inside* another command's reply loop — the URC sink fires there too —
and the one thing it must never do is send AT from inside that loop, because
the session's gate is held by the command in flight.  So the sink only queues
`(storage, index)`, and the serve loop drains the queue between requests, on
the same single thread that answers requests.  A repeated announcement of a
slot that has not been read yet is one read, not two.

A read is `AT+CMGR=<index>` in text mode; the reply parses into
`{storage, index, status, from, timestamp, text}` (`core/capability/control.rs`,
which also refuses a PDU-shaped header instead of misreading it).  The daemon
never deletes what it read; the `+CMTI:` itself still lands in the URC stream
and in whichever run summary was in flight.

### 9.3 The request/response contract

One request per connection, one JSON object per line — the shape the sibling
port's AT daemon already proves on this modem family — except that what is
asked for here is a **capability**, never a raw AT string.  Raw AT over a
socket would move the ownership rule out of the one process that enforces it,
and the red line would be a convention again.

```
$ unisoc-cpd --profile e5 --mode native serve --socket /run/unisoc-cpd/cmd.sock
$ unisoc-cpd --mode native --socket /run/unisoc-cpd/cmd.sock sim
+CPIN: READY
status: pass
```

| request | answered with |
| --- | --- |
| `{"capability":"<name>","args":[…]}` — action defaults to `run` | that capability's own output, `status`, `exit_code`, `notes` |
| `{"action":"state"}` | the daemon's state: pid, uptime, requests, idle probes, `last_ok_age_s`, channel and AT metrics, URC counts, message counts, the last 20 decoded events |
| `{"action":"urc","limit":N}` | the last `N` decoded URC events, oldest first |
| `{"action":"messages","limit":N}` | the last `N` messages read on their own after a `+CMTI:` — A5's MT half |

An unknown capability, a malformed line, or asking for `serve` itself is an
error in the response, not a dropped connection.  Every `run` writes its own
run summary on the daemon's side (that is where the run happened), with the
URCs that arrived while it was in flight recorded as its events; its telemetry
baseline is re-taken per request, so the deltas are per run and not per boot.

Exit codes are unchanged: `0` pass, `1` fail, `2` usage/config — including a
request the daemon rejects — and `3` environment, which now covers both "the
channel is owned by someone else" and "there is no daemon on that socket".

Two details that are easy to get wrong and are pinned by tests:

* only a `run` resets the idle timer.  A client polling `state` must not be
  able to postpone the probe — keeping the link warm is the daemon's job, not
  a side-effect of being watched;
* a live socket is refused before the channel is touched, so an owner that is
  already serving never even sees the next daemon reach for its lock; a stale
  socket file (SIGTERM does not unwind, so it is normal) is removed.

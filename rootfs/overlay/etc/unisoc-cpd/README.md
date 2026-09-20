# unisoc-cpd

A device-independent control daemon for the Unisoc CP (baseband), written against
[`BASEBAND-PLAN.md`](BASEBAND-PLAN.md).

> 中文文档：[`README.zh-CN.md`](README.zh-CN.md)

The AP-side contract is a property of the **baseband generation**, not of the
board: the SIPC channels, the AT/URC dialect, the CP boot handshake, the
log/dump spools, the time-sync channel and the mailbox quirks are the same
wherever this CP family is soldered on.  So the core here never names a
platform.  Everything a board knows — device nodes, partitions, interface
names, spool channels, vendor commands — lives in a profile under
`platform/profiles/`, and `unisoc-cpd profile-check` fails if that boundary is
crossed.

```
unisoc-cpd                     one binary, one profile
├── src/channel.rs             owns a channel, drains it forever, counts what it sees
├── src/at.rs                  AT codec, URC demux, serialisation, pacing, timeouts
├── src/urc.rs                 URC decoding: the control plane's unsolicited half
├── src/unisoc_at.rs           the CP generation's own AT extensions (band/cell/5G/IMS)
├── src/capability/            link, sim, cfun, register, signal, operator,
│                              band, nr, ims, sms, ussd, call, data, nv, diag, serve
├── src/telemetry.rs           per-run JSON: asserts, URC gaps, mailbox deltas, counters
├── src/profile_check.rs       the A12 gate, as a command
├── platform/profiles/e5.toml      the only file that knows about the E5
├── platform/profiles/mu300.toml   second platform, same core (stub, unverified)
└── docs/BASEBAND-CONTRACTS.md     W0: the channel/command/timing contract (§9: G2)
```

## Build

```sh
cargo build --release          # host
cargo test                     # 104 tests, no device needed
```

The tests run against a fake CP on a **pty**, which is the only honest stand-in
for an SIPC tty: a real tty with two ends, a driver that hands lines over in
bursts, and a modem that interleaves a URC into every reply — so response/URC
demultiplexing, pacing, timeouts and the `>` continuation prompt are all
exercised on every command, not only in the happy path.

For the device (Debian trixie arm64) see `tools/build-aarch64.sh`: the reliable
cross target is `aarch64-unknown-linux-musl`, because a static binary is immune
to the glibc version on the other side — which is also the cleanest reading of
the plan's "same binary, second platform".  That script is the whole recipe
(one non-obvious step: `rust-lld`, not the host's GNU ld, has to be the linker,
because `--fix-cortex-a53-843419` is an AArch64 option the host ld rejects).

## Run

```
unisoc-cpd [--profile NAME] [--mode native|vendor] <capability> [args]
unisoc-cpd mode native <capability>      # the test rig's spelling
unisoc-cpd capabilities                  # what it can do
unisoc-cpd profiles                      # what platforms it knows
unisoc-cpd profile-check                 # the A12 gate
```

Examples:

```sh
unisoc-cpd --profile e5 --mode native link --seconds 60      # CP link health
unisoc-cpd --profile e5 --mode native link --seconds 259200  # the 72 h soak (A1)
unisoc-cpd --profile e5 --mode native sim
unisoc-cpd --profile e5 --mode native band status
unisoc-cpd --profile e5 --mode native band lock nr 78
unisoc-cpd --profile e5 --mode vendor register               # vendor baseline
unisoc-cpd --profile e5 --mode native nv list                # read-only
```

`--mode vendor` runs the command the profile names for that capability and
records its output, so the same acceptance test can be run against the vendor
daemon and against ours and the two summaries diffed.  `link` and `serve` are
native-only: there is no vendor counterpart to compare a channel-ownership
measurement with.

## The resident owner (G2)

`serve` is the seat Android's RIL holds: it takes the channels once at boot,
keeps them, reads the unsolicited stream continuously, probes the CP when
nothing else is happening, and answers capability requests on a unix socket.
Because one AT channel has exactly one reader, a capability either opens the
channel itself (no `serve`) or asks the daemon (`--socket`) — never both:

```sh
unisoc-cpd --profile e5 --mode native serve --socket /run/unisoc-cpd/cmd.sock

unisoc-cpd --mode native --socket /run/unisoc-cpd/cmd.sock sim
unisoc-cpd --mode native --socket /run/unisoc-cpd/cmd.sock state   # the daemon's own state
unisoc-cpd --mode native --socket /run/unisoc-cpd/cmd.sock urc     # decoded URC events
unisoc-cpd --mode native --socket /run/unisoc-cpd/cmd.sock messages # messages the daemon read on its own (MT)
```

`serve` acts on `+CMTI:` by itself: when the modem announces a message, the
daemon reads it with `AT+CMGR` between requests (read-only — it never deletes;
PDU mode is not decoded and is reported as such), and a client collects the
result with `messages`.  Sending is `sms send <number> <text>` (the MO path,
whose `>` continuation prompt the AT layer already handles).

What is asked for is a **capability**, never a raw AT string: raw AT over a
socket would move the one-reader rule out of the one process that enforces it.
The contract — the URC→event table, the request/response shape, and what is
deliberately not implemented yet — is `docs/BASEBAND-CONTRACTS.md` §9.

## Telemetry

Every run writes `runs/<platform>/<date>/<capability>.<mode>.<hhmmss>.json` and
appends the same record to `runs/<platform>/<date>/summary.json`:

```json
{
  "platform": "e5", "mode": "native", "capability": "link",
  "status": "pass", "exit_code": 0,
  "at":        { "commands": 5, "ok": 5, "timeouts": 0, "probes": 5, "probe_failures": 0 },
  "channels":  { "cmd": { "opens": 1, "reopens": 0, "rx_lines": 10 } },
  "urc":       { "lines": 5, "max_gap_s": 0.5, "gaps_over_threshold": 0 },
  "mailbox_irq": { "before": 32760, "after": 32784, "delta": 24 },
  "cp_asserts":  { "before": 0, "after": 0, "delta": 0 }
}
```

That is the acceptance matrix in machine-readable form: A1's four clauses are
`cp_asserts.delta`, `urc.max_gap_s`, `mailbox_irq.delta` and
`channels.cmd.reopens`.

## Deploying on the E5

The soak is a systemd timer (`units/`), which is also the plan's rule that a
watchdog reboot must not hide the evidence:

```sh
install -Dm755 target/aarch64-unknown-linux-musl/release/unisoc-cpd /usr/local/bin/unisoc-cpd
install -Dm644 platform/profiles/e5.toml /etc/unisoc-cpd/e5.toml
cp -r units/* /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now unisoc-cpd-soak.timer
```

Taking the control plane over (G2) is the resident unit rather than the soak
timer: it declares `Conflicts=` on the incumbent AT brokers, so systemd stops
them for us — which is what "take over" means, as opposed to coexisting:

```sh
systemctl enable --now unisoc-cpd.service
```

While `e5-atd` (the incumbent shell broker) is running it owns
`/dev/stty_nr1`, and `unisoc-cpd` will refuse to become a second reader —
deliberately, loudly, with exit code 3.  Switch the vendor side off first:

```sh
systemctl stop e5-mobile-data-watch e5-mobile-data e5-atd
```

## Status

| | |
|---|---|
| core (channel/at/telemetry/profile/CLI) | implemented, 104 tests green |
| capabilities | `link`, `sim`, `register`, `signal`, `operator`, `cfun`, `band`, `nr`, `ims`, `sms`, `ussd`, `call`, `data`, `nv`, `diag`, `serve` |
| URC decoding (contracts §9.2) | implemented and tested; `+ECIND:`/`+CMT:`/`+CDS:` deliberately kept raw rather than half-decoded |
| G2 control plane (`serve`) | code and offline tests in place: resident ownership, URC events, capabilities over a socket, idle probes, `state` with `last_ok_age_s`. **Not yet on the device** — it has not been the owner of `/dev/stty_nr1` |
| W0 contracts | `docs/BASEBAND-CONTRACTS.md`, with the generation's AT extensions researched and unit-tested |
| A12 `profile-check` | pass (two profiles, no platform names in the core) |
| aarch64 build | static `aarch64-unknown-linux-musl`, built by `tools/build-aarch64.sh` |
| on-device, read-only | verified on the handset: `diag spools` (8 nodes, all `char`), `diag mailbox`, `diag asserts` (0 CP asserts), `nv list` (7 partitions). Each run's summary shows `at.commands: 0` and `channels.cmd.opens: 0` — the AT channel is deliberately not touched while the vendor RIL owns it |
| on-device, AT | **measured on the Android side** (2026-09-20): after `stop vendor.ril-daemon` the daemon was the only reader of both channels — `link`, `sim`, `band`, `serve` + socket clients all passed with 0 CP asserts and 50/50 URC lines decoded; the transfer rule and the stack cold-cycle requirement are in FINDINGS §25. **Not yet at boot on the Linux side**, not soaked, no profile is `verified` |
| log/dump spool drains, `stime_ch` | not implemented (W1, still open) |
| voice | `voice.supported = false`: no UCM/voice route on this platform yet |

## Licence

MIT, as the rest of this repository.  The generation-specific AT commands in
`src/unisoc_at.rs` came out of researching this CP generation's own AT surface;
the contract is written down in `docs/BASEBAND-CONTRACTS.md`.

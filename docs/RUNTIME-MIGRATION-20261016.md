# Runtime fixes after the component split

This integration adapts the runtime changes from `kanoqwq/e5-linux`
`cf51e30d67a044cea5c30cb3af44f006fbc429d8` to the component layout at
`sprd-linux-devs/e5-linux` `569f13d4ce15585f70817c2a1e03bb574a84720b`.
It preserves upstream board overlays, screen scaling and existing feature gates.

## Scope

- Shared kernel adapters: display/eMMC DMA, EIC teardown, thermal readings,
  SIPA ownership/checksum/retry handling, fuel-gauge state and Unisoc SAE.
- WiFi: ordinary AP multicast uses the flow-controlled data queue; control
  traffic keeps the pinned E5 driver's existing classification. Enabled APs
  recover once after a successful WCN reset; manually disabled APs stay off.
- ModemManager: mobility address renewal, dual-SIM SMS context isolation,
  and validation of power/mode transitions and activation prerequisites.
- OpenWrt: passive modem recovery, complete bearer snapshot replacement,
  offline-aware lock receipts, radio restart guards, SMS forwarding results,
  per-SIM controls, boot intent display and WiFi capability compatibility.
- Infoscreen: band readback, unread SMS state, boot intent and power-menu
  confirmation, focus and keyboard handling.
- Integration: matching hostapd/wifi-scripts SAE packages, source fingerprints,
  shared board preparation/staging hooks, kernel feature audit and field capture.

Installer GUI, installation/flashing/partitioning scripts, installer-specific
kernel switches and first-boot markers, image packaging workflows, Magisk and
Android APK changes are excluded. Existing default-boot runtime controls remain;
their misc/intent update now verifies the write and rolls back on failure.

## Validation during migration

- Python compilation, shell syntax checks and `git diff --check` (excluding
  stored `.patch` files, whose context prefixes are significant).
- Twelve regression scripts: display, existing upstream fixes, WiFi capability
  generation, modem recovery and port discovery, bearer mobility parsing,
  multipart/dual-SIM SMS, lock control, radio restart, power events and screen
  profiles. Platform-specific optional cases report skips.
- C harnesses using source fixtures from the pinned kernel
  `020b970e351eee3887e6caaf2d653926e7086e44`: WiFi IPv4/IPv6 AP/GO/STA packet
  classification, SIPA PM/reference/ownership/retry/checksum behavior and
  fuel-gauge persistence/error/shutdown behavior, including idempotent adapters.
- WCN reset/cooldown/manual-disable and multicast RX harnesses against the
  local vendor driver fixture with the shared WiFi adapter applied.
- Prepared ModemManager 1.24.0 source: power prerequisite and SMS isolation C
  harnesses, including both slot orders, CMS failures and restoration failures.
- SAE bridge C harnesses with address/undefined-behavior sanitizers; real
  OpenWrt ucode SAE/PMF generation, per-SIM screen band contract and SMS
  forwarding answer/transport fixtures.
- Node: voice switches and confirmation, SIM-scoped RPC, lock job completion,
  offline receipts, progressive rendering and English/Turkish translations.
- Playwright: screen request lifetime/shutdown, disabled channel analysis,
  LuCI/screen boot banners and save failures, power-menu focus/keyboard/touch
  cases. Screen session startup unit tests also pass.

Full kernel/APK/image rebuilds and hardware endurance tests were not repeated
for this migration. Component PRs must be integrated before updating the parent
submodule pins; if upstream squash-merges them, replace pins with the resulting
upstream commits.

# Remote main and PR #12 reconciliation

## Source revisions

- Original local main: `569f13d4ce15585f70817c2a1e03bb574a84720b`.
- Remote main: `9095b4a1cc03891e8fc7de3cb840595ad95113e1`.
- Common ancestor: `e4cfda0837b673f045bdafabe0344e4c4d5dd456`.
- [PR #12](https://github.com/sprd-linux-devs/e5-linux/pull/12): `a7214729731336151ba65c9d262afcff3a39a7ec`.

Remote main contains 43 commits after the common ancestor, changing 696 paths.
PR #12 already contains the original local history and adds `bb8775e` and
`a721472`. The final history retains those original PR commits, avoiding copies
of already present commits. Only the remaining remote content is ported above it.

## Content accounting

[REMOTE-SYNC-20261018.tsv](REMOTE-SYNC-20261018.tsv) accounts for every one of
the 696 changed remote paths and records its current location and comparison.

| Result | Paths |
| --- | ---: |
| Identical remote contents, including 139 files already present in pinned components | 580 |
| Existing component adaptations: split paths, shared helpers, board policy and screen feature gates | 79 |
| Parent adaptations preserving split paths, provenance and existing build fixes | 29 |
| Installer runtime assets retained by the parent instead of editing components | 3 |
| Additional installer regression tests retained by the parent | 4 |
| Release workflow preserved as a template for the separate release repository | 1 |

Of the 471 parent paths, 27 were already identical to remote main at the PR
head. They are not changed again. Component commits and working files are not
rewritten. The parent gitlinks retain exactly the revisions submitted in PR #12.

## Integration decisions

- Keep the `device/` submodule layout and independent infoscreen repositories.
  Do not restore the retired `devices/`, rootfs overlay or duplicated screen base.
- Retain the full shared desktop installer, Windows/macOS build workflows,
  internal-partition install/reinstall/resume, uninstall preservation/evidence,
  Android loop handling, SSH updates, Magisk TF packaging, switch APK/plugin,
  binaries, source fingerprints, screenshots and validation records from remote main.
- Preserve local SDK frozen-default fixes, package download retries, selected
  kernel output, UTC+8 build time, all component source revisions, NV isolation,
  executable-script auditing and OpenSSL checks.
- `boot/installer-runtime` contains the remote GPT resize/carve helper and both
  distributions' partition-trial confirmation scripts. The builders stage them
  after device composition, and the initramfs/package builders use the same GPT
  source. This preserves installer behavior excluded from the component PRs.
- Install `iw-full` in both parent build paths without changing the component
  package list. Keep the Wi-Fi SAE package/bridge source audit.
- Keep publication in `sprd-linux-devs/release`. The complete adapted workflow
  is preserved in `tools/ci-release-workflow.yml`; the GUI reusable workflows
  accept the caller's source repository/ref. The external release repository's
  online workflow was not changed in this reconciliation.
- Retain remote TF behavior: use the first existing partition, or the whole
  unpartitioned card, grow to target capacity and keep the partition table intact.
  Do not reintroduce the previous reserved OTA layout through stale documentation.

## Validation

- 27 Linux Python suites pass using Python 3.12, Paramiko 4.0.0 and lz4 4.4.5.
  The unittest suites contain 369 cases, with 7 conditional skips; additional
  script-style checks cover configuration preservation and package composition.
  These include the 195 desktop backend cases and 21 release-audit cases.
- All 13 system-switch plugin Node cases pass on Linux, including simulated
  writes, rollback and concurrency on temporary regular files.
- Ten GPT plan/resize/carve scenarios pass with real OpenWrt ARM64 ucode and
  synthetic disk files. Read-only plans preserve both GPT copies.
- Android bundled-tool fixtures pass with the actual static ARM64 BusyBox input.
- Desktop TypeScript/Vite production build passes.
- 158 parent Python sources and 85 shell scripts pass syntax checks; workflow
  YAML and shell blocks parse. Whitespace checks retain remote CRLF endings and
  existing final blank lines rather than changing otherwise identical inputs.
- The original submodule working changes and untracked user files are retained.

No device connection, kernel/APK/image rebuild or release publication is part of
this reconciliation. Historical hardware reports are imported as source records,
not presented as new hardware validation.

Local recovery refs preserve all three starting points:
`backup/sync-20261018-local`, `backup/sync-20261018-remote` and
`backup/sync-20261018-pr12`. The remote update uses an explicit lease on
`9095b4a1cc03891e8fc7de3cb840595ad95113e1`.

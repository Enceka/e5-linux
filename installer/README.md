# Building the desktop installer

The shared sidebar credits installer author Minikano and provides four copy-number QQ buttons plus two fixed project links. E5 points to `https://github.com/sprd-linux-devs/e5-linux` (Enceka and Minikano), and MU300 points to `https://github.com/dikeckaan/mu300-linux` (dikeckaan and Minikano). Minikano is credited as co-author of both. Native `open_repository` accepts only the IDs `e5` and `mu300`, which map to those two literal URLs; it does not accept a URL or shell command.

`ui/src/components/support.tsx` provides an optional donation notice on every application launch, followed by onboarding when applicable. Closing it lasts for that window only; older `support-notice-v1` acknowledgements are ignored. A labeled sidebar button reopens it. Both repository entries include a Lucide GitHub icon, and the dialog invites a Star through the same fixed-ID repository opener. Opening the page does not automatically star anything. Only the donation image host is added to CSP `img-src`; scripts and IPC/network command permissions remain restricted. Online loading uses a normal no-referrer image request, with a five-second timeout/error fallback to `ui/src/assets/donation-fallback.png`. The checked-in 613×514 PNG was downloaded from `https://api.kanokano.cn/pay/zsm.png` on 2026-10-15: 161,701 bytes, SHA-256 `22c0d03221750cfb7a8c59692ff0e7d7530e56b807fe731ed23522403ce99be3`. It is fingerprinted and embedded in the GUI release, not the device rootfs. To refresh it, download that exact source, inspect the image and update this provenance before rebuilding.

Build dependencies (users do not need these): Windows x64, MSVC C++ Build Tools and Windows SDK, Rust 1.90.0, Node 22+, Python 3.12, PyInstaller, Paramiko, lz4. A system WebView2 Runtime is required to run the GUI. See the [Tauri Windows prerequisites](https://v2.tauri.app/start/prerequisites/) and [portable WebView2 configuration](https://v2.tauri.app/reference/config/).

```powershell
python -m pip install pyinstaller paramiko lz4
python -m unittest discover -s installer/tests -v
python installer/build.py
```

## Apple Silicon macOS and combined releases

Run the same `python installer/build.py` on an Apple Silicon Mac with Xcode Command Line Tools, native ARM64 Python 3.12, Node 22 and Rust 1.90.0. Install the same Python build dependencies first. It creates `installer/artifacts/macos-arm64/OpenWrt-Installer.app`, `tools/macos/adb`, the private Python backend under `tools/macos/backend`, and a source/binary fingerprint manifest. macOS uses system WebKit, the native `open` command and `~/Library/Application Support/OpenWrt-Installer` for recovery records. The app locates either E5's `files/device-profile.json` or MU300's `desktop/manifest.json`; Finder translocation prompts for the extracted package folder. The macOS command-line launcher uses the same bundled backend, without a system Python dependency.

The build checks GUI architecture, applies and verifies an ad-hoc app signature, and pins Google's Darwin platform-tools archive in `platform-tools-macos.json`. The bundle version and identifier come from Tauri configuration. This is ARM64 support only; it does not produce an Intel or universal app. Ad-hoc signing is not Developer ID signing or Apple notarization, so downloaded applications may require explicit permission in Privacy & Security. See [Tauri's macOS distribution instructions](https://v2.tauri.app/distribute/macos-application-bundle/) and [signing documentation](https://v2.tauri.app/distribute/sign/macos/).

`.github/workflows/gui-macos.yml` supports reusable calls, manual dispatch and `build/macos-*` branch pushes. It uses GitHub's native ARM64 `macos-15` runner, runs backend tests, builds release binaries and checks the frozen backend protocol, ADB, GUI architecture and signature without connecting to devices. The artifact is transported as `openwrt-installer-macos-arm64.tar.gz` to preserve executable permissions. [Runner architecture reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

E5's main release workflow now requires **both** GUI jobs. It downloads Windows files, restores the macOS tar artifact on the Linux packaging runner, then sets `OPENWRT_GUI_MACOS_ARTIFACT` before assembling the firmware archive. This path is shared by the E5, M8 and T551M package assemblers. For a local combined release, provide both artifact directories:

```sh
export OPENWRT_GUI_ARTIFACT=/path/to/windows-artifact
export OPENWRT_GUI_MACOS_ARTIFACT=/path/to/macos-arm64-artifact
# Run the existing model-specific firmware package builder afterward.
```

`package_gui.attach` also detects a local `installer/artifacts/macos-arm64/build.json` automatically. **Every normal desktop release requires both Windows and Apple Silicon macOS artifacts**, including local profile builds and installer refreshes. Missing Mac output fails before copying either platform; it never silently produces a Windows-only release. Both artifacts must match the current source and their platform, complete file lists and binary checksums before either is attached. Text fingerprints normalize Git CRLF/LF differences; binary hashes remain exact. Runtime directories are replaced so removed dependencies do not survive a refresh. The root EXE and APP share one firmware payload; desktop dependencies stay outside device payloads. `size_report` includes separate `gui_windows_bytes` and `gui_macos_bytes`, their total `gui_bytes`, backend/tools, firmware and archive sizes. The shared ZIP writer records Unix execute permissions for the Mac app, backend, ADB and command-line launchers even when packaging on Windows. `OPENWRT_GUI_OPTIONAL=1` remains for source-only test fixtures, not a desktop release.

To validate this integration without compiling anything, run `python -m unittest discover -s installer/tests -p test_macos_integration.py -v`. External build/signing commands are intercepted and attachment checks use tiny disposable text fixtures. This does not establish native macOS runtime or hardware compatibility; those checks run when the Mac workflow is actually invoked.

## Shared runtime and packaging

`ui/rust-toolchain.toml`, Cargo.lock and package-lock.json pin the build graph. `build.py` runs a Tauri release build with size optimization/LTO/strip and builds a console-protocol Python sidecar. The Tauri host spawns it with CREATE_NO_WINDOW. `installer/artifacts/windows` contains `OpenWrt-Installer.exe`, `tools/backend/`, and `build.json` with source/binary hashes. No browser runtime, Node, Rust, Python installation, cache, large fonts or development dependencies are shipped. The bundled interpreter is private to the sidecar.

The artifact also includes ADB and its two Windows USB DLLs under `tools/`, plus `ADB-NOTICE.txt`. `platform-tools.json` pins Google's 37.0.1 archive URL and SHA256; only these necessary files are extracted. `--adb-dir` accepts a pre-fetched official platform-tools folder for offline builds. Normal packaging therefore does not rely on ADB installed on the end user's PATH or an optional environment variable.

The host uses fixed Rust commands for dialogs, protocol requests and opening the application-data directory. CSP restricts remote content and scripts. Window-close handling prevents killing an active backend. A missing WebView2 Runtime produces native installation instructions. Portable distribution requires the complete adjacent `tools/backend` directory; the root EXE by itself is not the complete package.

Host firmware converters are allowlisted under `scripts/tools`. They have detached stdin, captured stdout/stderr, hidden subprocesses, diagnostic heartbeats, safe pause and a 120-second timeout. `--run-tool` compiles source helpers with optimization zero, preserving their docstrings and guards when the sidecar is built with `--optimize 2`. Firmware extraction/conversion have named UI phases; structured activity events clear the preceding file's completed progress bar. Tests include real converter execution after simulated extraction and optimized-host execution, rather than only checking process routing.

`OPENWRT_GUI_ARTIFACT` can point to an extracted Windows build artifact while packaging on Linux. Existing e5 `install-entrypoints.py` and MU300 `desktop/package.py` call `package_gui.attach` before generating final manifests. GUI sources and binaries are fingerprinted; missing/stale artifacts fail normal packaging. `OPENWRT_GUI_OPTIONAL=1` permits source-only/test fixtures and must not be used for a GUI release. Old optional console EXEs are stored under `tools/legacy`; the root EXE is always Tauri.

MU300's `--exe` packaging option accepts the GUI artifact **directory**. Legacy console EXE input remains accepted under `tools/legacy`. `tools/build-openwrt-tf-magisk.sh` still calls the same package assembler; set `OPENWRT_GUI_ARTIFACT` (or its existing MU300_DESKTOP_EXE to the directory). e5's profile builder and make-flash-bundle paths use the same attachment. Root Magisk files and a single rootfs remain intact; desktop code is not added to any device initramfs or rootfs.

To refresh the generated MU300 mirror:

```powershell
python installer/sync.py D:\Git\mu300-linux-clean-tf-7.2
python installer/sync.py D:\Git\mu300-linux-clean-tf-7.2 --check
```

`package_gui.size_report(package, archive)` reports GUI, backend/tools, device firmware payload and final compressed archive bytes separately. `release.py` augments an existing validated package into a new output directory, refreshes only host installer sources/manifests, preserves the firmware payload, then tests ZIP CRCs. Never overwrite an existing published package.

Validation uses fake transports and disposable files. Run POSIX device-script tests in Linux/WSL; Windows path syntax is not valid in those shell test fixtures. Actual hardware erase, resize, boot synchronization and Magisk installation require a separate authorized hardware run. See the verification report for what was actually executed.

For the complete browser regression suite, install development-only Playwright (`python -m pip install playwright`, then `python -m playwright install chromium`), build the production frontend and run `python -X utf8 installer/tests/run_ui.py`. It starts and stops its own local server, checks all six UI suites and writes `verification/ui-regression.json`. It refuses an occupied test port and never connects to ADB/SSH. Windows CI runs the same suites after its release build.

## Desktop layout, feedback and motion

MU300 updates use `backend/mu300_update.py`; packaging generates the compatible CLI helper `desktop/update_control.py` from the same file. The adapter calls the shared implementation even when an older package's Python entry rejects `legacy`. Hidden-area support requires the live OpenWrt container, ext4 label/capacity and loop backing/offset/extent to agree with eMMC/GPT bounds and the packaged boot's existing discovery logic. Checks run before uploads and immediately before commit. The native upgrade lock, config/account/vendor migration, disk staging, rollback and readback checks remain in the packaged updater. Unknown layouts stop; no GPT edit, resize or format is introduced by this compatibility path.

The window has a fixed viewport: header, sidebar, primary actions and footer stay visible. Purpose lists, recovery records, installation content and expanded logs have independent scroll areas. The package extraction reminder and transaction-folder shortcut stay at the bottom of the sidebar. Recovery controls remain compact at the minimum 800×650 window size, including when the log is open.

Device enumeration is independent of payload verification: the install/advanced/one-time-boot views refresh once on entry, and Refresh devices remains available with an empty list or before verification. Device inspection and installation still require a verified package. Every refresh clears the old inspection so stale root/readiness cannot authorize a later action. Empty responses and enumeration failures clear stale selection; multiple-device responses retain only an explicitly selected device that is still present.

Installation mode is explicit and stable: probing does not change it, Advanced defaults to reinstall, and returning from review preserves the method and originating page. The review names the selected method. Non-TF probes collect only an optional removable-card availability hint and never call the legacy mandatory SD detector or validate card capacity. Physical card discovery excludes the eMMC carrying userdata instead of assuming `mmcblk1` is the card. TF probes retain strict card/partition selection and failure handling. Execution rejects a method that differs from the saved plan before probing or writing.

`tests/test_method_routing.py` exercises the actual adapter probe and coordinator planning paths, real E5 legacy GUI-mode SD errors, all method argument/entrypoint mappings and mismatched-plan refusal using simulated reads and mocked write entrypoints. `tests/method_smoke.py` checks the exact frontend protocol parameters, no-card reinstall review, explicit choices with a present card and return-to-edit behavior. Neither test writes to a connected device.

`tests/frozen_method_smoke.py <package-folders...> --report <report.json>` runs the same no-card probe/plan isolation inside each real bundled backend executable using a simulated transport. It loads the package's actual legacy installer/profile, verifies that all non-TF probes and the internal-reinstall plan succeed without card detection, and confirms that TF installation still rejects a missing card. No external Python is used by the child backend and no device connection is opened.

Static captions, navigation, button text and headings do not allow text selection. Editable fields, paths, device/plan values, logs, error details and manual body text remain selectable for copying. `tests/refresh_smoke.py` covers empty-list/error retries before verification, multi-device and unauthorized states, stale inspection invalidation, relevant views and selection behavior without device writes.

[Sonner](https://sonner.emilkowal.ski/) is the single notification surface for request results, native/clipboard errors and transaction changes. Transaction snapshots are deduplicated by identity, stage, status and error; repeated polling does not reset elapsed time or flood notifications. Destructive warnings, actionable waiting guidance, failures and final results also remain in context. Notifications appear above the content, away from the bottom confirmation controls. Loading notifications transition to their result; cancelling a save dialog does not report a successful export.

[Motion for React](https://motion.dev/docs/react) supplies short page entrances/exits, purpose-row interactions, phase/result entrances and log expansion. `LazyMotion` loads the DOM animation feature set without layout/drag features. `MotionConfig`, `useReducedMotion` and CSS respect the operating system's reduced-motion preference; waiting for the user uses a static device icon rather than an endless execution spinner. No transfer percentages are synthesized.

To exercise the production UI without ADB/SSH, install Playwright on the development machine, build the frontend, serve `installer/ui/dist` on `127.0.0.1:1420`, and run `python -X utf8 installer/tests/ui_smoke.py`. This test injects its transport fixture only into the browser test context. It checks bounded scrolling, large record/log lists, notifications and deduplication, device binding, confirmation controls, themes/languages and reduced motion, and refreshes the screenshots.

## Onboarding and offline help

The three-step getting-started guide appears after a successful startup when no saved transactions exist and `onboarding-v1` has not been acknowledged in this application's local storage. Completing, skipping or closing it remembers that choice. Home can replay it at any time. Existing records suppress automatic onboarding so recovery remains the priority. The guide performs no backend operations.

The header help button and F1 open an independent help dialog without navigating away from the current plan, password fields or running task. Waiting phases link to the relevant setup/authorization topic. Closing with Escape or the close button restores focus to the originating control. Radix Dialog provides modal keyboard focus management; topic lists and article bodies scroll independently within the minimum 800×650 window. Help and onboarding honor the existing theme/language/reduced-motion preferences.

`ui/src/help-data.ts` imports the bilingual `GUIDE.md` as text at build time and selects localized topics, so root `START-HERE.md`, the packaged guide and in-app detailed help share one source. Search matches topic titles and full content. Markdown is rendered with `react-markdown`, without raw HTML or remote content; displayed URLs are selectable text. The help module/Markdown renderer loads on demand. `GUIDE.md` is part of the source fingerprint: a guide change requires rebuilding the GUI artifact.

Run `python -X utf8 installer/tests/help_smoke.py` against the same production-bundle test server to cover first launch, replay, skip/persistence, saved-record suppression, search/no-match state, focus trapping/restoration, F1/Escape, relevant help during installation, bilingual bounded dialogs and the absence of help-driven backend commands. This is browser automation with a test-only bridge, not device installation validation.

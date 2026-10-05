# OpenWrt on the Rongyue E5

> 中文：[`README.zh-CN.md`](README.zh-CN.md)

OpenWrt **25.12.5** with the mainline E5 **6.18.y** kernel. Android stays on
slot A; Linux boots slot B. The device panel runs the information screen and
its apps, including the Phone dialer/contacts page. LuCI is the separate router
web interface.

## Install and update

Download a complete mainline bundle from [Releases](https://github.com/Enceka/e5-linux/releases),
unpack it, then run `flash.cmd` on Windows or `./flash.sh` on macOS/Linux.
Follow the included bundle README and interactive installer. A first install
starts from rooted Android and extracts that device's firmware/vendor files;
the generic image contains neither those files nor personal device identity.

SD installation is recommended. It checks space and allocates the removable
card, preserving Android eMMC GPT. The shared `e5boot` registry tracks the
selected system and each system's slots. Existing standalone userdata images
and older directory installations remain supported.

For a running OpenWrt system connected over USB:

```sh
./flash.sh --update
```

Updates preserve configuration, contacts, forwarding profiles and the durable
SMS inbox. Kernel and root modules must come from the same build. Read installer
errors before retrying; they identify the failing stage and device response.

## Use

- USB management LAN: device **192.168.9.1**, host normally **192.168.9.2**.
  USB and hotspot share `br-lan`. The WAN supports IPv4/IPv6 through ModemManager.
- **Info screen → Apps → Phone:** dialer and contacts on one screen. Phone 1.5
  selects the outgoing SIM and labels the origin of incoming calls. Ring sound,
  vibration and screen wake are plugin settings.
- **LuCI → Services → SMS:** merged or card-filtered inboxes, source labels,
  send-card selection and shared/per-SIM forwarding profiles. Receiving/sending
  does not change the selected data card.
- **Info screen → Settings → USB:** reset USB connection and collect a one-click
  connection report for USB/hotspot issues.
- Return to Android through the screen's boot settings or `e5-next-boot android`,
  then reboot. The [Magisk module](../magisk/README.md) provides a manual Android
  Action to return to the installed Linux system, preserving SD selection.

## Dual-SIM validation

Current stack: kernel `6.18.54-e5-00072-g020b970e351e`, ModemManager
`1.24.0-r917`, information screen `1.6.7`, Phone plugin `1.5`.

Both cards' SMS reception, sending and correct source identity are verified.
SIM2 outgoing receiver downlink and incoming alerts are verified. SIM2
microphone uplink, answered incoming audio and a sustained 30-second call
remain unverified. The shared voice frontend supports one active conversation;
starting another call returns a busy error and does not hang up the existing
call. Details and native per-call SIM API: [MULTISIM.md](MULTISIM.md).

## Build and release

```sh
docker build -t e5-mainline-build upstream/
E5_RELEASE=1 upstream/build.sh
openwrt/build-modemmanager.sh
openwrt/build-bluez.sh
E5_MAINLINE=1 E5_TOOLS_BUILD_IMAGE=e5-mainline-build openwrt/make-flash-bundle.sh
```

Run these commands from the repository root. Existing bootstrap templates,
BusyBox and information-screen inputs are required; [RELEASE.md](../docs/RELEASE.md)
explains preparing them for CI. `build-rootfs.sh` rejects stale/unverified
ModemManager APKs. The package build runs source-identity/routing tests without
calling a modem. Generic archives go to `out/openwrt/`; the release validator
checks backend/UI source hashes, kernel modules and ZIP/TAR contents.

GitHub Actions builds/publishes the mainline bundle and Magisk ZIP, with UTC+8
compile time precise to a second. First boot starts ModemManager, the vendor
CP runtime and the audio services; network availability follows registration.

Hardware/service implementation lives in `overlay/`, the shared scripts in
`../rootfs/overlay/opt/e5/`, and the Unisoc MM patches in `../rootfs/deb-patches/`.
The older 5.15/vendor and userdata directory forms are retained compatibility
paths; the current one-click bundle uses mainline and SD installation.

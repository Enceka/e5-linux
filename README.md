# Linux on Unisoc devices

[简体中文](README.zh-CN.md)

Boot tooling, kernel adaptations and userspace builds for the Rongyue E5, T551M and VIPME M8.
Debian 13 / Phosh and OpenWrt configurations are maintained in independent repositories under
[sprd-linux-devs](https://github.com/sprd-linux-devs).

## Devices

| Device | Debian | OpenWrt | Scope |
| --- | --- | --- | --- |
| Rongyue E5 / UMS9621 | Phosh supported | Supported | SD multiboot recommended; legacy userdata loop images retained |
| T551M | No profile yet | Trial adaptation | Own charger, GPIO backlight, 32-bit vendor runtime and isolated NV |
| VIPME M8 / UMS9620 | No profile yet | Bring-up | Own kernel/display/USB/audio adaptations; not a release image |

Read the device-specific build and validation notes for [E5](https://github.com/sprd-linux-devs/linux_device_e5/blob/main/README.md),
[T551M](https://github.com/sprd-linux-devs/linux_device_t551m/blob/main/README.md) and [M8](https://github.com/sprd-linux-devs/linux_device_m8/blob/main/README.md).
A shared SoC does not establish compatibility with another handset.

## Checkout

```sh
git clone --recurse-submodules https://github.com/sprd-linux-devs/e5-linux.git
cd e5-linux
```

After updating an existing checkout:

```sh
tools/sync-device-repos.sh
python3 tools/device-layout.py list
```

Submodules pin source commits. The sync script restores those commits rather than advancing to branch tips.
The full kernel source is a separate checkout:

```sh
git clone --branch e5-6.18 https://github.com/sprd-linux-devs/linux.git linux-lts-e5
```

Generic builds require the committed shared fixes listed in `upstream/kernel-source.json`.
E5 model builds use the same `e5-6.18` branch and apply only their model differences.
Build versions retain the kernel version and device suffix without Git/dirty suffixes;
release metadata records the exact source commits. See [kernel sources](docs/KERNEL-SOURCE.md).
Other device adapters can require a specific kernel commit; follow their checks.

## Repository layout

Every device repository lives at `device/[system]_device_[model]`; shared repositories use `common`.
The `linux` layer holds kernel adaptations and runtime scripts shared by distributions.
The `debian` and `openwrt` layers hold distribution-specific configuration.
All ten device repositories come from `github.com/sprd-linux-devs`.

| Path | Contents |
| --- | --- |
| `device/linux_device_common/` | Shared kernel fixes, CPUFreq, Wi-Fi/USB helpers, runtime scripts and regulatory database |
| `device/linux_device_e5/`, `linux_device_t551m/`, `linux_device_m8/` | Per-device kernel, hardware/audio assets, boot and collection tools |
| `device/debian_device_common/` | Shared Debian services, networking and UFI-TOOLS |
| `device/debian_device_e5/` | E5 desktop, keypad and defaults |
| `device/openwrt_device_common/` | Shared OpenWrt services, LuCI dashboard, staging tools, sounds and package dependencies |
| `device/openwrt_device_e5/`, `openwrt_device_t551m/`, `openwrt_device_m8/` | Per-device overlays, radio defaults and userspace adapters |
| `ci/infoscreen/` | Independent [infoscreen](https://github.com/Enceka/infoscreen) core, including the integrated mobile UI and screen services |
| `ci/infoscreen-plugins/` | Independent [infoscreen-plugins](https://github.com/Enceka/infoscreen-plugins), including Phone |
| `boot/`, `upstream/`, `kernel/` | Boot image tooling, mainline build entry points and legacy vendor kernel reference |
| `rootfs/`, `openwrt/`, `magisk/` | System builders, installers, flash bundles and Android-to-Linux module |
| `installer/` | Shared Windows and Apple Silicon desktop installer, backend, UI and offline tests |
| `tools/`, `docs/` | Synchronization, overlay composition, validation and device findings |

[device/manifest.json](device/manifest.json) declares overlay order:
`linux common → linux device → distro common → distro device`. Later files override earlier ones.
Radio modes and band defaults live in device overlays; common code reads them.
Installed `e5-*` and `t551m-*` names remain compatibility interfaces.

## Build

Use Docker, Python 3, LLVM/build tools and an ARM64 C compiler.
Device adaptation and offline root operations require Linux or WSL.
See the [OpenWrt guide](openwrt/README.md), [SD multiboot](openwrt/MULTIBOOT.md)
and [release workflow](docs/RELEASE.md) for installation and rollback details.

### E5 OpenWrt flash bundle

```sh
E5_RELEASE=1 bash upstream/build.sh
bash openwrt/build-modemmanager.sh
bash openwrt/build-bluez.sh
E5_MAINLINE=1 bash openwrt/make-flash-bundle.sh
```

The builder composes the OpenWrt overlay and stages the independent infoscreen and Phone repositories.
Outputs are under `out/openwrt/`. Hosted builds and publication run in [sprd-linux-devs/release](https://github.com/sprd-linux-devs/release). Release metadata records device submodule and screen revisions.
Generic images (`E5_DEVICE_FILES=0`) omit the receiving unit's firmware, calibration and Android runtime;
the installer extracts those files from that unit.

The common [package list](https://github.com/sprd-linux-devs/openwrt_device_common/blob/main/packages.list) includes `openssl-util`,
`curl`, `ca-bundle` and `msmtp`. `openssl-util` provides the `openssl` executable used by SMS email
encoding and DingTalk HMAC signatures. Builds exercise Base64/HMAC-SHA256, and release validation
rejects images without OpenSSL.

### E5 Debian

```sh
rootfs/pull-wcn-firmware.sh
rootfs/pull-audio-firmware.sh
rootfs/extract-android-vendor.sh
rootfs/build-rootfs-container.sh
```

Firmware extraction requires ADB and rooted Android on the target device.
Private overlay files go to `work/device-files/e5/overlay/`, merged after repository overlays during Debian builds.
See the [detailed E5 build reference](docs/E5-BUILD-REFERENCE.md) for modules, parameters and vendor runtime installation.

### Inspect or compose an overlay

```sh
python3 tools/device-layout.py check --system openwrt --model t551m
python3 tools/device-layout.py overlay --system openwrt --model t551m
python3 tools/device-layout.py overlay --system debian --model e5
```

Outputs default to `work/overlays/[system]-[model]/`. These are build artifacts, not source directories.
Use the composed directory for a manual Debian boot image's `--overlay` argument.
The composition tool only includes private files when passed `--private-overlay`; generic releases omit them.
Follow the separate T551M/M8 kernel and offline userspace procedures; E5 bundles are not substitutes.

## Add a device

1. Create `linux_device_[model]` and each required `[system]_device_[model]` repository in the organization.
   Include `profile.json`, `overlay/`, hardware adapters and a device README.
2. Add matching submodule paths and declare dependencies/order in `device/manifest.json`.
3. Put shared fixes in common repositories and model, radio, charger, audio and boot policy in device repositories.
4. Validate on the target before adding release builds or claiming support.

Commit and push a child repository before committing its updated gitlink in the parent.
Edit screen frontend/API/services in `ci/infoscreen`, and Phone in `ci/infoscreen-plugins`.
The old T551M `infoscreen/base` copy and source-anchor patch generator have been removed;
screen migration notes retain the source commit references. Existing public parent history is preserved.

## Install and use

Download a matching bundle from [Releases](https://github.com/sprd-linux-devs/release/releases).
Read its instructions and back up boot images and `misc` first. E5 boots Linux through `boot_b` while
Android remains on slot A. TF installation overwrites the existing first partition, or the whole card
when it has no partition table, and grows the filesystem to the selected target's capacity.
Rollback and persistent boot policies are device-specific.

The shared installer provides Windows EXE and Apple Silicon APP entries, internal-partition
installation and reinstall, resumable two-stage setup, SSH updates and Android uninstall options.
Read the packaged `START-HERE.md` and [installer guide](installer/GUIDE.md) before choosing a method.
The same ZIP supports TF installation through Magisk and extracted desktop installation.

E5's default LAN is `192.168.9.1`. OpenWrt provides LuCI/SSH, infoscreen, SMS and Phone;
Debian provides Phosh. Credentials and hotspot defaults are documented with the device/bundle;
change initial passwords before use. Device dumps, proprietary firmware, Android vendor components
and per-unit identity data are not committed.

LuCI and infoscreen share per-SIM APN selection, including PAP/CHAP. Multipart SMS fragments persist until a complete message can be displayed, notified and forwarded. `openwrt/build-profile-tf.py --profile e5|t551m|m8` packages an installer from an explicit matching kernel and sanitized base root; see [profile package inputs](docs/PROFILE-PACKAGES.zh-CN.md). Android installation backs up and verifies the B-slot boot chain before committing the system. Debian-origin package patches live in `device/debian_device_common/patches/`.

## License and sources

Scripts, tools and documentation use MIT; see [LICENSE](LICENSE).
Kernel/driver files retain their own GPL/SPDX licenses, upstream attribution and M8 source hash manifests.
Thanks to [mu300-linux](https://github.com/dikeckaan/mu300-linux) and the upstream projects.

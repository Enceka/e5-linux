# SD card updates and multiple systems

A first OpenWrt + Debian implementation was tested on the E5 on 2026-10-01.
The format-1 registry below is implemented; the full update/installation design
later in this document still has outstanding work.

## Tested format-1 registry

One kernel/initramfs in `boot_b` is shared by both systems. The card now has:

| Partition | Contents |
|---|---|
| `e5root` | Existing OpenWrt A (1025 MiB partition, 1 GiB image) |
| `e5boot` | 32 MiB ext4: registry and boot choices |
| `debian-a` | 4 GiB Debian A |
| `debian-b` | 4 GiB Debian B |
| `e5root2` | 1280 MiB OpenWrt B, allocated by the updater |

`e5boot` contains `format=1`, `kernel-release`, `default`, optional `next`,
and `systems/<system>/<slot>` files holding PARTUUIDs. `boot/init` checks the
kernel release, selects the system, then considers only that system's registered
partitions and matching `/etc/e5/sd-system`. Generation/trial selection is
unchanged within that group. A failed registered card selection does not fall
through into a writable userdata root. Metadata is mounted as `/mnt/e5-boot`.

`e5-os SYSTEM` persists the default on the card; `e5-os SYSTEM --once` writes
`next`, consumed by the initramfs without changing the default. Userdata stays
read-only for registered card systems. Unregistered cards retain the legacy
selection. The selector refuses an invalid ID, unknown system, missing
PARTUUID or competing selection request.

`rootfs/device-install-sd.sh` adds both 4 GiB Debian slots and the registry to
unallocated space of an existing SD OpenWrt installation, verifying each raw
image before registration. The original OpenWrt partition entry was byte-for-byte
unchanged. The OpenWrt updater validates the current slot's registration,
rejects foreign root identities and registers its own new slot after writing.

Before any card write, the installer runs `e5-gpt plan` for all three new
partitions: 32 MiB plus 4096 MiB twice. It checks both GPT copies, available
entries, partition overlaps and the same 1 MiB alignment/largest-gap allocation
that `add` uses. Each root must fit an unallocated gap; filesystem free space
does not count. Failure shows the requested size, largest aligned gap and total
remaining space, and leaves the card untouched. Separate gaps are supported.
Pass `--check` as the fourth argument to `device-install-sd.sh` to print the
plan and exit before writing. The image URL, raw SHA-256 and shared kernel
release remain its first three arguments.

Image writes stop at each 4096 MiB slot's boundary, reject even a one-byte
oversize image, report download/gzip/write errors separately and verify the
entire raw-image SHA-256 before mounting or registering it. Automated tests use
synthetic GPTs and small disposable image files; the existing multi-system card
was not erased to test these failure paths.

Device tests passed: both Debian desktops booted, persistent/one-shot choices,
one-shot Debian followed by ordinary reboot back to OpenWrt, OpenWrt update
into its B slot, full SHA-256 equality of both 4 GiB Debian partitions before
and after that update, and failed-trial-marker rollback within each system.
OpenWrt rollback ignored Debian's higher generation. The marker tests simulate
an unsuccessful trial; they do not inject a crash or power loss.

Remaining: an automated Debian updater, installer/flash-bundle migration for
already registered cards, recovery from interrupted registry/GPT writes and
actual failed-startup/power-cut tests. The installer currently refuses an
already registered card rather than migrating it. Kernel compatibility is an
exact release check, not a negotiated update across installed systems.

## Legacy unregistered-card updates

The card holds two OpenWrt roots, not two different operating systems:

| Update | Running root before the update | Destination |
|---|---|---|
| First | partition 1 | partition 2, created in free space |
| Second | partition 2 | partition 1 |
| Third | partition 1 | partition 2 |
| Later | the current root | the other root |

The updater selects another partition named `e5root*` with enough space,
preferring an unmarked root, a failed trial, or the oldest generation. It never
writes the mounted root. If no existing candidate is large enough, it creates a
new partition with 256 MiB of headroom. A larger future image can therefore
create a third partition; routine updates that fit alternate between the
existing two. Unrelated partition names are skipped, but matching `e5root*`
names alone do not distinguish different operating systems.

The image is written first, followed by the current system's configuration,
passwords, device firmware/vendor files, traffic records and installed info
screen apps. Packages manually added with `apk` are not carried over. The
destination receives a new `/etc/e5/sd-gen` and `/etc/e5/sd-trial=1`.

At boot the initramfs considers all roots marked `/etc/e5/sd-root` and chooses
the highest generation. It changes a pending trial to `0` before starting it.
OpenWrt's `e5-boot-ok` removes that file late in service startup. If the file
still contains `0` on the next boot, the root is skipped and the previous
generation boots. Confirmation currently means that `e5-boot-ok` ran; it is
not a check that every hardware service or the WAN is healthy.

The flash package also updates `boot_b`. This kernel/initramfs is shared by
both roots: rootfs rollback does not restore an older kernel. Configuration
changes made after an update do not propagate back into the older root.

## Multiple systems with independent updates

Use a stable system ID and an A/B pair for each installation, rather than a
global generation counter. Two OpenWrt installations count as separate systems
and get separate IDs just as OpenWrt and Debian would.

An example layout:

| Partition | Purpose |
|---|---|
| `e5boot` | Small ext4 partition: default system, one-shot selection, system registry |
| `openwrt-a`, `openwrt-b` | OpenWrt's current and previous roots |
| `debian-a`, `debian-b` | Debian's current and previous roots |
| Optional data partition | Explicitly shared user files; never automatically used for `/etc` |

The registry identifies partitions by PARTUUID, not by `mmcblk` number or label.
Each root also carries its system ID, slot ID and image compatibility metadata.
The updater checks that the registry, partition and image agree before writing;
an absent or conflicting identity stops the update. Legacy `e5root*` partitions
need an explicit migration into an OpenWrt pair, not automatic reassignment.

The rules are:

1. **Choose the system first, then its slot.** Default and one-shot choices live
   on the card, so selecting a system does not need a write to userdata. Android
   versus Linux remains the existing `e5-next-boot` A/B-slot choice.
2. **Update only that system's inactive slot.** Preserve configuration and apps
   from its own active slot. Never select another system as spare space. If both
   slots are too small, allocate a replacement for this system or stop with an
   explanation; do not overwrite another installation.
3. **Keep trials and rollback per system.** Failure of an OpenWrt update returns
   to the previous OpenWrt slot. It does not select Debian just because Debian has
   a larger generation number. Confirm a trial only after its defined startup
   checks pass; missing SIM/network coverage should not invalidate a usable root.
4. **Keep writable state separate.** `/etc`, passwords, SSH keys, package
   databases, traffic records, Bluetooth pairings and apps belong to each
   installation. Any shared media directory is opt-in.
5. **Commit boot metadata last.** Stage the image and configuration, flush them,
   then atomically replace the registry entry. Keep recoverable copies of the
   registry and verify GPT changes before announcing a new slot.

## The shared kernel

The agreed scope is one tested kernel/initramfs shared by all installed
userspaces; booting different kernels is not supported. Each root includes
modules matching that kernel. Ordinary system
updates should not silently replace the shared kernel; kernel updates need
compatibility checks against every registered system and a separate recovery
plan.

The current LK boots the Linux kernel from the shared `boot_b`, not from an SD
system's directory.

Independent roots also do not isolate physical device state: the modem's NV,
PMIC and charger state are shared hardware. System selection must leave hardware
in a known state, and switching systems is a reboot, not simultaneous operation.

Before claiming multi-system support, test that updates cannot target a foreign
system, each system retains its own configuration, power loss leaves a bootable
slot, and an unconfirmed trial rolls back within the selected system.

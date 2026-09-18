#!/usr/bin/env python3
"""Build an e5-linux boot image for the Rongyue E5 (Unisoc UMS9621, ums9158_1h10).

The E5 bootloader (LK) takes the *generic* ramdisk from boot.img and only falls
back to init_boot when boot.img's ramdisk_size is zero. Confirmed in the stock
bootloader log (uboot_log partition):

    bootimage: generic ramdisk size is 360840
    bootimage: generic ramdisk offset is 0x2c98000
    ...
    bootimage: generic ramdisk size is zero, maybe ramdisk in init_boot image side!
    init_bootimage: generic ramdisk size is 1907183

So the Linux kernel and the Linux initramfs both go into slot b's boot image and
init_boot_b / vendor_boot_b stay stock (LK also AVB-verifies init_boot).

The image reuses the stock boot image header, vbmeta blob and AVB footer byte for
byte; only kernel_size, ramdisk_size, the command line and the payload change.
AVB is not enforced on this unlocked device (the Magisk-patched boot_a boots with
a non-matching digest), but keeping the original descriptor avoids the
"invalid vbmeta header" failures seen when regenerating it.

Example:
  boot/build-boot-image.py \
    --stock-boot dumps/boot_b.img --misc-head dumps/misc-head.bin \
    --kernel out_linux/arch/arm64/boot/Image --modules out_linux-modules \
    --busybox work/busybox --out boot-linux-slotb.img
"""
import argparse
import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = 4096
MISC_BC_OFFSET = 0x800

# e5-linux reserves the top of boot_b for a persistent init log written by
# boot/init (survives a cold power cycle, unlike pstore). 56 MiB of the 64 MiB
# partition; the image must end before it.
PERSIST_LOG_OFFSET = 56 << 20

BOOT_CMDLINE = (
    b'console=tty0 console=ttyGS0,115200 loglevel=7 '
    b'selinux=0 androidboot.selinux=permissive enforcing=0 '
    b'panic=10 softlockup_panic=1 '
    # No 'fw_devlink=permissive' here on purpose.  The E5's USB controller
    # (64a00000.usb) lists the AW322xx charger (i2c:2-006a, which declares the
    # "vddvbus" regulator musb wants in host mode) among its devicetree
    # suppliers, and while 2-006a has no driver fw_devlink blocks musb before its
    # probe function is even entered:
    #
    #   platform 64a00000.usb: DEFERDBG: supplier 2-006a not ready
    #   probe of 64a00000.usb returned -517      (/sys/class/udc stays empty)
    #
    # Relaxing fw_devlink globally does unblock it, but it also lets every other
    # driver probe out of order and the kernel then dies before the initramfs
    # writes its first log line.  The charger driver exists in this tree
    # (drivers/power/supply/aw32257_charger.c, CONFIG_CHARGER_AW32257=m) and
    # registers a power supply named "aw322xx_charger" for compatible
    # "awinic,aw322xx_chg" -- loading it makes 2-006a probe, which is the actual
    # fix.  See boot/module-order.extra.
    # register ramoops from the command line so console/pmsg survive a boot that
    # dies before the DT-based device_initcall runs (artifacts_e5 diagnostics)
    b'ramoops.mem_address=0xfff80000 ramoops.mem_size=0x40000 '
    b'ramoops.record_size=0x8000 ramoops.console_size=0x8000 ramoops.pmsg_size=0x8000'
)


def cpio_record(name, data, mode, ino, rdev=(0, 0)):
    nb = name.encode() + b'\0'
    fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, rdev[0], rdev[1], len(nb), 0]
    h = b'070701' + b''.join(('%08x' % v).encode() for v in fields)
    x = h + nb
    x += b'\0' * ((-len(x)) % 4)
    x += data
    x += b'\0' * ((-len(data)) % 4)
    return x


def slot_info(prio, tries, successful):
    return (prio & 0xf) | ((tries & 0x7) << 4) | ((successful & 1) << 7)


def bootloader_control(misc_head):
    """Return (slot_a_block, slot_b_trial_block) from the live bootloader_control.

    Same 32-byte AOSP structure as mu300-linux: slot_suffix[4], magic 'BCAB',
    version, nb_slot, recovery_tries, merge_status, slot_info[4], ..., crc32.
    slot_info bit layout: priority (4) | tries_remaining (3) | successful_boot (1).
    """
    bc = misc_head[MISC_BC_OFFSET:MISC_BC_OFFSET + 32]
    if bc[4:8] != b'BCAB':
        sys.exit('misc head has no bootloader_control magic at 0x800')
    if zlib.crc32(bc[:28]) != struct.unpack('<I', bc[28:])[0]:
        sys.exit('misc bootloader_control CRC mismatch')

    def with_slots(suffix, a, b):
        x = bytearray(bc)
        x[0:4] = suffix
        x[12] = a
        x[14] = b
        x[28:32] = struct.pack('<I', zlib.crc32(bytes(x[:28])))
        return bytes(x)

    a_info, b_info = bc[12], bc[14]
    a_prio = a_info & 0xf
    # slot a: what the device runs today, restored by init when the Linux trial fails
    slot_a = with_slots(b'_a\0\0', slot_info(a_prio, 1, 1), b_info)
    # slot b one-shot trial: a keeps a slightly lower priority and stays marked
    # successful, b gets the top priority with tries=2. LK decrements to 1 on the
    # next boot; a Linux boot that never succeeds therefore rolls back to a.
    slot_b = with_slots(b'_b\0\0', slot_info((a_prio - 1) & 0xf, 1, 1), slot_info(0xf, 2, 0))
    return slot_a, slot_b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--stock-boot', required=True, type=Path,
                    help='stock boot image of the target slot (64 MiB, header v4, ramdisk_size 0)')
    ap.add_argument('--misc-head', required=True, type=Path, help='first 4 KiB of the misc partition')
    ap.add_argument('--kernel', required=True, type=Path, help='arm64 Image built by kernel/build-linux.sh')
    ap.add_argument('--modules', type=Path, help='flat directory with the built .ko files')
    ap.add_argument('--module-order', type=Path, default=HERE / 'module-order.txt')
    ap.add_argument('--init', type=Path, default=HERE / 'init')
    ap.add_argument('--busybox', required=True, type=Path, help='static arm64 busybox')
    ap.add_argument('--overlay', type=Path,
                    help='rootfs overlay tree to embed in the initramfs as e5-overlay/ '
                         '(firmware, factory data, systemd units); boot/init copies it into '
                         'the initramfs root before the module pass and into the real root '
                         'before switch_root')
    ap.add_argument('--cmdline', default=BOOT_CMDLINE.decode())
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()

    base = a.stock_boot.read_bytes()
    if base[:8] != b'ANDROID!' or struct.unpack_from('<I', base, 40)[0] != 4:
        sys.exit('stock boot is not an Android boot image header v4')
    ks0, rs0 = struct.unpack_from('<II', base, 8)
    print('base: kernel_size=0x%x ramdisk_size=0x%x' % (ks0, rs0))
    slot_a_bc, slot_b_bc = bootloader_control(a.misc_head.read_bytes())
    print('misc: slot_a=%s slot_b_trial=%s' % (slot_a_bc.hex(), slot_b_bc.hex()))

    cmdline = a.cmdline.encode()
    if len(cmdline) >= 1536:
        sys.exit('command line too long for a boot header v4 (max 1535 bytes)')

    files = {
        'init': (a.init.read_bytes(), stat.S_IFREG | 0o755),
        'bin/busybox': (a.busybox.read_bytes(), stat.S_IFREG | 0o755),
        'bin/sh': (b'busybox', stat.S_IFLNK | 0o777),
        'etc/misc-bc-slot-a.bin': (slot_a_bc, stat.S_IFREG | 0o644),
        'etc/misc-bc-slot-b-trial.bin': (slot_b_bc, stat.S_IFREG | 0o644),
    }
    dirs = {'bin', 'sbin', 'etc', 'proc', 'sys', 'dev', 'run', 'tmp', 'root', 'config', 'linux-modules'}

    order = []
    if a.module_order.exists():
        order = a.module_order.read_text().split()
        files['etc/module-order'] = (a.module_order.read_bytes(), stat.S_IFREG | 0o644)
    for name in order:
        ko = a.modules / name if a.modules else None
        if ko is None or not ko.exists():
            sys.exit('missing module %s (looked in %s)' % (name, a.modules))
        files['linux-modules/' + name] = (ko.read_bytes(), stat.S_IFREG | 0o644)

    overlay_files = 0
    if a.overlay and a.overlay.is_dir():
        dirs.add('e5-overlay')
        for path in sorted(a.overlay.rglob('*')):
            if any(part.startswith('.') for part in path.relative_to(a.overlay).parts):
                continue
            name = 'e5-overlay/' + str(path.relative_to(a.overlay))
            if path.is_dir():
                dirs.add(name)
            elif path.is_file():
                # Never ship a file the session's user cannot read: the build
                # host's umask has nothing to do with what the device needs, and
                # a 0600 /etc/phosh/phoc.ini silently cost the e5 user its whole
                # session (phoc is started with an explicit -C and exits when it
                # cannot read the file).  Executables keep their bits; everything
                # else is at least a+r.
                mode = path.stat().st_mode & 0o777
                mode |= 0o055 if mode & 0o100 else 0o044
                files[name] = (path.read_bytes(), stat.S_IFREG | mode)
                overlay_files += 1
    print('overlay: %d files from %s' % (overlay_files, a.overlay))

    cpio = bytearray()
    ino = 1
    for d in sorted(dirs, key=lambda x: (x.count('/'), x)):
        cpio += cpio_record(d, b'', stat.S_IFDIR | 0o755, ino)
        ino += 1
    for name, (data, mode) in files.items():
        cpio += cpio_record(name, data, mode, ino)
        ino += 1
    # the kernel opens /dev/console before running /init
    cpio += cpio_record('dev/console', b'', stat.S_IFCHR | 0o600, ino, (5, 1))
    ino += 1
    cpio += cpio_record('TRAILER!!!', b'', 0, ino)

    # LK decodes the generic ramdisk as an LZ4 *legacy* frame (magic 02 21 4c 18);
    # that is what the stock and Magisk boot images on this device use.
    ram = subprocess.run(['lz4', '-l', '-12', '-c'], input=bytes(cpio), capture_output=True, check=True).stdout
    assert ram[:4] == bytes.fromhex('02214c18'), 'not a legacy lz4 frame'
    print('initramfs: cpio %d bytes -> lz4 legacy %d bytes, %d modules'
          % (len(cpio), len(ram), len(order)))

    kern = a.kernel.read_bytes()
    hdr = bytearray(base[:PAGE])
    struct.pack_into('<I', hdr, 8, len(kern))
    struct.pack_into('<I', hdr, 12, len(ram))
    hdr[44:44 + 1536] = cmdline + b'\0' * (1536 - len(cmdline))
    struct.pack_into('<I', hdr, 1580, 0)  # signature_size
    body = bytes(hdr) + kern + b'\0' * ((-len(kern)) % PAGE) + ram
    body += b'\0' * ((-len(body)) % PAGE)
    original_size = len(body)

    avb_off, avb_size = struct.unpack_from('>QQ', base, len(base) - 44)
    if avb_off + avb_size > len(base) - 64:
        sys.exit('base image has no usable vbmeta blob (offset 0x%x size 0x%x)' % (avb_off, avb_size))
    body += base[avb_off:avb_off + avb_size]
    if len(body) > PERSIST_LOG_OFFSET:
        sys.exit('image data (%d bytes) overlaps the persistent log area at %d'
                 % (len(body), PERSIST_LOG_OFFSET))
    body += b'\0' * (len(base) - 64 - len(body))
    footer = bytearray(base[-64:])
    struct.pack_into('>QQQ', footer, 12, original_size, original_size, avb_size)
    image = body + bytes(footer)
    assert len(image) == len(base)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(image)
    a.out.with_suffix('.misc-slot-b-trial.bin').write_bytes(slot_b_bc)
    manifest = {
        'image': a.out.name,
        'sha256': hashlib.sha256(image).hexdigest(),
        'sha256_head56m': hashlib.sha256(image[:PERSIST_LOG_OFFSET]).hexdigest(),
        'kernel_sha256': hashlib.sha256(kern).hexdigest(),
        'kernel_size': len(kern),
        'ramdisk_size': len(ram),
        'modules': len(order),
        'cmdline': a.cmdline,
        'misc_slot_a_hex': slot_a_bc.hex(),
        'misc_slot_b_trial_hex': slot_b_bc.hex(),
        'overlay_files': overlay_files,
        'persist_log_offset': PERSIST_LOG_OFFSET,
    }
    a.out.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

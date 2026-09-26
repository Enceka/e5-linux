#!/usr/bin/env python3
"""Read-only audit of what the device actually runs, against this checkout.

Why this exists
---------------
Only three things decide what a booted E5 runs, and none of them is "the checkout":

  * the flashed boot image.  ``boot/build-boot-image.py`` bakes ``rootfs/overlay``
    into the initramfs as ``e5-overlay/``, and ``boot/init`` copies every one of
    those files over ``/newroot`` on *every* boot.  An old image therefore
    silently restores old files over ``/etc`` for as long as it is flashed --
    the ``sddm.conf.d/10-e5.conf`` that still said ``plasma-mobile.desktop``
    (and so kept phosh from being the session) is the classic case, and
    docs/STATUS.md keeps them under "Traps found the hard way".
  * ``/data/e5linux/rootfs.ext4``, which is where the files the image *cannot*
    carry end up: anything under a dot-directory (``.config``, ``.keep``) and
    every ``*.wants/`` link, because the image builder packs plain files only.
  * the enable lists in ``rootfs/configure-rootfs.sh`` and
    ``rootfs/device-finalize.sh``, which turn units on when the rootfs is built.

This script compares all three against the tree, in both directions, and never
writes: on Android it mounts ``/data/e5linux/rootfs.ext4`` read-only through a
loop device and unmounts it again; nothing is pushed, installed or rebooted.

usage:
  tools/verify-device.py                    # device on Android, adb + su
  tools/verify-device.py --image boot-linux-slotb.img --repo .
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parent.parent
DEV_ROOTFS = '/data/e5linux/rootfs.ext4'
DEV_MNT = '/mnt/e5-verify'
DEV_PATHS = '/data/local/tmp/e5-verify-paths.txt'

# Directories the overlay owns.  A file here that the tree does not have is a
# leftover from an earlier design: the overlay only ever adds, so nothing on the
# device removes it again.
MANAGED_DIRS = ['opt/e5', 'usr/local/sbin', 'etc/e5', 'etc/e5linux', 'etc/phosh',
                'home/e5/.config/autostart']

# The image builder skips any path with a dot component, so these can only reach
# a device through rootfs.ext4 -- worth saying out loud when one differs.
DOT_EXCLUDED = re.compile(r'(^|/)\.[^/]')

# macOS droppings: gitignored, skipped by the builder as a dot-path anyway, and
# recreated by Finder the moment anyone opens the directory.  Not a device fault.
JUNK = {'.DS_Store'}


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def adb(cmd):
    """Run cmd as root on the device (Android mode)."""
    return sh("adb exec-out su -c '%s'" % cmd.replace("'", "'\\''"))


# --------------------------------------------------------------- boot image


def lz4_decompress(blob):
    """The ramdisk is an LZ4 *legacy* frame (0x184C2102), not gzip."""
    magic = bytes.fromhex('02214c18')
    at = blob.find(magic)
    if at < 0:
        return None
    proc = subprocess.run(['lz4', '-d', '-c'], input=blob[at:], capture_output=True)
    # The frame is followed by the rest of the image (the log area, the AVB footer),
    # which lz4 reports as trailing garbage and exits non-zero on.  The stream itself
    # is complete by then, so judge the result by whether anything came out.
    if not proc.stdout:
        return None
    return proc.stdout


def cpio_names(blob):
    """(name, is_dir) for every entry of a newc cpio archive (what the builder writes).

    The archive carries the directories too, and a directory name is not a file the
    overlay applies, so the two have to stay apart: counting them together made the
    image look like it had 104 overlay files where the tree has 70.
    """
    names, off = [], 0
    while off + 110 <= len(blob) and blob[off:off + 6] == b'070701':
        fields = [int(blob[off + 6 + i * 8:off + 14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = blob[off + 110:off + 110 + namesize - 1].decode('utf-8', 'replace')
        names.append((name, (mode & 0o170000) == 0o040000))
        off += 110 + namesize
        off += (-off) % 4
        off += size
        off += (-off) % 4
        if name == 'TRAILER!!!':
            break
    return names


def image_overlay(img):
    """The e5-overlay/ file names inside a boot image (None if it carries none)."""
    blob = Path(img).read_bytes()
    ram = lz4_decompress(blob)
    if ram is None:
        return None
    return set(n[len('e5-overlay/'):] for n, is_dir in cpio_names(ram)
               if n.startswith('e5-overlay/') and not is_dir)


def tree_overlay(root):
    """What the builder would pack: files only, no dot components anywhere."""
    out = set()
    for path in Path(root).rglob('*'):
        rel = path.relative_to(root)
        if path.is_file() and path.name not in JUNK and not any(p.startswith('.') for p in rel.parts):
            out.add(str(rel))
    return out


def tree_overlay_all(root):
    """Everything the overlay would put on a device, dot-directories included."""
    return set(str(p.relative_to(root)) for p in Path(root).rglob('*')
               if p.is_file() and p.name not in JUNK)


# ------------------------------------------------------------------- device


class Device:
    """A device with /data/e5linux/rootfs.ext4 mounted read-only."""

    def __init__(self):
        self.mounted = False
        self.notes = []

    def rooted(self):
        out = sh('adb devices').stdout
        return 'device' in out.replace('List of devices attached', '')

    def mount(self):
        if not self.rooted():
            sys.exit('no adb device: the audit needs the device in Android (adb + su)')
        out = adb('mkdir -p %s; F=$(losetup -f); losetup $F %s && mount -t ext4 -o ro $F %s '
                  '&& echo LOOP-OK' % (DEV_MNT, DEV_ROOTFS, DEV_MNT))
        self.mounted = 'LOOP-OK' in out.stdout
        if not self.mounted:
            sys.exit('could not mount %s read-only: %s' % (DEV_ROOTFS, out.stdout + out.stderr))

    def umount(self):
        if self.mounted:
            adb('umount %s 2>/dev/null; for l in $(losetup -a | grep rootfs.ext4 | cut -d: -f1); '
                'do losetup -d $l; done' % DEV_MNT)
            self.mounted = False

    def file(self, rel):
        return adb('cat %s/%s 2>/dev/null' % (DEV_MNT, rel)).stdout

    def shas(self, rels):
        """sha256 of every path, in one round trip; missing files come back as '-'."""
        with tempfile.NamedTemporaryFile('w', suffix='.txt') as fh:
            fh.write('\n'.join(rels) + '\n')
            fh.flush()
            sh('adb push %s %s' % (fh.name, DEV_PATHS))
        script = ('cd %s && while IFS= read -r f; do ' % DEV_MNT +
                  'if [ -f "$f" ]; then printf \'%%s  %%s\\n\' "$(sha256sum "$f" | cut -d" " -f1)" "$f"; '
                  'else printf \'MISSING  %%s\\n\' "$f"; fi; done < %s' % DEV_PATHS)
        out = adb(script).stdout
        found = {}
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            sha, _, name = line.partition('  ')
            found[name.lstrip('./')] = sha
        return found

    def find(self, rel):
        """Files under a directory of the mounted root, as tree-relative paths."""
        out = adb('cd %s && find %s -type f -o -type l 2>/dev/null' % (DEV_MNT, rel)).stdout
        return set(p.strip().lstrip('./') for p in out.splitlines() if p.strip())

    def wants(self):
        out = adb('cd %s && for d in etc/systemd/system/*.wants; do '
                  '[ -d "$d" ] || continue; for l in "$d"/*; do basename "$l"; done; done'
                  % DEV_MNT).stdout
        return set(p.strip() for p in out.splitlines() if p.strip())

    def dangling(self):
        """Enable links whose target unit is not there.

        Two kinds of target exist: a relative one (``../e5-atd.service``), which the
        kernel resolves next to the link and plain ``-e`` gets right, and an absolute
        one (``/lib/systemd/system/NetworkManager.service``), which has to be resolved
        inside the mount -- from the running Android root *every* packaged unit would
        look broken.
        """
        out = adb('cd %s && root=$(pwd) && for d in etc/systemd/system/*.wants; do '
                  '[ -d "$d" ] || continue; for l in "$d"/*; do '
                  '[ -e "$l" ] && continue; t=$(readlink "$l" 2>/dev/null); '
                  'case "$t" in /*) [ -e "$root$t" ] || echo "$l" ;; *) echo "$l" ;; esac; '
                  'done; done' % DEV_MNT).stdout
        return set(p.strip().lstrip('./') for p in out.splitlines() if p.strip())


# --------------------------------------------------------------------- main


def imagenames(repo, image):
    manifest = Path(str(image).replace('.img', '.json'))
    if not manifest.exists():
        return None, None
    meta = json.loads(manifest.read_text())
    # the device reports its own boot_b head; compare with the local file's
    out = adb('dd if=/dev/block/by-name/boot_b bs=1M count=%d 2>/dev/null | sha256sum'
              % (meta['persist_log_offset'] // 1048576)).stdout
    dev_head = out.split()[0] if out.split() else '<nothing>'
    return meta, dev_head


def enable_lists(repo):
    """The units the build scripts enable, as one set."""
    units = set()
    for name in ('rootfs/configure-rootfs.sh', 'rootfs/device-finalize.sh'):
        text = (repo / name).read_text()
        for block in re.findall(r'for s in (.*?); do', text, re.S):
            for word in re.split(r'[\s\\]+', block):
                if word and not word.startswith('#'):
                    units.add(word if word.endswith('.service') else word + '.service')
    return units


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', type=Path, default=REPO_DEFAULT)
    ap.add_argument('--image', type=Path, default=REPO_DEFAULT / 'boot-linux-slotb.img')
    a = ap.parse_args()
    overlay = a.repo / 'rootfs/overlay'
    problems = 0

    dev = Device()
    dev.mount()
    try:
        # ---- 1. which boot image is flashed, and what it carries
        print('== boot image')
        meta, dev_head = imagenames(a.repo, a.image)
        if meta is None:
            print('   %s has no manifest; skipping' % a.image)
        else:
            same = dev_head == meta['sha256_head56m']
            print('   device boot_b head56m %s local %s  %s'
                  % (dev_head[:16], meta['sha256_head56m'][:16],
                     'SAME -- auditing the image the device actually boots' if same else 'DIFFERENT!!'))
            problems += 0 if same else 1
        embedded = image_overlay(a.image)
        if embedded is None:
            print('   %s: no LZ4 legacy ramdisk found' % a.image)
        else:
            wants = tree_overlay(overlay)
            missing = sorted(wants - embedded)
            print('   overlay in the image: %d, the builder would pack: %d' % (len(embedded), len(wants)))
            for f in missing:
                print('   NOT IN THE IMAGE (a reboot restores the old copy, or nothing): %s' % f)
            problems += len(missing)
            skipped = sorted(f for f in tree_overlay_all(overlay) if DOT_EXCLUDED.search(f))
            for f in skipped:
                print('   dot-path, never in the image (device gets it from rootfs.ext4 only): %s' % f)

        # ---- 2. every overlay file, as the device has it
        print('== overlay files in /data/e5linux/rootfs.ext4')
        rels = sorted(tree_overlay_all(overlay))
        got = dev.shas(rels)
        for rel in rels:
            want = hashlib.sha256((overlay / rel).read_bytes()).hexdigest()
            have = got.get(rel)
            if have == want:
                continue
            problems += 1
            state = 'MISSING on the device' if have in (None, '-') or have == 'MISSING' else 'DIFFERENT'
            print('   %-9s %s' % (state, rel))
        print('   %d files checked, %d wrong' % (len(rels), problems - (0 if meta is None else 0)))

        # ---- 3. what the device has that the tree does not (old designs survive)
        print('== leftovers on the device (in directories the overlay owns)')
        for d in MANAGED_DIRS:
            dev_files = dev.find(d)
            tree_files = set(str(p.relative_to(overlay)) for p in (overlay / d).rglob('*')) if (overlay / d).exists() else set()
            for extra in sorted(dev_files - tree_files):
                print('   only on the device: %s' % extra)
                problems += 1
        # the same for /etc/systemd/system: a unit file from a design that is gone,
        # or an enable link pointing at a unit that no longer exists, is a failed or
        # noisy boot rather than a silent one.
        dev_units = set(f for f in dev.find('etc/systemd/system') if '.wants/' not in f)
        tree_units = set(str(p.relative_to(overlay)) for p in (overlay / 'etc/systemd/system').rglob('*'))
        # Only our own namespace can be a leftover of ours: /etc/systemd/system also holds
        # the aliases `systemctl enable` makes for Debian's own units (dbus-org.bluez,
        # display-manager, smartd), and dropping those would be dropping the distro.
        stale = [f for f in sorted(dev_units - tree_units) if os.path.basename(f).startswith('e5-')]
        links = sorted(dev.dangling())
        for extra in stale:
            print('   only on the device: %s' % extra)
            problems += 1
        for link in links:
            print('   enable link to a unit that does not exist: %s' % link)
            problems += 1
        if not stale and not links:
            print('   none')

        # ---- 4. units: enabled by the build, linked here, or neither
        print('== units')
        wanted = dev.wants()
        enabled = enable_lists(a.repo)
        known = set(p.name for p in (overlay / 'etc/systemd/system').glob('*.service'))
        known |= {'NetworkManager.service', 'sddm.service', 'serial-getty@ttyGS0.service'}
        # Some units are enabled by nobody on purpose: a drop-in pulls them in, because
        # the overlay cannot carry a *.wants/ link (docs/FINDINGS.md 6.1 and 6.4).  Read
        # those once and match against their text.
        drops = ['NetworkManager.service.d/50-e5-networkd.conf',
                 'NetworkManager.service.d/20-e5-shutdown-timeout.conf',
                 'e5-zram.service.d/10-e5-4g.conf']
        drop_text = ''.join(dev.file('etc/systemd/system/' + d) for d in drops)
        pulled = set(u for u in known if u in drop_text)
        for unit in sorted(known):
            state = ('in a .wants/ link' if unit in wanted else
                     'pulled in by a drop-in' if unit in pulled else
                     'enabled by the build scripts' if unit in enabled else
                     'NOT ENABLED anywhere')
            print('   %-34s %s' % (unit, state))
            problems += 0 if state != 'NOT ENABLED anywhere' else 1
        # the other direction: a unit the build scripts enable, but that nothing on this
        # device links or pulls in -- which is what an install predating the change is
        for unit in sorted(u for u in enabled if u.startswith('e5-')):
            if unit not in wanted and unit not in pulled:
                print('   %-34s enabled by the build scripts, but nothing on the device pulls it in' % unit)
                problems += 1
    finally:
        dev.umount()

    print('\n%d problem(s)' % problems)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())

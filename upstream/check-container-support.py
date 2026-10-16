#!/usr/bin/env python3
"""Check the built KVM/container kernel, its modules and their provenance.

Adapted from mu300-linux's check-container-support.py for the E5 output layout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import tarfile

BUILTIN = '''VIRTUALIZATION KVM IKCONFIG IKCONFIG_PROC CGROUPS MEMCG BLK_CGROUP
CGROUP_SCHED CGROUP_PIDS CPUSETS CGROUP_BPF CFS_BANDWIDTH BLK_DEV_THROTTLING
NAMESPACES UTS_NS IPC_NS USER_NS PID_NS NET_NS SECCOMP SECCOMP_FILTER
POSIX_MQUEUE VETH BRIDGE TUN OVERLAY_FS NF_CONNTRACK NF_NAT NF_TABLES NFT_COMPAT
NETFILTER_XT_MATCH_CONNTRACK NETFILTER_XT_TARGET_MASQUERADE'''.split()
MODULES = {
    'VHOST_NET': 'vhost_net', 'VSOCKETS': 'vsock', 'VHOST_VSOCK': 'vhost_vsock',
    'BRIDGE_NETFILTER': 'br_netfilter', 'NETFILTER_XT_MATCH_ADDRTYPE': 'xt_addrtype',
    'NETFILTER_XT_MATCH_IPVS': 'xt_ipvs', 'NETFILTER_XT_MARK': 'xt_mark',
    'NETFILTER_XT_NAT': 'xt_nat',
    'NETFILTER_XT_MATCH_COMMENT': 'xt_comment', 'NETFILTER_XT_MATCH_MULTIPORT': 'xt_multiport',
    'IP_VS': 'ip_vs', 'IP_VS_RR': 'ip_vs_rr', 'IP_VS_WRR': 'ip_vs_wrr',
    'IP_VS_SH': 'ip_vs_sh', 'VXLAN': 'vxlan', 'IPVLAN': 'ipvlan',
    'MACVTAP': 'macvtap', 'DUMMY': 'dummy', 'BINFMT_MISC': 'binfmt_misc', 'FUSE_FS': 'fuse',
}

# PR #228: optional features must ship their dependency modules too.
MODULES.update({
    'VIRTIO_PCI': 'virtio_pci',
    'VIRTIO_NET': 'virtio_net',
    'VIRTIO_BLK': 'virtio_blk',
    'VIRTIO_CONSOLE': 'virtio_console',
    'HW_RANDOM_VIRTIO': 'virtio_rng',
    'VIRTIO_BALLOON': 'virtio_balloon',
    'VIRTIO_INPUT': 'virtio_input',
    'VIRTIO_FS': 'virtiofs',
    'VIRTIO_VSOCKETS': 'vmw_vsock_virtio_transport',
    'NET_9P': '9pnet',
    'NET_9P_VIRTIO': '9pnet_virtio',
    '9P_FS': '9p',
    'VHOST_SCSI': 'vhost_scsi',
    'USBIP_CORE': 'usbip_core',
    'USBIP_HOST': 'usbip_host',
    'USBIP_VHCI_HCD': 'vhci_hcd',
    'USB_VIDEO_CLASS': 'uvcvideo',
    'USB_NET_AX8817X': 'asix',
    'NFS_FS': 'nfs',
    'NFSD': 'nfsd',
    'CIFS': 'cifs',
    'XFS_FS': 'xfs',
    'DM_CACHE': 'dm_cache',
    'DM_WRITECACHE': 'dm_writecache',
    'DM_MULTIPATH': 'dm_multipath',
    'DM_INTEGRITY': 'dm_integrity',
    'DM_MIRROR': 'dm_mirror',
    'MD_RAID456': 'raid456',
})


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def config_check(path):
    config = dict(line.split('=', 1) for line in path.read_text().splitlines()
                  if line.startswith('CONFIG_') and '=' in line)
    for key in BUILTIN:
        if config.get('CONFIG_' + key) != 'y':
            raise ValueError('Built kernel missing CONFIG_' + key + '=y')
    for key in MODULES:
        if config.get('CONFIG_' + key) not in ('y', 'm'):
            raise ValueError('Built kernel missing CONFIG_' + key)
    runpy.run_path(str(Path(__file__).with_name('audit-bundle.py')))['expanded_check'](config, Path(__file__).with_name('e5-mainline.config'))
    return config


def check(out, record=False):
    config = config_check(out / 'config')
    release = (out / 'kernel.release').read_text().strip()
    version = re.search(rb'Linux version ([^\s\x00]+)', (out / 'Image').read_bytes())
    if not version or version[1].decode('ascii') != release:
        raise ValueError('Image and kernel.release disagree')
    if record:
        # Canonical modules_install archive, before flat staging/aliases.
        with tarfile.open(out / 'modules.tar') as archive:
            inventory = sorted(Path(m.name).name for m in archive if m.isfile() and m.name.endswith('.ko'))
        (out / 'modules.in-tree').write_text('\n'.join(inventory) + '\n')
    runpy.run_path(str(Path(__file__).with_name('audit-bundle.py')))['audit'](out, 'config')
    files = list((out / 'modules').glob('*.ko'))
    normalized = {p.name.replace('-', '_'): p for p in files}
    if not files or len(normalized) != len(files):
        raise ValueError('Empty module set or colliding module names')
    for path in files:
        vermagic = re.search(rb'vermagic=([^\s\x00]+)', path.read_bytes())
        if not vermagic or vermagic[1] != version[1]:
            raise ValueError('Module vermagic mismatch: ' + path.name)
    for key, name in MODULES.items():
        if config['CONFIG_' + key] == 'm' and name + '.ko' not in normalized:
            raise ValueError('Configured module not packaged: ' + name)
    names = ['Image', 'Image.lk', 'config', 'kernel.release', 'modules.builtin',
             'modules.builtin.modinfo', 'modules.tar', 'modules.in-tree'] + sorted('modules/' + p.name for p in files)
    hashes = {name: digest(out / name) for name in names}
    if not all((out / name).stat().st_size for name in names):
        raise ValueError('Empty build artifact')
    manifest = out / 'container-support.json'
    expected = {'release': release, 'sha256': hashes}
    if not record and json.loads(manifest.read_text()) != expected:
        raise ValueError('Kernel/module artifacts differ from the recorded build')
    # Compare the flat boot input with modules_install's canonical tree before
    # the OpenWrt stager flattens it and adds the existing audio/modem aliases.
    seen = set()
    with tarfile.open(out / 'modules.tar') as tar:
        for item in tar:
            if not item.name.endswith('.ko'):
                continue
            name = Path(item.name).name
            if not item.isfile() or name in seen or not item.name.startswith('lib/modules/' + release + '/'):
                raise ValueError('Invalid module archive member: ' + item.name)
            if hashlib.sha256(tar.extractfile(item).read()).hexdigest() != hashes.get('modules/' + name):
                raise ValueError('Root module differs from boot build: ' + name)
            seen.add(name)
    if seen != {p.name for p in files}:
        raise ValueError('Root module archive is incomplete')
    if record:
        manifest.write_text(json.dumps(expected, indent=2) + '\n')
    return release


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    ap.add_argument('--record', action='store_true', help='Only during a successful kernel+modules build')
    ap.add_argument('--config-only', action='store_true')
    args = ap.parse_args()
    if args.config_only:
        config_check(args.output)
    else:
        check(args.output, args.record)
    print('KVM/container build artifacts verified')

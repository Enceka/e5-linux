#!/usr/bin/env python3
"""Static checks of the Landscape integration, without Docker or a device.

What this covers (all of it is what can break silently between a kernel
option, the OpenWrt package list and the procd service):

  * every kernel option Landscape's requirements page lists is in
    upstream/e5-mainline.config, and the three it requires off stay off;
  * openwrt/build-rootfs.sh installs the pinned Landscape assets only for
    E5_LANDSCAPE=1, verifies their SHA-256, and copies the daemon, the
    redirect handler, the web UI and the service into the image;
  * the landscape service starts the static binary with the config dir, the
    web root and the ports the overlay ships;
  * 99-landscape turns OpenWrt's dnsmasq/odhcpd off (Landscape owns :53/:67)
    and only in a landscape image.
"""
import re
import unittest
from pathlib import Path

TOP = Path(__file__).resolve().parents[2]
CONFIG = TOP / 'upstream/e5-mainline.config'
BUILD = TOP / 'openwrt/build-rootfs.sh'
SERVICE = TOP / 'openwrt/landscape/etc/init.d/landscape-router'
DEFAULTS = TOP / 'openwrt/landscape/etc/uci-defaults/99-landscape'
TOML = TOP / 'openwrt/landscape/etc/landscape-router/landscape.toml'

# landscape.whileaway.dev/zh/intro/requirements, verbatim where the kernel
# Kconfig does not derive it (BPF_JIT_DEFAULT_ON and IPV6_SEG6_BPF are
# defaults of ARCH_WANT_DEFAULT_BPF_JIT and IPV6_SEG6_LWTUNNEL on arm64).
REQUIRED_ON = [
    'CONFIG_BPF_SYSCALL=y',
    'CONFIG_BPF_JIT=y',
    'CONFIG_BPF_JIT_DEFAULT_ON',       # derived; checked in the compiled config
    'CONFIG_BPF_UNPRIV_DEFAULT_OFF=y',
    'CONFIG_BPF_LSM=y',
    'CONFIG_BPF_EVENTS=y',
    'CONFIG_BPF_STREAM_PARSER=y',
    'CONFIG_CGROUP_BPF=y',
    'CONFIG_LWTUNNEL_BPF=y',
    'CONFIG_NETFILTER_BPF_LINK=y',
    'CONFIG_IPV6_SEG6_LWTUNNEL=y',
    'CONFIG_IPV6_SEG6_BPF',            # derived; checked in the compiled config
    'CONFIG_NETFILTER_XT_MATCH_BPF=m',
    'CONFIG_NET_CLS_BPF=y',
    'CONFIG_NET_ACT_BPF=m',
    'CONFIG_DEBUG_INFO_BTF=y',
    'CONFIG_DEBUG_INFO_BTF_MODULES=y',
]
REQUIRED_OFF = [
    'CONFIG_BPF_JIT_ALWAYS_ON',
    'CONFIG_BPF_PRELOAD',
    'CONFIG_HID_BPF',
]
DERIVED = {'CONFIG_BPF_JIT_DEFAULT_ON', 'CONFIG_IPV6_SEG6_BPF'}


class KernelConfig(unittest.TestCase):
    def setUp(self):
        self.lines = {line.strip() for line in CONFIG.read_text().splitlines()}

    def test_required_options_are_named(self):
        missing = [o for o in REQUIRED_ON
                   if o not in DERIVED and o not in self.lines]
        self.assertEqual(missing, [])

    def test_required_options_are_off(self):
        # `# ... is not set` is what kconfig writes and what the Landscape
        # checklist and the workflow grep for; `=n` in the fragment becomes
        # `# ... is not set` but would fail the workflow's own check.
        for option in REQUIRED_OFF:
            self.assertFalse(any(line in (f'{option}=y', f'{option}=m') for line in self.lines),
                             f'{option} must not be built in')
            self.assertIn(f'# {option} is not set', self.lines)
            self.assertNotIn(f'{option}=n', self.lines)

    def test_btf_needs_dwarf(self):
        # BTF without debug info is empty: the Build ID Landscape reads would
        # not be there either.
        self.assertIn('CONFIG_DEBUG_INFO_BTF=y', self.lines)
        self.assertTrue(any(line.startswith('CONFIG_DEBUG_INFO_DWARF') for line in self.lines))


class Build(unittest.TestCase):
    def setUp(self):
        self.text = BUILD.read_text()

    def test_assets_are_pinned_and_hashed(self):
        self.assertIn('LANDSCAPE_VER=${E5_LANDSCAPE_VER:-0.26.3}', self.text)
        for name in ('landscape-webserver-aarch64-static',
                     'redirect_pkg_handler-aarch64-static', 'static.zip'):
            self.assertIn(name, self.text)
        self.assertIn('checksum mismatch for $f', self.text)

    def test_install_is_gated_on_the_flag(self):
        self.assertIn('LANDSCAPE=${E5_LANDSCAPE:-0}', self.text)
        self.assertIn('E5_LANDSCAPE=1 requires E5_ROOT_MODULES', self.text)

    def test_image_carries_the_landscape_files(self):
        for name in ('usr/sbin/landscape-webserver', 'etc/landscape-router/static',
                     'etc/init.d/landscape-router'):
            self.assertIn(name, self.text)
        # the service/config tree is staged next to the root modules and copied
        # over the image root, so it stays out of the Debian/OpenWrt shared tree
        self.assertIn('openwrt/landscape', self.text)
        self.assertIn('cp -a /in/landscape-root/. $R/', self.text)

    def test_ebpf_packages_use_the_feed_names(self):
        # OpenWrt's feed names the library libelf1; libelf is not a package.
        self.assertIn('apk add tc-full bpftool-full libelf1', self.text)

    def test_service_is_enabled_only_with_landscape(self):
        match = re.search(r'svcs="([^"]+)"', self.text)
        self.assertIsNotNone(match)
        self.assertNotIn('landscape-router', match.group(1))
        self.assertIn('svcs="$svcs landscape-router"', self.text)


class Service(unittest.TestCase):
    def setUp(self):
        self.text = SERVICE.read_text()

    def test_runs_the_static_binary_under_procd(self):
        self.assertIn('USE_PROCD=1', self.text)
        self.assertIn('/usr/sbin/landscape-webserver', self.text)
        self.assertIn('procd_set_param respawn', self.text)

    def test_uses_the_shipped_paths(self):
        for value in ('/etc/landscape-router', '/etc/landscape-router/static',
                      '--port 6300', '--https 6443'):
            self.assertIn(value, self.text)

    def test_raises_the_memlock_limit(self):
        # Landscape locks its maps; the manual's LimitMEMLOCK=infinity.  The
        # rlimit has to be applied by procd to the child: a ulimit in the init
        # script only changes the shell that calls procd.
        self.assertIn('procd_set_param limits memlock=unlimited', self.text)
        self.assertNotIn('ulimit -l', self.text)


class Defaults(unittest.TestCase):
    def setUp(self):
        self.text = DEFAULTS.read_text()

    def test_only_runs_in_a_landscape_image(self):
        self.assertIn('landscape-webserver', self.text)
        self.assertTrue(self.text.lstrip().splitlines()[0].startswith('#!'))
        self.assertIn('exit 0', self.text)

    def test_openwrt_dns_and_dhcp_are_turned_off(self):
        for service in ('dnsmasq', 'odhcpd'):
            self.assertIn(f'/etc/init.d/{service} disable', self.text)
            self.assertIn(f'/etc/init.d/{service} stop', self.text)

    def test_resolv_conf_points_at_landscape(self):
        self.assertIn('/etc/resolv.conf', self.text)
        self.assertIn('nameserver 127.0.0.1', self.text)


class Config(unittest.TestCase):
    def setUp(self):
        self.text = TOML.read_text()

    def test_web_ui_and_ports_match_the_service(self):
        self.assertIn('web_root = "/etc/landscape-router/static"', self.text)
        self.assertIn('port = 6300', self.text)
        self.assertIn('https_port = 6443', self.text)

    def test_database_lives_with_the_config(self):
        self.assertIn('sqlite:///etc/landscape-router/landscape_db.sqlite', self.text)

    def test_no_init_template_is_shipped(self):
        # landscape_init.toml replaces the database on the next start; shipping
        # one would silently reset a configured router.
        self.assertNotIn('landscape_init', BUILD.read_text().split('LANDSCAPE = 1', 1)[0])
        self.assertFalse((TOML.parent / 'landscape_init.toml').exists())


class Bundle(unittest.TestCase):
    def setUp(self):
        self.text = (TOP / 'openwrt/make-flash-bundle.sh').read_text()

    def test_landscape_bundle_is_named_apart(self):
        self.assertIn('e5-openwrt-flash-$VER-landscape-$STAMP-$GIT', self.text)

    def test_landscape_is_not_bolted_onto_an_existing_image(self):
        # E5_IMAGE_FROM only writes modules into an existing image, which has
        # no daemon/UI: refuse it instead of shipping a bundle without
        # Landscape.
        self.assertIn('E5_LANDSCAPE=1 needs the image rebuilt', self.text)

    def test_bundle_image_is_checked_for_landscape(self):
        self.assertIn('checking the image for Landscape', self.text)
        self.assertIn('etc/landscape-router/static/index.html', self.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)

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
import shlex
import subprocess
import unittest
from pathlib import Path

TOP = Path(__file__).resolve().parents[2]
CONFIG = TOP / 'upstream/e5-mainline.config'
BUILD = TOP / 'openwrt/build-rootfs.sh'
SERVICE = TOP / 'openwrt/landscape/etc/init.d/landscape-router'
DEFAULTS = TOP / 'openwrt/landscape/etc/uci-defaults/99-landscape'
TOML = TOP / 'openwrt/landscape/etc/landscape-router/landscape.toml'
INIT = TOP / 'openwrt/landscape/etc/landscape-router/landscape_init.toml'
WAN_SYNC = TOP / 'openwrt/landscape/usr/libexec/landscape-wan-sync'
WAN_LOOP = TOP / 'openwrt/landscape/usr/libexec/landscape-wan-sync-loop'
WAN_SLOTS = TOP / 'openwrt/landscape/usr/libexec/landscape-wan-slots'
WAN_HOTPLUG = TOP / 'openwrt/landscape/etc/hotplug.d/iface/95-landscape-wan'

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

    def test_container_gets_the_host_variables_it_reads(self):
        # The rootfs script runs with set -u; a flag named here but left
        # off the docker command aborts the build only after the packages
        # are installed (run 39227497153 stopped at "LANDSCAPE: parameter
        # not set").  Check the run block, not the whole file.
        start = self.text.index('docker run --rm --platform linux/arm64 \\\n')
        body = self.text.index("/bin/sh -euc '", start)
        run = self.text[start:body]
        for name in ('LANDSCAPE', 'E5_LANDSCAPE_VER', 'VER', 'CONTAINERS',
                     'STANDALONE', 'NAME', 'VERSION', 'EXTRA_LIST'):
            self.assertIn(f'-e {name}=', run)

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
                     'etc/landscape-router/landscape_init.toml',
                     'etc/init.d/landscape-router',
                     'usr/libexec/landscape-wan-sync',
                     'usr/libexec/landscape-wan-sync-loop',
                     'usr/libexec/landscape-wan-slots',
                     'etc/hotplug.d/iface/95-landscape-wan'):
            self.assertIn(name, self.text)
        # the service/config tree is staged next to the root modules and copied
        # over the image root, so it stays out of the Debian/OpenWrt shared tree
        self.assertIn('openwrt/landscape', self.text)
        self.assertIn('cp -a /in/landscape-root/. $R/', self.text)

    def test_the_inner_container_script_survives_quoting(self):
        # build-rootfs.sh hands its container body to `sh -euc '...'`.  An
        # apostrophe in it (a comment, a UCI value) ends that argument early,
        # and the container then runs a truncated script.  Parse the command
        # exactly as the shell does, then syntax-check the body it produces.
        start = self.text.index('/bin/sh -euc ')
        lex = shlex.shlex(self.text[start:], posix=True, punctuation_chars=False)
        lex.whitespace_split = True
        words = list(lex)
        self.assertEqual(words[:2], ['/bin/sh', '-euc'])
        body = words[2]
        self.assertIn('tar -czf /out/$NAME', body)
        self.assertIn('landscape_init.toml', body)
        result = subprocess.run(['sh', '-n'], input=body, text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standalone_image_has_the_management_lan(self):
        # Netifd needs a lan interface to exist; 90-e5 configures it but does
        # not create it, and armsr's base image does not ship one.  The two
        # variants are files copied into the image, never here-documents:
        # build-rootfs.sh's outer `sh -euc '...'` would end at their quotes.
        plain = (TOP / 'openwrt/standalone/network').read_text()
        landscape = (TOP / 'openwrt/standalone/network.landscape').read_text()
        system = (TOP / 'openwrt/standalone/system').read_text()
        for text in (plain, landscape):
            self.assertIn("config device 'br_lan'", text)
            self.assertIn("option name 'br-lan'", text)
            self.assertIn("option bridge_empty '1'", text)
            self.assertIn("config interface 'lan'", text)
        self.assertIn("list ipaddr '192.168.9.1/24'", plain)
        self.assertIn("option ip6assign '64'", plain)
        # Landscape's DHCPv4 owns the address and deletes netifd's copy, so
        # its image must not let netifd configure it at all.
        self.assertNotIn("list ipaddr '192.168.9.1/24'", landscape)
        self.assertNotIn('ip6assign', landscape)
        self.assertIn("option proto 'none'", landscape)
        self.assertIn("option hostname 'E5'", system)
        # and the build has to mount and use those files
        self.assertIn('-v "$HERE/standalone":/in/standalone:ro', self.text)
        self.assertIn('cp /in/standalone/"$STANDALONE_NETWORK" $R/etc/config/network', self.text)
        self.assertIn('cp /in/standalone/system $R/etc/config/system', self.text)
        self.assertIn('STANDALONE_NETWORK=network.landscape', self.text)
        # no here-document may reintroduce the quoting bug
        self.assertNotIn('<<NET', self.text)
        self.assertNotIn('<<SYS', self.text)

    def test_ebpf_packages_use_the_feed_names(self):
        # OpenWrt's feed names the library libelf1; libelf is not a package.
        self.assertIn('apk add tc-full bpftool-full libelf1', self.text)

    def test_wan_helpers_are_executable_in_the_image(self):
        self.assertIn('chmod 755 $R/usr/sbin/landscape-webserver', self.text)
        for name in ('landscape-wan-sync', 'landscape-wan-sync-loop',
                     'landscape-wan-slots'):
            self.assertIn(f'$R/usr/libexec/{name}', self.text)
        self.assertIn('$R/etc/hotplug.d/iface/95-landscape-wan', self.text)

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

    def test_uses_the_flag_names_of_the_pinned_release(self):
        # 0.26.3's clap parser has --log-output-in-terminal; --log_terminal is
        # rejected at startup, which left the router down with no DHCP.
        self.assertIn('--log-output-in-terminal false', self.text)
        self.assertNotIn('--log_terminal', self.text)

    def test_raises_the_memlock_limit(self):
        # Landscape locks its maps; the manual's LimitMEMLOCK=infinity.  The
        # rlimit has to be applied by procd to the child: a ulimit in the init
        # script only changes the shell that calls procd.
        self.assertIn('procd_set_param limits memlock=unlimited', self.text)
        self.assertNotIn('ulimit -l', self.text)

    def test_wan_sync_is_resident(self):
        # The API token and the bearer's address arrive in either order, and
        # either can be late; a one-shot call after boot is not enough.
        self.assertIn('procd_open_instance wan-sync', self.text)
        self.assertIn('/usr/libexec/landscape-wan-sync-loop', self.text)
        self.assertIn('procd_open_instance slot-keeper', self.text)
        self.assertIn('/usr/libexec/landscape-wan-slots', self.text)


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

    def test_wan_seed_lives_in_the_service_not_a_sleep(self):
        self.assertNotIn('sleep 20', self.text)
        self.assertNotIn('landscape-wan-sync ensure', self.text)


class Config(unittest.TestCase):
    def setUp(self):
        self.text = TOML.read_text()

    def test_web_ui_and_ports_match_the_service(self):
        self.assertIn('web_root = "/etc/landscape-router/static"', self.text)
        self.assertIn('port = 6300', self.text)
        self.assertIn('https_port = 6443', self.text)

    def test_database_lives_with_the_config(self):
        self.assertIn('sqlite:///etc/landscape-router/landscape_db.sqlite', self.text)

    def test_init_template_is_shipped_and_versioned(self):
        # The init file seeds the first boot only: landscape_init.lock stops it
        # from replacing a router that has been configured since.  Its version
        # must match the binary, so the build rewrites it from E5_LANDSCAPE_VER.
        self.assertTrue(INIT.is_file())
        text = INIT.read_text()
        self.assertRegex(text, r'(?m)^version = "0\.26\.3"$')
        self.assertIn('landscape_init.toml', BUILD.read_text())
        self.assertIn('sed -i "s/^version = .*/version =', BUILD.read_text())
        # the init file is the active config on a first boot; without auth here
        # the daemon falls back to root/root
        self.assertIn('[config.auth]', text)
        self.assertIn('admin_user = "admin"', text)
        self.assertIn('admin_pass = "root"', text)


class InitConfig(unittest.TestCase):
    def setUp(self):
        self.text = INIT.read_text()

    def test_management_lan_is_seeded(self):
        # br-lan is netifd's; Landscape must not try to make its own br_lan.
        self.assertIn('name = "br-lan"', self.text)
        self.assertIn('create_dev_type = "no_need_to_create"', self.text)
        self.assertIn('zone_type = "lan"', self.text)

    def test_wan_interface_and_route_services_are_seeded(self):
        # Without route_lans/route_wans the BPF ingress has no WAN target
        # table, and forwarded LAN traffic silently falls back to the kernel.
        self.assertIn('name = "sipa_eth0"', self.text)
        self.assertIn('zone_type = "wan"', self.text)
        self.assertIn('[[route_lans]]', self.text)
        self.assertIn('[[route_wans]]', self.text)
        self.assertIn('iface_name = "br-lan"', self.text)
        self.assertIn('iface_name = "sipa_eth0"', self.text)

    def test_wan_link_is_seeded_before_the_modem_attaches(self):
        # The address is carrier-assigned, but the link row itself must exist
        # on the first boot even when the bearer is late.
        self.assertIn('[[wan_links]]', self.text)
        self.assertIn('attach_iface_name = "sipa_eth0"', self.text)
        self.assertIn('t = "static"', self.text)
        self.assertIn('default_router_ip = "10.0.0.1"', self.text)
        self.assertIn('[wan_links.nat]', self.text)

    def test_dhcp_pool_matches_the_openwrt_lan(self):
        self.assertIn('iface_name = "br-lan"', self.text)
        self.assertIn('ip_range_start = "192.168.9.10"', self.text)
        # ip_range_end is exclusive: .201 ends the pool at .200
        self.assertIn('ip_range_end = "192.168.9.201"', self.text)
        self.assertIn('server_ip_addr = "192.168.9.1"', self.text)
        self.assertIn('network_mask = 24', self.text)

    def test_usb_host_keeps_its_address(self):
        self.assertIn('mac = "02:50:00:00:e5:02"', self.text)
        self.assertIn('ipv4 = "192.168.9.2"', self.text)


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
        self.assertIn('etc/landscape-router/landscape_init.toml', self.text)
        for name in ('usr/libexec/landscape-wan-sync',
                     'usr/libexec/landscape-wan-sync-loop',
                     'usr/libexec/landscape-wan-slots',
                     'etc/hotplug.d/iface/95-landscape-wan'):
            self.assertIn(name, self.text)


class WanHelpers(unittest.TestCase):
    def setUp(self):
        self.sync = WAN_SYNC.read_text()
        self.loop = WAN_LOOP.read_text()
        self.slots = WAN_SLOTS.read_text()
        self.hotplug = WAN_HOTPLUG.read_text()

    def test_hotplug_is_a_thin_wrapper(self):
        self.assertNotIn('urllib', self.hotplug)
        self.assertNotIn('curl', self.hotplug)
        self.assertIn('ifup|ifupdate', self.hotplug)
        self.assertIn('[ "$DEVICE" = sipa_eth0 ]', self.hotplug)
        self.assertIn('exec /usr/libexec/landscape-wan-sync', self.hotplug)

    def test_sync_creates_the_link_and_does_not_hardcode_an_address(self):
        self.assertIn("'t': 'static'", self.sync)
        self.assertIn("'default_router_ip': '10.0.0.1'", self.sync)
        self.assertIn('method=POST', self.sync)
        self.assertNotRegex(self.sync, r'10\.35\.\d+\.\d+')
        self.assertNotIn('ANTHROPIC_BASE_URL', self.sync)
        self.assertIn('ip -4 -o addr show dev sipa_eth0', self.sync)

    def test_loop_and_slot_keeper_are_resident(self):
        self.assertIn('while :; do', self.loop)
        self.assertIn('sleep 10', self.loop)
        self.assertIn('while :; do', self.slots)
        self.assertIn('rt4_slot_map', self.slots)
        self.assertIn("printf '%02x'", self.slots)
        # key is {flow_id: u32, slot: u32}, little-endian
        self.assertIn('00 00 00 00', self.slots)
        self.assertIn('00 00 00', self.slots)
        self.assertIn('slot -le 15', self.slots)


if __name__ == '__main__':
    unittest.main(verbosity=2)

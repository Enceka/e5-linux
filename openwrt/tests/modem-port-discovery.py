#!/usr/bin/env python3
"""Real shell metadata notification in an isolated fake sysfs; never sends AT."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]


class Discovery(unittest.TestCase):
    def fixture(self, card='0', external=False, net=True):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        parameter = root/'sys/module/sipc_wwan/parameters/card'
        parameter.parent.mkdir(parents=True); parameter.write_text(card)
        physical = root/('sys/devices/pci/usb/wwan/wwan0/wwan0at0' if external else
                         'sys/devices/platform/sipc-virt/core/channel/wwan/wwan0/wwan0at0')
        physical.mkdir(parents=True)
        port = root/'sys/class/wwan/wwan0at0'; port.parent.mkdir(parents=True); port.symlink_to(physical)
        if net:
            for name in ('sipa_eth'+str(i) for i in range(16)):
                (root/'sys/class/net'/name).mkdir(parents=True)
        cache = root/'events.cache'; cache.write_text(''.join(f'add,sipa_eth{i},net,old\n' for i in range(16)))
        common = root/'common'
        common.write_text(f'''MODEMMANAGER_RUNDIR={root}/run
MODEMMANAGER_EVENTS_CACHE={cache}
mm_report_event() {{ printf '%s %s %s\\n' "$1" "$2" "$3" >> {root}/events; }}
''')
        script = root/'report'
        source = (TOP/'openwrt/overlay/usr/libexec/e5-mm-report-ports').read_text()
        script.write_text(source.replace('/sys/', str(root)+'/sys/').replace(
            '/usr/share/ModemManager/modemmanager.common', str(common)))
        return root, script

    def run_script(self, root, script):
        subprocess.run(['sh', str(script)], check=True)
        events = root/'events'
        return events.read_text().splitlines() if events.exists() else []

    def test_selected_card_and_order(self):
        for card, own, other in [('0',0,8), ('1',8,0)]:
            root, script = self.fixture(card)
            self.assertEqual(self.run_script(root, script), ['add wwan0at0 wwan'] +
                             [f'remove sipa_eth{i} net' for i in range(other,other+8)] +
                             [f'add sipa_eth{i} net' for i in range(own,own+8)])

    def test_external_wwan_is_not_claimed(self):
        root, script = self.fixture(external=True)
        self.assertEqual(self.run_script(root, script), [])

    def test_invalid_slot_is_not_guessed(self):
        root, script = self.fixture('2')
        self.assertEqual(self.run_script(root, script), [])

    def test_missing_at_port_does_not_publish_net(self):
        root, script = self.fixture(); (root/'sys/class/wwan/wwan0at0').unlink()
        self.assertEqual(self.run_script(root, script), [])

    def test_missing_net_port_keeps_at_notification(self):
        root, script = self.fixture(net=False)
        self.assertEqual(self.run_script(root, script), ['add wwan0at0 wwan'] +
                         [f'remove sipa_eth{i} net' for i in range(8,16)])

    def test_missing_context_does_not_hide_other_contexts(self):
        root, script = self.fixture()
        (root/'sys/class/net/sipa_eth1').rmdir()
        events = self.run_script(root, script)
        self.assertNotIn('add sipa_eth1 net', events)
        self.assertIn('add sipa_eth2 net', events)

    def test_debian_filter_is_scoped_and_waits_for_at(self):
        for card in ('0','1'):
            root, _ = self.fixture(card)
            script = root/'allowed'
            script.write_text((TOP/'rootfs/overlay/usr/local/sbin/e5-mm-sipa-port-allowed').read_text().replace('/sys/',str(root)+'/sys/'))
            for index in range(18):
                result = subprocess.run(['sh',str(script),f'sipa_eth{index}'])
                self.assertEqual(result.returncode == 0, int(card)*8 <= index < int(card)*8+8)
            (root/'sys/class/wwan/wwan0at0').unlink()
            self.assertNotEqual(subprocess.run(['sh',str(script),f'sipa_eth{int(card)*8}']).returncode,0)

    def test_openwrt_filter_allows_removing_other_card_even_without_at(self):
        # Execute the filter from the package patch, including its real shell
        # condition, rather than duplicating that condition in this test.
        patch = (TOP/'openwrt/patches/modemmanager-package-sipa-eth.patch').read_text()
        lines = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        block = lines[lines.index('if [ "$action"'):lines.index('mm_log "debug" "unisoc sipa')]
        for card in ('0','1'):
            root, _ = self.fixture(card)
            block_ = block.replace('/sys/',str(root)+'/sys/')
            script = root/'filter'
            script.write_text('filter() {\n'+block_+'\n}\naction=$1 name=$2\nfilter\n')
            for index in range(18):
                result = subprocess.run(['sh',str(script),'add',f'sipa_eth{index}'])
                self.assertEqual(result.returncode == 0,int(card)*8 <= index < int(card)*8+8)
            (root/'sys/class/wwan/wwan0at0').unlink()
            self.assertNotEqual(subprocess.run(['sh',str(script),'add',f'sipa_eth{int(card)*8}']).returncode,0)
            for index in range(16):
                self.assertEqual(subprocess.run(['sh',str(script),'remove',f'sipa_eth{index}']).returncode,0)

    def test_shared_patch_is_idempotent_and_preserves_replay_sequence(self):
        patch = runpy.run_path(str(TOP/'devices/t551m/network-startup.py'))['patch_root']
        for profile in ('e5','t551m','m8'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); wrapper = root/'usr/sbin/ModemManager-wrapper'
                wrapper.parent.mkdir(parents=True)
                wrapper.write_text('''#!/bin/sh
main() {
	/usr/sbin/ModemManager "$@" 1>/dev/null 2>/dev/null &
	mm_report_events_from_cache
	wait "$CHILD"
}
''')
                loader = root/'etc/init.d/e5-sipc-wwan'; loader.parent.mkdir(parents=True)
                loader.write_text((TOP/'openwrt/overlay/etc/init.d/e5-sipc-wwan').read_text())
                patch(root, profile); first = wrapper.read_bytes(), loader.read_bytes()
                patch(root, profile); self.assertEqual(first, (wrapper.read_bytes(), loader.read_bytes()))
                text = wrapper.read_text()
                self.assertLess(text.index('boot-replay early'), text.index('/usr/sbin/ModemManager "$@"'))
                self.assertGreater(text.index('# unisoc-port-discovery:'), text.index('/usr/sbin/ModemManager "$@"'))
                self.assertIn('tx_gap_ms=100', loader.read_text())

    def test_installed_update_hook_uses_overlay_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root/'opt/e5/t551m-network-startup'
            installed.parent.mkdir(parents=True)
            installed.write_bytes((TOP/'devices/t551m/network-startup.py').read_bytes())
            patch = runpy.run_path(str(installed))['patch_root']
            with self.assertRaisesRegex(ValueError, 'Missing shared'):
                patch(root)
            helper = root/'usr/libexec/e5-mm-report-ports'
            helper.write_bytes((TOP/'openwrt/overlay/usr/libexec/e5-mm-report-ports').read_bytes())
            before = helper.read_bytes()
            patch(root)
            self.assertEqual(before, helper.read_bytes())
            self.assertTrue(helper.stat().st_mode & 0o111)


if __name__ == '__main__': unittest.main()

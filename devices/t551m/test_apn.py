"""Shared APN adapters, packaging, private RPC and patch regressions; no modem."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
PLUGIN = TOP / 'openwrt/luci-app-t551m'
HERE = Path(__file__).resolve().parent
if os.name == 'nt':
    # Windows has no flock; mock only that platform primitive, not APN logic.
    sys.modules['fcntl'] = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *a: None)
loader = importlib.machinery.SourceFileLoader('shared_apn', str(PLUGIN / 'root/usr/libexec/unisoc-modem/apn'))
spec = importlib.util.spec_from_loader(loader.name, loader)
apn = importlib.util.module_from_spec(spec)
loader.exec_module(apn)
network = runpy.run_path(str(HERE / 'network-startup.py'))
menu_compiler = runpy.run_path(str(PLUGIN / 'compile-menu.py'))


class APN(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.card = self.root / 'card'
        self.card.write_text('1')
        self.who = dict(slot='1', iccid='89860112345678901234', imsi='460011234567890')
        self.addCleanup(patch.stopall)
        patch.object(apn, 'RUN', self.root / 'run').start()
        patch.object(apn, 'CARD', self.card).start()

    def test_identity_from_active_mm_sim_not_any(self):
        with patch.object(apn, 'mm', side_effect=[{'modem':{'generic':{'sim':'/org/freedesktop/ModemManager1/SIM/2'}}}, {'sim':{'properties':{'iccid':self.who['iccid'], 'imsi':self.who['imsi']}}}]) as mm:
            self.assertEqual(apn.identity(), self.who)
            self.assertEqual(mm.call_args_list[1].args[0], ['-i', '/org/freedesktop/ModemManager1/SIM/2'])

    def test_missing_sim_property_has_no_borrowed_identity(self):
        with patch.object(apn, 'mm', return_value={'modem':{'generic':{'sim':'--'}}}):
            self.assertEqual(apn.identity(), {'slot':'1'})

    def test_sim_change_during_identity_rejected(self):
        def mm(args):
            if args[0] == '-m':
                return {'modem':{'generic':{'sim':'/org/freedesktop/ModemManager1/SIM/2'}}}
            self.card.write_text('0')
            return {'sim':{'properties':{'iccid':self.who['iccid']}}}
        with patch.object(apn, 'mm', side_effect=mm):
            self.assertRaises(ValueError, apn.identity)

    def test_apply_during_switch_rejected(self):
        with patch.object(apn.fcntl, 'flock', side_effect=BlockingIOError), patch.object(apn, 'invoke') as worker:
            self.assertEqual(apn.main('apply', {'id':'automatic'})['error'], 'apn_busy')
            worker.assert_not_called()

    def test_screen_apply_accepts_same_data_sim(self):
        with patch.object(apn, 'identity', return_value=self.who), patch.object(apn, 'invoke',return_value={'ok':1}) as worker:
            self.assertTrue(apn.main('auto', {'data_sim':1})['ok'])
            worker.assert_called_once_with('auto',self.who,{'data_sim':1})

    def test_screen_apply_rejects_data_sim_changed_since_confirmation(self):
        with patch.object(apn, 'identity', return_value=self.who), patch.object(apn, 'invoke') as worker:
            for action in ('apply', 'auto'):
                self.assertEqual(apn.main(action, {'data_sim':0})['error'], 'apn_sim_changed')
                self.assertEqual(apn.main(action, {'data_sim':True})['error'], 'apn_sim_changed')
            worker.assert_not_called()

    def test_apply_without_identity_does_not_fall_back(self):
        with patch.object(apn, 'identity', side_effect=ValueError), patch.object(apn, 'invoke') as worker:
            for action in ('apply', 'auto'):
                self.assertEqual(apn.main(action, {})['error'], 'apn_identity')
            worker.assert_not_called()

    def test_resolver_does_not_deadlock_switch(self):
        with patch.object(apn, 'identity', return_value=self.who), patch.object(apn, 'invoke', return_value={'ok':1}) as worker, patch.object(apn.fcntl, 'flock', side_effect=AssertionError('recursive lock')):
            self.assertTrue(apn.main('resolve')['ok'])
            worker.assert_called_once_with('resolve', self.who)

    def test_status_is_read_only_and_does_not_take_the_switch_lock(self):
        with patch.object(apn,'identity',return_value=self.who),patch.object(apn,'invoke',return_value={'ok':1,'apn':'CMIOT5G'}) as worker,patch.object(apn.fcntl,'flock',side_effect=AssertionError('status must not lock')):
            self.assertEqual(apn.main('status')['apn'],'CMIOT5G')
            worker.assert_called_once_with('status',self.who)

    def test_status_has_no_binary_capability_scan(self):
        public=dict(ok=1,apn='CMIOT5G',source='sim',data_sim=1)
        with patch.object(apn.subprocess,'check_output',return_value=json.dumps(public)),patch.object(apn,'auth_supported',side_effect=AssertionError('hot path binary scan')):
            self.assertEqual(apn.invoke('status',self.who),public)

    def test_status_identity_failure_is_unknown_without_changing_get_fallback(self):
        for error in (OSError('missing card'), ValueError('card changed'), subprocess.TimeoutExpired('mmcli',4)):
            with patch.object(apn,'identity',side_effect=error),patch.object(apn,'invoke',return_value={'ok':1}) as worker:
                self.assertEqual(apn.main('status'),{'ok':0,'error':'apn_identity'})
                worker.assert_not_called()
                self.assertEqual(apn.main('get'),{'ok':1})
                worker.assert_called_once_with('get',{})

    def test_global_apply_without_iccid_cannot_bypass_binding(self):
        with patch.object(apn, 'identity', return_value={'slot':'1'}), patch.object(apn, 'auth_supported', return_value=True), patch.object(apn, 'invoke') as worker:
            self.assertEqual(apn.main('apply', {'id':'automatic','remember':False})['error'], 'apn_identity')
            worker.assert_not_called()

    def test_save_only_and_native_auth_capability(self):
        with patch.object(apn, 'identity', return_value=self.who), patch.object(apn, 'auth_supported', return_value=False), patch.object(apn, 'invoke', return_value={'profiles':[{'id':'private', 'auth':'chap'}]}) as worker:
            self.assertEqual(apn.main('apply', {'id':'private'})['error'], 'apn_auth_unsupported')
            self.assertEqual(worker.call_count, 1)
            apn.main('save', {'name':'stored'})
            self.assertEqual(worker.call_args.args[0], 'save')

    def test_alphanumeric_card_identity_preserved_for_apply_and_auto(self):
        for iccid in ('898604E112345678901F', '898604Z11234567890af'):
            who = dict(self.who, iccid=iccid)
            with patch.object(apn, 'identity', return_value=who), patch.object(apn, 'auth_supported', return_value=True), patch.object(apn, 'invoke', return_value={'ok':1}) as worker:
                for action in ('apply', 'auto'):
                    self.assertTrue(apn.main(action, {})['ok'])
                    self.assertEqual(worker.call_args.args[1]['iccid'], iccid)

    def test_invalid_card_identity_cannot_write(self):
        for iccid in (12345678901234567890, '898604Z11234567890af\n', '898604/112345678901F', 'short', 'x'*23, '卡'*20):
            with patch.object(apn, 'identity', return_value=dict(self.who, iccid=iccid)), patch.object(apn, 'invoke') as worker:
                self.assertEqual(apn.main('auto', {})['error'], 'apn_identity')
                worker.assert_not_called()

    def test_private_resolve_and_password_are_not_rpc(self):
        rpc = (PLUGIN / 'root/usr/libexec/rpcd/mu300dash').read_text(encoding='utf-8')
        branch = rpc[rpc.index('        apn_set)'):rpc.index('        sim_get)')]
        self.assertIn('case "$action" in save|delete|apply|auto)', branch)
        self.assertNotIn('run_m', branch)
        self.assertNotIn('eval', branch.replace('# Never log APN payloads or pass secrets through eval/argv.', ''))
        self.assertIn('printf', branch)

    def test_menu_acl_and_translation_catalogs(self):
        menu = json.loads((PLUGIN / 'root/usr/share/luci/menu.d/luci-app-mu300.json').read_text(encoding='utf-8'))
        self.assertEqual(menu['admin/modem/apn']['action']['path'], 'mu300/apn')
        acl = json.loads((PLUGIN / 'root/usr/share/rpcd/acl.d/luci-app-mu300.json').read_text(encoding='utf-8'))['luci-app-mu300']
        self.assertIn('apn_get', acl['read']['ubus']['mu300dash'])
        self.assertNotIn('apn_set', acl['read']['ubus']['mu300dash'])
        for language, label in [('en','Access points (APN)'), ('tr','Erişim noktaları (APN)')]:
            lmo = (PLUGIN / f'lmo/mu300.{language}.lmo').read_bytes()
            self.assertEqual(lmo, menu_compiler['compile_po'](PLUGIN / f'po/{language}/mu300.po'))
            offset = struct.unpack('!I', lmo[-4:])[0]
            entries = [struct.unpack('!IIII', lmo[n:n+16]) for n in range(offset, len(lmo)-4,16)]
            key = menu_compiler['sfh']('接入点 APN')
            entry = next(e for e in entries if e[0] == key)
            self.assertEqual(lmo[entry[2]:entry[2]+entry[3]].decode(), label)

    def test_every_model_gets_idempotent_hook_before_attach(self):
        # Minimal tracked fixture for the pinned netifd patch anchors, not a
        # developer's ignored work directory or a network-fetched moving file.
        proto = '''modemmanager_set_plmn() {
\tmmcli --modem="${device}" \\
\t\t--timeout 120 \\
\t\t--3gpp-register-in-operator="${plmn}" || {
\t\tproto_block_restart "${interface}"
\t}
}
proto_modemmanager_setup() {
\t# always cleanup before attempting a new connection, just in case
\t\t\tproto_notify_error "${interface}" MM_FAILED_REASON_SIM_MISSING
\t\t\tproto_block_restart "${interface}"
\t# set initial eps bearer settings
\t\tcase "$init_epsbearer" in
\t\tesac
\tif [ -z "${allowedmode}" ]; then
\t\tmodemmanager_set_allowed_mode "$device" "$interface" "any"
\tfi
\tmmcli --modem="${device}" --timeout 120 --simple-connect="${connectargs}" || {
\t\treturn 1
\t}
}
proto_modemmanager_teardown() {
\tlocal disable="$(uci_get network "$interface" disable_modem "1")"
}
'''
        for profile in ('e5', 't551m', 'm8'):
            root = self.root / profile
            path = root / 'lib/netifd/proto/modemmanager.sh'
            path.parent.mkdir(parents=True)
            path.write_text(proto)
            network['patch_root'](root, profile)
            first = path.read_bytes()
            network['patch_root'](root, profile)
            self.assertEqual(path.read_bytes(), first)
            text = path.read_text()
            self.assertLess(text.index('# unisoc-apn-selection:'), text.index('# set initial eps bearer settings'))
            self.assertIn('allowedauth=\'pap chap\'', text)
            self.assertIn('unset apn_selection', text)
            subprocess.run(['C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else 'sh','-n',str(path)], check=True)

    def test_common_stager_includes_profiles_helpers_all_models(self):
        ui = runpy.run_path(str(HERE / 'ui.py'))['stage']
        globals_ = ui.__globals__
        real_run = runpy.run_path
        client = self.root / 'fake-at-client'
        client.write_bytes(b'test-only compiled-client fixture')
        def staged_script(path):
            path = Path(path)
            if path.name == 'build-at-client.py':
                return {'build':lambda:client}
            if path.name == 'ui-cleanup.py':
                return {'cleanup':lambda root:None}
            if path.parent.name == 'infoscreen':
                return {'stage':lambda root:None}
            return real_run(str(path))
        with patch.dict(globals_, PACKAGES={}), patch.object(runpy, 'run_path', side_effect=staged_script), patch.dict(os.environ,E5_UI_CACHE=str(self.root/'cache')):
            for model in ('e5', 't551m', 'm8'):
                root = self.root / ('stage-' + model)
                ui(root, profile=model)
                for file in ('usr/libexec/unisoc-modem/apn','usr/libexec/unisoc-modem/apn-worker','usr/libexec/unisoc-modem/apn.uc','usr/libexec/unisoc-modem/dashboard-network.sh','www/luci-static/resources/view/mu300/apn.js','etc/config/unisoc_apn'):
                    self.assertTrue((root/file).is_file(), model + ':' + file)
                config = root / 'etc/config/unisoc_apn'
                config.write_text("config profile 'user'\n option name 'Keep me'\n")
                ui(root, profile=model)
                self.assertIn('Keep me',config.read_text())

    def test_shared_auth_patch_applies_to_original_plugin(self):
        original = (TOP / 'rootfs/deb-patches/modemmanager-01-unisoc-plugin.patch').read_text()
        section = original.split('diff -ruN a/src/plugins/unisoc/mm-broadband-bearer-unisoc.c',1)[1].split('\ndiff -ruN',1)[0]
        source = '\n'.join(l[1:] for l in section.splitlines() if l.startswith('+') and not l.startswith('+++')) + '\n'
        target = self.root / 'src/plugins/unisoc/mm-broadband-bearer-unisoc.c'
        target.parent.mkdir(parents=True)
        target.write_text(source)
        executable = 'C:/Program Files/Git/usr/bin/patch.exe' if os.name == 'nt' else 'patch'
        result = subprocess.run([executable,'--batch','--fuzz=0','-p1','-i',str(TOP/'rootfs/deb-patches/modemmanager-13-unisoc-bearer-auth.patch')],cwd=self.root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        patched = target.read_text()
        self.assertIn('mm_base_bearer_peek_config',patched)
        self.assertIn('MM_BEARER_ALLOWED_AUTH_PAP | MM_BEARER_ALLOWED_AUTH_CHAP',patched)
        self.assertIn('"+CGPCO=0,\\"%s\\",\\"%s\\",%u,%u"',patched)
        self.assertIn('(GAsyncReadyCallback) cgpco_ready',patched)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""RF intent, per-slot isolation, owner restoration and reboot persistence."""
import fcntl
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
TOOL = TOP / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/data-sim'


class RadioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = self.root / 'sim-radio'
        self.card = self.root / 'card'
        self.card.write_text('0')
        self.env = dict(UNISOC_RADIO_POLICY=str(self.policy), E5_DATA_SIM_CARD=str(self.card),
                        E5_DATA_SIM_RUN=str(self.root/'jobs'),
                        E5_SMS_LOCK=str(self.root / 'sms.lock'),
                        E5_RADIO_MODEM_LOCK=str(self.root / 'modem.lock'))
        with patch.dict(os.environ, self.env):
            self.scope = runpy.run_path(str(TOOL))
        self.apply = self.scope['radio_apply']
        self.g = self.apply.__globals__
        self.commands = []
        self.fail = None
        self.states = [1, 1]

        def execute(argv, **kw):
            self.commands.append(argv)
            if argv[0] == 'ubus':
                return subprocess.CompletedProcess(argv, 0,
                    '{"up":false,"pending":false}' if argv[-1]=='status' else '', '')
            if argv[0] == 'mmcli':
                own=int(self.card.read_text())
                if argv[-1]=='--disable': self.states[own]=4
                elif self.scope['radio_policy']()[own]: self.states[own]=1
                return subprocess.CompletedProcess(argv,0,'','')
            cmd = argv[-1]
            if self.fail and self.fail in cmd:
                return subprocess.CompletedProcess(argv, 1, 'ERROR\n', '')
            slot = int(cmd.split('SPACTCARD=')[1][0])
            if ';+CFUN=' in cmd:
                self.states[slot] = int(cmd[-1])
            reply = f'+CFUN: {self.states[slot]}\nOK\n' if cmd.endswith('?') else 'OK\n'
            return subprocess.CompletedProcess(argv, 0, reply, '')
        self.patches = [patch.dict(os.environ, self.env), patch.object(self.scope['subprocess'], 'run', execute)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_legacy_default_and_all_saved_combinations(self):
        self.assertEqual(self.scope['radio_policy'](), [True, True])
        for a in (0,1):
            for b in (0,1):
                self.policy.write_text(f'{a} {b}\n')
                self.assertEqual(self.scope['radio_policy'](), [bool(a),bool(b)])
                fresh = runpy.run_path(str(TOOL))
                self.assertEqual(fresh['radio_policy'](), [bool(a),bool(b)])

    def test_standby_off_does_not_touch_wan_or_other_rf(self):
        self.apply('1', False)
        self.assertEqual(self.states, [1,4])
        self.assertFalse(any(c[0]=='ubus' for c in self.commands))
        self.assertEqual(self.policy.read_text(), '1 0\n')
        self.assertTrue(self.commands[-1][-1].endswith('SPACTCARD=0;+CFUN?'))

    def test_both_can_be_off_and_enabled_independently(self):
        self.apply('0', False)
        self.apply('1', False)
        self.assertEqual((self.states,self.policy.read_text()), ([4,4],'0 0\n'))
        self.apply('1', True)
        self.assertEqual((self.states,self.policy.read_text()), ([4,1],'0 1\n'))
        self.apply('0', True)
        self.assertEqual(self.states,[1,1])

    def test_data_intent_is_preserved_without_ifup_ifdown_or_card_switch(self):
        self.apply('0', False)
        self.apply('0', True)
        notes = [json.loads(c[-1]) for c in self.commands if c[0]=='ubus' and 'notify_proto' in c]
        self.assertEqual(notes,[{'action':5,'available':False},{'action':5,'available':True}])
        self.assertFalse(any(c[0] in ('ifup','ifdown', 'uci') for c in self.commands))
        self.assertFalse(any('SPSWDATA' in c[-1] or 'SFUN' in c[-1] for c in self.commands))
        self.assertEqual([c[-1] for c in self.commands if c[0]=='mmcli'],['--enable'])

    def test_failure_restores_at_owner_and_keeps_explicit_off_for_next_boot(self):
        self.fail='CFUN=4'
        with self.assertRaises(RuntimeError): self.apply('1',False)
        self.assertEqual(self.policy.read_text(),'1 0\n')
        self.assertTrue(self.commands[-1][-1].endswith('SPACTCARD=0;+CFUN?'))

    def test_bad_policy_is_not_silently_enabled(self):
        for bad in ('1', '1 2', '1 1\n0', 'on off', ''):
            self.policy.write_text(bad)
            with self.assertRaises(ValueError): self.scope['radio_policy']()

    def test_sms_or_network_mutex_prevents_persistence_and_at(self):
        for name in ('sms.lock', 'modem.lock'):
            with (self.root/name).open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): self.apply('1',False)
            self.assertFalse(self.policy.exists())
            self.assertEqual(self.commands,[])

    def test_invalid_rpc_arguments_do_not_spawn(self):
        for args in ({'slot':'2','enabled':False,'confirm':True},
                     {'slot':'0','enabled':'false','confirm':True},
                     {'slot':'0','enabled':False,'confirm':False}):
            with self.assertRaises(ValueError): self.scope['start'](args,radio=True)

    def test_data_sim_cannot_switch_to_disabled_target(self):
        self.policy.write_text('1 0\n')
        with self.assertRaisesRegex(ValueError,'Enable the target SIM radio'):
            self.scope['start']({'slot':'1','current':'0','confirm':True})
        self.assertEqual(self.commands,[])

    def test_worker_reports_busy_without_changing_policy_or_rf(self):
        self.scope['RUN'].mkdir()
        job={'id':'a'*32,'state':'running','kind':'radio','previous':'0','target':'1','enabled':False}
        self.scope['write'](job)
        with (self.root/'sms.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.scope['worker'](job['id'])
        result=self.scope['status'](job['id'])
        self.assertEqual(result['error'],'modem_busy')
        self.assertEqual(result['state'],'error')
        self.assertFalse(self.policy.exists())
        self.assertEqual(self.commands,[])

    def test_failed_atomic_save_never_issues_rf_command(self):
        self.policy.write_text('1 1\n')
        with patch.object(Path, 'replace', side_effect=OSError('No space left')):
            with self.assertRaises(OSError): self.apply('1',False)
        self.assertEqual(self.policy.read_text(),'1 1\n')
        self.assertEqual(self.commands,[])

    def test_boot_proto_waits_without_enable_or_retry_when_data_radio_disabled(self):
        scope=runpy.run_path(str(TOP/'devices/t551m/network-startup.py'))
        block=scope['RADIO_POLICY'].replace('/etc/e5/sim-radio',str(self.policy)).replace(
            '/sys/module/sipc_wwan/parameters/card',str(self.card)).replace(
            '/usr/libexec/unisoc-modem/radio-allowed',str(TOOL.with_name('radio-allowed')))
        for slot in (0,1):
            self.card.write_text(str(slot))
            for flags in ('0 0','0 1','1 0','1 1'):
                self.policy.write_text(flags+'\n')
                script='device=unisoc-sipc; interface=wan\nproto_notify_error(){ echo error:$*; }\nproto_set_available(){ echo available:$*; }\nsetup(){\n'+block+'echo enable\n}\nsetup\n'
                # Bypass the RF command mock: this only runs the real shell
                # guard against temporary files; no actual netifd/AT command.
                result=subprocess.Popen(['sh','-c',script],env=dict(os.environ,**self.env),stdout=subprocess.PIPE,text=True)
                text=result.communicate(timeout=3)[0]
                if flags[slot*2]=='0':
                    self.assertNotIn('enable',text)
                    self.assertIn('available:wan 0',text)
                else:self.assertEqual(text,'enable\n')


if __name__ == '__main__': unittest.main()

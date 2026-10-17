"""Run the shipped restart helper with fake commands; no radio or network access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/t551m-radio-restart'


class RadioRestartTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = self.root/'trace'
        card = self.root/'card';card.write_text('0')
        self.env = dict(os.environ, PATH=str(self.root)+':'+os.environ['PATH'],
                        UNISOC_RADIO_ALLOWED=str(SCRIPT.with_name('radio-allowed')),
                        UNISOC_RADIO_POLICY=str(self.root/'radio-policy'), TRACE=str(self.trace), STATE='connected', MU300_SIM_SLOT='0',
                        UNISOC_CARD_FILE=str(card), MU300_AT=str(self.root/'at'), CFUN='1')
        self.script('mmcli', '''echo "mmcli $*" >> "$TRACE"
case "$*" in
    *' -K') [ "${QUERY_FAIL:-0}" = 0 ] || exit 1; echo "modem.generic.state : $STATE";;
    *--disable) [ "${DISABLE_FAIL:-0}" = 0 ] || { echo 'Wrong state' >&2; exit 1; };;
    *--enable) [ "${ENABLE_FAIL:-0}" = 0 ] || exit 1;;
esac''')
        self.script('uci', 'echo wan')
        self.script('sleep', 'exit 0')
        self.script('ubus', 'echo "{\"autostart\":${AUTOSTART:-true}}"')
        self.script('jsonfilter', 'cat >/dev/null; echo "${AUTOSTART:-true}"')
        for command in ('ifup', 'ifdown'):
            self.script(command, f'echo "{command} $*" >> "$TRACE"')
        self.script('at', '''echo "at $*" >> "$TRACE"
case "$*" in *"${FAIL_AT:-no-failure}") echo ERROR; exit 1;; esac
case "$*" in *'AT+CFUN?') echo "+CFUN: $CFUN";; esac
echo OK''')

    def script(self, name, body):
        path = self.root/name
        path.write_text('#!/bin/sh\n'+body+'\n')
        path.chmod(0o755)

    def run_helper(self, *args):
        self.trace.unlink(missing_ok=True)
        result = subprocess.run(['sh',str(SCRIPT),*args],env=self.env,
                                capture_output=True,text=True,timeout=5)
        return result, self.trace.read_text() if self.trace.exists() else ''

    def test_offline_states_never_disconnect_wan_or_cycle_radio(self):
        for state in ('failed','locked','disabled','unknown','initializing','disabling','enabling'):
            with self.subTest(state=state):
                self.env['STATE'] = state
                result, trace = self.run_helper('--settings')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),'RECONNECT-DEFERRED '+state)
                self.assertNotIn('ifdown',trace)
                self.assertNotIn('--disable',trace)
                self.assertNotIn('at ',trace)

    def test_no_service_still_allows_settings_with_ready_radio(self):
        for state in ('enabled','searching','registered','connected'):
            with self.subTest(state=state):
                self.env['STATE'] = state
                result, trace = self.run_helper('--settings')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertLess(trace.index('ifdown'),trace.index('--disable'))
                self.assertLess(trace.index('--disable'),trace.index('--enable'))
                self.assertLess(trace.index('--enable'),trace.index('ifup'))

    def test_failed_or_unknown_query_never_touches_wan(self):
        for changes in ({'QUERY_FAIL':'1'}, {'STATE':'not-a-state'}):
            with self.subTest(changes=changes):
                self.env.update(changes)
                result, trace = self.run_helper('--settings')
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('ifdown',trace)
                self.assertNotIn('--disable',trace)
                self.env.pop('QUERY_FAIL',None)

    def test_restore_netifd_on_disable_and_enable_failure(self):
        for failure in ('DISABLE_FAIL','ENABLE_FAIL'):
            with self.subTest(failure=failure):
                self.env[failure] = '1'
                result, trace = self.run_helper('--settings')
                self.assertNotEqual(result.returncode,0)
                self.assertIn('ifdown wan',trace)
                self.assertEqual(trace.splitlines()[-1],'ifup wan')
                self.env.pop(failure)

    def test_standby_offline_skips_cycle_without_reading_primary_mm(self):
        self.env['MU300_SIM_SLOT'] = '1'
        for cfun in ('0','4'):
            self.env['CFUN'] = cfun
            result, trace = self.run_helper('--settings')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'RECONNECT-DEFERRED radio-off')
            self.assertNotIn('AT+CFUN=4',trace)
            self.assertNotIn('mmcli',trace)
            self.assertNotIn('ifdown',trace)

    def test_standby_active_uses_existing_cfun_order_without_touching_wan(self):
        self.env['MU300_SIM_SLOT'] = '1'
        result, trace = self.run_helper('--settings')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(trace.index('AT+CFUN=4'),trace.index('AT+CFUN=1'))
        self.assertNotIn('mmcli',trace)
        self.assertNotIn('ifdown',trace)

    def test_explicit_manual_restart_keeps_existing_behavior(self):
        self.env['STATE'] = 'failed'
        result, trace = self.run_helper()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn(' -K',trace)
        self.assertIn('--disable',trace)

    def test_settings_reconnect_keeps_manual_data_off(self):
        self.env['AUTOSTART']='false'
        result, trace = self.run_helper('--settings')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--disable',trace)
        self.assertIn('--enable',trace)
        self.assertNotIn('ifup',trace)

    def test_unreadable_autostart_never_disconnects_or_enables(self):
        self.env['AUTOSTART']='unknown'
        result, trace = self.run_helper('--settings')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('ifdown',trace)
        self.assertNotIn('--disable',trace)

    def test_bands_use_sfun_even_when_mm_is_failed_and_restore_wan(self):
        self.env['STATE'] = 'failed'
        result, trace = self.run_helper('--bands')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(trace.index('ifdown wan'),trace.index('AT+SFUN=5'))
        self.assertLess(trace.index('AT+SFUN=5'),trace.index('AT+SFUN=4'))
        self.assertEqual(trace.splitlines()[-1],'ifup wan')
        self.assertNotIn('mmcli',trace)
        self.assertNotIn('AT+CFUN=',trace)

    def test_band_standby_cycle_never_touches_data_card_wan(self):
        self.env['MU300_SIM_SLOT'] = '1'
        result, trace = self.run_helper('--bands')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('AT+SFUN=5',trace);self.assertIn('AT+SFUN=4',trace)
        self.assertNotIn('ifdown',trace);self.assertNotIn('ifup',trace)

    def test_band_stop_failure_still_restores_stack_and_wan(self):
        for command in ('AT+SFUN=5','AT+SFUN=4'):
            self.env['FAIL_AT'] = command
            result, trace = self.run_helper('--bands')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('AT+SFUN=4',trace)
            self.assertEqual(trace.splitlines()[-1],'ifup wan')

    def test_band_cycle_preserves_manual_data_and_radio_off(self):
        self.env['AUTOSTART'] = 'false'
        result, trace = self.run_helper('--bands')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('AT+SFUN=4',trace);self.assertNotIn('ifup',trace)
        for cfun in ('0','4'):
            self.env['CFUN'] = cfun
            result, trace = self.run_helper('--bands')
            self.assertEqual(result.stdout.strip(),'RECONNECT-DEFERRED radio-off')
            self.assertNotIn('AT+SFUN=',trace);self.assertNotIn('ifdown',trace)
        self.env['CFUN'] = '1'
        Path(self.env['UNISOC_RADIO_POLICY']).write_text('0 1\n')
        result, trace = self.run_helper('--bands')
        self.assertEqual(result.stdout.strip(),'RECONNECT-DEFERRED radio-disabled-by-user')
        self.assertNotIn('at ',trace)


if __name__ == '__main__':
    unittest.main()

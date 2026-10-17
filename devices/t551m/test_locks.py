"""No modem access: exercise verified setters, SIM selection and job failures."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem/lock-control'
spec = importlib.util.spec_from_loader('locks', importlib.machinery.SourceFileLoader('locks', str(SOURCE)))
locks = importlib.util.module_from_spec(spec)
with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', '')):
    spec.loader.exec_module(locks)

class LocksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        locks.RUN = root / 'run';locks.RUN.mkdir()
        locks.STATE = root / 'state';locks.STATE.mkdir()
        locks.CARD = root / 'card';locks.CARD.write_text('0')
        locks.MARKER = root / 'replayed'
        locks.TARGET = None; locks.LOCK_RUN = None
        self.tm, self.gran, self.endc = [3,134,0], 1, 0
        self.cells = {12: [],16: []}
        self.band = {0:[0,482,0,149,0],3:[549,0,272,0]}
        self.sent, self.fail, self.ignore = [], None, None
        self.restarts = 0
        self.restart_args = []
        self.reset_bands_on_restart = False
        self.reset_mode_on_restart = False
        self.omit_final = None
        self.restart_result = (0, '', '')
        self.voice = {'volte': True, 'vonr': False}
        p = patch.object(locks.subprocess, 'run', side_effect=self.run_command)
        p.start();self.addCleanup(p.stop)
        p = patch.object(locks.time, 'sleep');p.start();self.addCleanup(p.stop)

    def test_auto_mode_configuration_keeps_legacy_and_explicit_modes(self):
        legacy = locks.mode_table('134')
        native = locks.mode_table('152')
        self.assertEqual(native['auto'], (152, 1))
        self.assertEqual(native['auto-nsa'], (152, 0))
        for key in ('4g', 'sa', 'nsa', '5g4g', '4g-nsa', 'sa-nsa'):
            self.assertEqual(native[key], legacy[key])
        for value in ('', 'unsupported', '0', '153'):
            self.assertEqual(locks.mode_table(value), legacy)

    def test_native_auto_preserves_other_sim_and_primary(self):
        with patch.object(locks, 'MODES', locks.mode_table('152')):
            self.tm = [134, 3, 1]
            locks.TARGET = 0
            locks.apply('mode', 'auto')
            self.assertEqual(self.tm, [152, 3, 1])
            self.assertEqual(locks.snapshot()['mode']['label'], 'auto')
            self.assertEqual((locks.STATE / 'mode').read_text().strip(), 'auto')
            self.assertTrue(locks.matches_saved('mode', 'auto', locks.snapshot()))

    def test_native_auto_readback_is_not_unknown_on_legacy_config(self):
        self.tm = [152, 3, 0]
        self.assertEqual(locks.snapshot()['mode']['label'], 'auto')

    def run_command(self, argv, **kwargs):
        if argv[0] == locks.RESTART:
            self.restarts += 1
            self.restart_args.append(argv[1:])
            if self.reset_mode_on_restart: self.tm[0] = 134
            if self.reset_bands_on_restart: self.band = {0:[0,0,0,1,0],3:[0,0,16,0]}
            self.assertIn(argv[1:], [['--settings'], ['--bands']])
            return subprocess.CompletedProcess(argv, *self.restart_result)
        cmd = argv[-1];self.sent.append(cmd)
        if cmd == self.fail: return subprocess.CompletedProcess(argv,1,'','AT channel quarantined')
        data = ''
        if cmd == 'AT+SPTESTMODE?': data = '+SPTESTMODE: '+','.join(map(str,self.tm))
        elif cmd == 'AT+SP5GRAN?': data = '+SP5GRAN: '+str(self.gran)
        elif cmd == 'AT+SPENDC?': data = '+ENDC: '+str(self.endc)
        elif cmd == 'AT+CAVIMS?': data = '+CAVIMS: '+str(int(self.voice['volte']))
        elif cmd == 'AT+SP5GCMDS="get nr synch_param",42':
            data = '+SP5GCMDS: "get nr synch_param",42,'+str(int(self.voice['vonr']))
        elif cmd.startswith(('AT+CAVIMS=', 'AT+SP5GCMDS="set nr param",45,')):
            key = 'volte' if cmd.startswith('AT+CAVIMS=') else 'vonr'
            if cmd != self.ignore: self.voice[key] = cmd[-1] == '1'
        elif cmd == 'AT+SP5GCMDS="get nr support_band"': data = '+SP5GCMDS: get nr support_band,6,41,78,1,8,28,5'
        elif cmd.startswith('AT+SPTESTMODE='):
            if cmd != self.ignore:self.tm = list(map(int,cmd.split('=')[1].split(',')))
        elif cmd.startswith('AT+SP5GRAN='):self.gran = int(cmd.split('=')[1])
        elif cmd.startswith('AT+SPENDC='):
            if cmd != self.ignore:self.endc = 1 if cmd.endswith('=1') else 0
        elif cmd.startswith('AT+SPLBAND='):
            v = list(map(int,cmd.split('=')[1].split(',')))
            if len(v)==1:data = '+SPLBAND: '+','.join(map(str,self.band[v[0]]))
            elif cmd != self.ignore:self.band[0 if v[0]==1 else 3] = v[1:]
        elif cmd.startswith('AT+SPFORCEFRQ='):
            v = list(map(int,cmd.split('=')[1].split(',')))
            if v[1]==3:data = '+SPFORCEFRQ: '+','.join(map(str,v+self.cells[v[0]]))
            elif v[1]==4:self.cells[v[0]]=[]
            elif v[1]==6:self.cells[v[0]] += v[2:]
        else:raise AssertionError(argv)
        if cmd == self.omit_final:
            return subprocess.CompletedProcess(argv,1,'','Modem returned no final response; awaiting late reply')
        return subprocess.CompletedProcess(argv,0,data+'\nOK\n','')

    def test_mode_preserves_other_sim_and_primary(self):
        locks.CARD.write_text('1');self.tm=[134,3,1]
        locks.apply('mode','sa')
        self.assertEqual(self.tm,[134,128,1])
        self.assertEqual(locks.snapshot()['mode']['label'],'sa')

    def test_screen_default_bands_share_persistence_and_restart_once(self):
        locks.apply('bands_default','')
        self.assertEqual(self.restarts,1)
        self.assertEqual(self.restart_args,[['--bands']])
        self.assertEqual((locks.STATE/'lte').read_text(),','.join(map(str,locks.LTE)))
        self.assertEqual((locks.STATE/'nr').read_text(),'')
        self.assertEqual(locks.snapshot()['nr']['locked'],'')

    def test_nr_access_saves_one_combined_mode_for_replay(self):
        self.tm=[131,134,0]
        locks.apply('gran','sa')
        self.assertEqual((locks.STATE/'mode').read_text(),'5g4g')
        self.assertEqual(locks.snapshot()['mode']['label'],'5g4g')
        locks.apply('gran','nsa')
        self.assertEqual((locks.STATE/'mode').read_text(),'nsa')
        self.assertFalse((locks.STATE/'gran').exists())

    def test_scoped_state_migration_and_mode_preserve_data_card(self):
        base,run,marker=locks.STATE,locks.RUN,locks.MARKER
        (base/'lte').write_text('1,3');(base/'auto_apply').write_text('0')
        with patch.dict(locks.os.environ):
            locks.migrate_legacy(base)
            self.assertEqual((base/'sim0/lte').read_text(),'1,3')
            self.assertFalse((base/'sim1/lte').exists())
            locks.scope(1,base,run,marker)
            locks.apply('mode','sa')
            self.assertEqual(self.tm,[3,128,0])
            self.assertEqual(locks.CARD.read_text(),'0')
            self.assertEqual((base/'sim1/mode').read_text(),'sa')
            self.assertFalse((base/'sim0/mode').exists())
            self.assertEqual(locks.os.environ['MU300_SIM_SLOT'],'1')
            locks.CARD.write_text('1');locks.migrate_legacy(base)
            self.assertFalse((base/'sim1/lte').exists())

    def test_error_never_persists_or_claims_success(self):
        self.fail='AT+SPTESTMODE=134,134,0'
        result=locks.main(['apply','mode','auto'])
        self.assertEqual(result['state'],'error')
        self.assertIn('quarantined',result['error'])
        self.assertFalse((locks.STATE/'mode').exists())

    def test_ok_without_changed_readback_is_failure(self):
        self.ignore='AT+SPTESTMODE=134,134,0'
        self.assertEqual(locks.main(['apply','mode','auto'])['state'],'error')
        self.assertFalse((locks.STATE/'mode').exists())

    def test_endc_write_two_reads_zero(self):
        locks.apply('endc','off')
        self.assertEqual(locks.snapshot()['endc'],'0')
        self.assertEqual((locks.STATE/'endc').read_text(),'off')

    def test_voice_switches_save_per_sim_without_radio_cycle_or_data_switch(self):
        base, run, marker = locks.STATE, locks.RUN, locks.MARKER
        with patch.dict(locks.os.environ):
            locks.scope(1, base, run, marker)
            for kind, val in [('volte','off'), ('vonr','on')]:
                locks.apply(kind, val)
                self.assertEqual((base/f'sim1/{kind}').read_text(), val)
                self.assertFalse((base/f'sim0/{kind}').exists())
            self.assertFalse(self.voice['volte'])
            self.assertTrue(self.voice['vonr'])
            self.assertEqual(locks.CARD.read_text(), '0')
            self.assertEqual(self.restarts, 0)
            self.assertNotIn('AT+CASIMS=0', self.sent)

    def test_failed_voice_read_keeps_other_locks_but_disables_toggle(self):
        locks.apply('volte', 'off')
        def reject(command, timeout=8):
            if command == 'AT+CAVIMS?': raise RuntimeError('AT+CAVIMS?: ERROR')
            return original(command, timeout)
        original = locks.at
        with patch.object(locks, 'at', side_effect=reject):
            state = locks.snapshot(refresh_voice=True)
            self.assertEqual(state['mode']['label'], '4g')
            self.assertNotIn('ims', state)
            self.assertIsNone(state['volte']['enabled'])
            self.assertEqual(state['volte']['source'], 'unknown')
            self.assertIs(state['vonr']['enabled'], False)

    def test_voice_set_failure_never_saves_or_claims_success(self):
        self.omit_final = 'AT+CAVIMS=0'
        self.assertEqual(locks.main(['apply', 'volte', 'off'])['state'], 'error')
        self.assertFalse((locks.STATE/'volte').exists())
        self.assertFalse((locks.RUN/'volte-applied.json').exists())
        self.omit_final = None
        for kind, command in [('volte','AT+CAVIMS=0'), ('vonr','AT+SP5GCMDS="set nr param",45,1')]:
            self.voice = {'volte': True, 'vonr': False}
            self.ignore = command
            self.assertEqual(locks.main(['apply',kind,'off' if kind=='volte' else 'on'])['state'], 'error')
            self.assertFalse((locks.STATE/kind).exists())

    def test_voice_only_boot_replay_is_once_and_preserves_preferences(self):
        (locks.STATE/'ims').write_text('off')  # removed settings must be inert
        for kind, val in [('volte','off'), ('vonr','on')]:
            (locks.STATE/kind).write_text(val)
        result = locks.replay('early')
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['applied'], ['volte','vonr'])
        count = len(self.sent)
        self.assertEqual(locks.replay('early')['skipped'], 1)
        self.assertEqual(len(self.sent), count)
        self.assertEqual(self.restarts, 0)
        self.assertNotIn('AT+IMSEN?', self.sent)
        self.assertNotIn('AT+IMSEN=0', self.sent)
        self.assertEqual(self.sent.count('AT+CAVIMS=0'), 1)

    def test_removed_ims_is_rejected_and_old_preference_never_replayed(self):
        (locks.STATE/'ims').write_text('off')
        self.assertEqual(locks.replay('early')['skipped'], 1)
        with self.assertRaises(ValueError): locks.apply('ims', 'off')
        self.assertEqual(self.sent, [])

    def test_cavims_reports_native_state_not_saved_preference(self):
        (locks.STATE/'volte').write_text('off')
        state = locks.snapshot(refresh_voice=True)
        self.assertIs(state['volte']['enabled'], True)
        self.assertEqual(state['volte']['saved'], 'off')
        self.assertEqual(state['volte']['source'], 'modem')
        self.assertEqual(self.sent.count('AT+CAVIMS?'), 1)

    def test_malformed_voice_readback_cannot_be_saved_as_enabled(self):
        with patch.object(locks, 'value', return_value='get nr synch_param,41,1'):
            with self.assertRaisesRegex(RuntimeError, 'VoNR'): locks.read_voice('vonr')
        with patch.object(locks, 'value', return_value='get nr synch_param,42,2'):
            with self.assertRaisesRegex(RuntimeError, 'VoNR'): locks.read_voice('vonr')

    def test_cell_add_and_unlock_verified(self):
        locks.apply('cell','lte:3740,36')
        self.assertEqual(locks.snapshot()['cells'],['lte:3740,36'])
        locks.apply('cell','off-lte')
        self.assertEqual(locks.snapshot()['cells'],[])
        self.assertEqual((locks.STATE/'cell').read_text().strip(),'')

    def test_invalid_inputs_never_issue_at(self):
        for kind,val in [('mode','oops'),('lte','79'),('nr','6'),('cell','lte:12,900'),('cell','lte:1,1;AT')]:
            with self.assertRaises(ValueError):locks.apply(kind,val)
        self.assertEqual(self.sent,[])

    def test_failed_reads_do_not_replace_good_cache(self):
        old=locks.snapshot();self.fail='AT+SPTESTMODE?'
        result=locks.main(['get','fresh'])
        self.assertIn('error',result)
        self.assertEqual(locks.read_json(locks.RUN/'lock.json'),old)

    def test_worker_records_error_for_its_id(self):
        job='a'*32;locks.write_json(locks.job_path(job),{'id':job,'started':0,'state':'queued'})
        self.fail='AT+SPTESTMODE?'
        locks.main(['worker','mode','auto',job])
        self.assertEqual(locks.main(['status',job])['state'],'error')

    def test_disabled_replay_sends_nothing(self):
        (locks.STATE/'auto_apply').write_text('off')
        self.assertEqual(locks.replay('early')['skipped'],1)
        self.assertEqual(self.sent,[])

    def test_replay_verifies_then_marks_done_and_does_not_repeat(self):
        (locks.STATE/'mode').write_text('auto')
        (locks.STATE/'cell').write_text('lte:3740,36\nlte:3740,143\n')
        self.assertEqual(locks.replay('early')['state'],'done')
        self.assertTrue(locks.MARKER.exists())
        self.assertEqual(self.restarts,0)
        count=len(self.sent)
        self.assertEqual(locks.replay('early')['skipped'],1)
        self.assertEqual(len(self.sent),count)

    def test_matching_replay_avoids_writes_and_reconnect(self):
        (locks.STATE/'mode').write_text('4g')
        (locks.STATE/'endc').write_text('off')
        self.assertEqual(locks.replay('early')['applied'],[])
        self.assertEqual(self.restarts,0)
        self.assertNotIn('AT+SPENDC=2',self.sent)

    def test_replay_failure_does_not_mark_boot_complete(self):
        self.tm[0]=134;self.ignore='AT+SPTESTMODE=3,134,0'
        (locks.STATE/'mode').write_text('4g')
        result=locks.replay('early')
        self.assertEqual(result['state'],'error')
        self.assertIn('readback',result['error'])
        self.assertFalse(locks.MARKER.exists())
        self.assertEqual(locks.read_json(locks.RUN/'lock-replay.json')['state'],'error')

    def test_verify_checks_saved_values(self):
        (locks.STATE/'mode').write_text('auto')
        with self.assertRaises(RuntimeError): locks.main(['verify'])

    def test_early_replay_never_restarts_radio(self):
        (locks.STATE/'mode').write_text('auto')
        (locks.STATE/'cell').write_text('lte:3740,36')
        self.assertEqual(locks.replay('early')['state'],'done')
        self.assertEqual(self.restarts,0)

    def test_early_missing_ok_requires_matching_readback(self):
        self.endc=1;self.omit_final='AT+SPENDC=2'
        (locks.STATE/'endc').write_text('off')
        self.assertEqual(locks.replay('early')['state'],'done')
        self.assertEqual(self.sent.count('AT+SPENDC=2'),1)

    def test_early_missing_ok_with_unchanged_value_fails(self):
        self.omit_final=self.ignore='AT+SPTESTMODE=134,134,0'
        (locks.STATE/'mode').write_text('auto')
        self.assertEqual(locks.replay('early')['state'],'error')
        self.assertFalse(locks.MARKER.exists())

    def test_offline_reconnect_is_deferred_and_setting_is_saved(self):
        self.restart_result = (0, 'RECONNECT-DEFERRED failed\n', '')
        for kind, val in [('mode', 'auto'), ('lte', '1,3'), ('nr', '1,41,78'),
                          ('cell', 'lte:3740,36'), ('bands_default', '')]:
            with self.subTest(kind=kind):
                result = locks.main(['apply', kind, val])
                self.assertEqual(result['state'], 'done', result)
                self.assertEqual(result['reconnect'], 'deferred')
                self.assertEqual(result['reconnect_reason'], 'failed')
                self.assertTrue((locks.STATE / ('nr' if kind == 'bands_default' else kind)).exists())

    def test_reconnect_failure_does_not_lose_accepted_setting(self):
        self.restart_result = (1, '', 'Wrong state: modem in failed state')
        result = locks.main(['apply', 'mode', 'auto'])
        self.assertEqual(result['state'], 'done', result)
        self.assertEqual(result['reconnect'], 'failed')
        self.assertIn('failed state', result['reconnect_error'])
        self.assertEqual((locks.STATE/'mode').read_text(), 'auto')

    def test_reconnect_timeout_preserves_setting_and_reports_reconnect_failure(self):
        original = self.run_command
        def timeout(argv, **kwargs):
            if argv[0] == locks.RESTART: raise subprocess.TimeoutExpired(argv, 75)
            return original(argv, **kwargs)
        with patch.object(locks.subprocess, 'run', side_effect=timeout):
            result = locks.main(['apply', 'mode', 'auto'])
        self.assertEqual(result['state'], 'done', result)
        self.assertEqual(result['reconnect'], 'failed')
        self.assertEqual((locks.STATE/'mode').read_text(), 'auto')

    def test_interactive_missing_final_requires_exact_readback_without_resending(self):
        for kind, val, command in [('endc','on','AT+SPENDC=1'),
                                   ('mode','auto','AT+SPTESTMODE=134,134,0'),
                                   ('mode','sa','AT+SP5GRAN=1')]:
            with self.subTest(kind=kind, command=command):
                self.sent.clear()
                self.omit_final = command
                result = locks.main(['apply', kind, val])
                self.assertEqual(result['state'], 'done', result)
                self.assertEqual(self.sent.count(command), 1)
                self.assertTrue((locks.STATE/kind).exists())

    def test_interactive_missing_final_with_wrong_or_unreadable_state_is_failure(self):
        for fail_read in (False, True):
            with self.subTest(fail_read=fail_read):
                self.sent.clear(); self.endc = 0
                self.omit_final = self.ignore = 'AT+SPENDC=1'
                self.fail = 'AT+SPENDC?' if fail_read else None
                result = locks.main(['apply', 'endc', 'on'])
                self.assertEqual(result['state'], 'error', result)
                self.assertEqual(self.sent.count('AT+SPENDC=1'), 1)
                self.assertFalse((locks.STATE/'endc').exists())

    def test_unrelated_snapshot_failure_does_not_invalidate_verified_mode_or_endc(self):
        with patch.object(locks, 'snapshot', side_effect=RuntimeError('bands unavailable')):
            for kind, val in [('mode','auto'), ('endc','on')]:
                result = locks.main(['apply',kind,val])
                self.assertEqual(result['state'], 'done', result)
                self.assertEqual(result['refresh_error'], 'bands unavailable')
                self.assertEqual((locks.STATE/kind).read_text(), val)

    def test_interactive_band_without_ack_cannot_be_proven_by_readback(self):
        self.omit_final = 'AT+SPLBAND=2,1,0,272,0'
        result = locks.main(['apply', 'nr', '1,41,78'])
        self.assertEqual(result['state'], 'error', result)
        self.assertFalse((locks.STATE/'nr').exists())
        self.assertEqual(self.restarts, 0)
        self.assertEqual(self.restart_args, [])

    def test_explicit_endc_error_is_not_recovered_or_saved(self):
        original = self.run_command
        def reject(argv, **kwargs):
            if argv[-1] == 'AT+SPENDC=1':
                self.sent.append(argv[-1])
                return subprocess.CompletedProcess(argv, 1, 'ERROR\n', '')
            return original(argv, **kwargs)
        with patch.object(locks.subprocess, 'run', side_effect=reject):
            result = locks.main(['apply', 'endc', 'on'])
        self.assertEqual(result['state'], 'error', result)
        self.assertNotIn('AT+SPENDC?', self.sent)
        self.assertFalse((locks.STATE/'endc').exists())

    def test_nr_capability_count_is_not_a_band(self):
        self.assertEqual(locks.nr_capabilities(),[1,5,8,28,41,78])

    def test_automatic_nr_readback_uses_actual_capabilities(self):
        with patch.object(locks,'nr_capabilities',return_value=[3,77]),patch.object(locks,'band_state',return_value={'raw':'expanded','locked':'3,77'}):
            self.assertTrue(locks.verify('nr','','0,0,0,0'))
        self.assertTrue(locks.matches_saved('nr','',{'nr':{'locked':'3,77'},'caps':{'nr':'3,77'}}))
        self.assertFalse(locks.matches_saved('nr','',{'nr':{'locked':'1,78'},'caps':{'nr':'3,77'}}))

    def test_shared_caps_use_platform_lte_and_dynamic_nr(self):
        with patch.object(locks, 'LTE', [1,3,5,8,34,39,40,41]), patch.object(locks, 'value', return_value='get nr support_band,3,3,77,79'):
            self.assertEqual(locks.main(['caps']), {'lte':'1,3,5,8,34,39,40,41','nr':'3,77,79'})

    def test_nr_query_failure_never_invents_capabilities(self):
        self.fail = 'AT+SP5GCMDS="get nr support_band"'
        self.assertEqual(locks.main(['caps'])['nr'], '')
        locks.write_json(locks.RUN/'lock.json', {'caps': {'nr':''}})
        with self.assertRaisesRegex(ValueError, 'Unsupported band'):
            locks.validate('nr','78')
        locks.validate('nr','')  # Unlock remains available.

    def test_lte_only_caps_never_access_modem(self):
        self.assertEqual(locks.main(['caps','lte'])['lte'], ','.join(map(str,locks.LTE)))
        self.assertEqual(self.sent, [])

    def test_late_replay_is_refused_without_writes(self):
        with self.assertRaises(ValueError): locks.replay('late')
        self.assertEqual(self.sent,[])

    def test_mode_must_still_match_after_manual_reconnect(self):
        self.tm[0]=134;self.reset_mode_on_restart=True
        result=locks.main(['apply','mode','4g'])
        self.assertEqual(result['state'],'error')
        self.assertFalse((locks.STATE/'mode').exists())

    def test_band_acknowledged_with_different_readback_is_saved(self):
        for kind, val, command, key in [
                ('lte', '1,3', 'AT+SPLBAND=1,0,0,0,5,0', 0),
                ('nr', '1,41,78', 'AT+SPLBAND=2,1,0,272,0', 3)]:
            with self.subTest(kind=kind):
                self.ignore = command
                result = locks.main(['apply', kind, val])
                self.assertEqual(result['state'], 'done', result)
                self.assertEqual((locks.STATE/kind).read_text(), val)
                self.assertEqual(locks.read_json(locks.RUN/'lock.json')[kind], locks.band_state(kind))
                self.assertFalse(locks.matches_saved(kind, val, locks.snapshot()))

    def test_band_readback_may_change_after_reconnect(self):
        self.reset_bands_on_restart = True
        for kind, val in [('lte', '1,3'), ('nr', '1,41,78')]:
            result = locks.main(['apply', kind, val])
            self.assertEqual(result['state'], 'done', result)
            self.assertEqual((locks.STATE/kind).read_text(), val)
        self.assertEqual(self.restarts, 2)

    def test_band_only_status_refresh_failure_does_not_fail_accepted_write(self):
        with patch.object(locks, 'band_state', side_effect=RuntimeError('status unavailable')):
            self.assertEqual(locks.main(['apply', 'lte', '1,3'])['state'], 'done')
        self.assertEqual((locks.STATE/'lte').read_text(), '1,3')

    def test_band_command_failure_still_fails_without_persisting(self):
        self.fail = 'AT+SPLBAND=1,0,0,0,5,0'
        result = locks.main(['apply', 'lte', '1,3'])
        self.assertEqual(result['state'], 'error')
        self.assertFalse((locks.STATE/'lte').exists())
        self.assertEqual(self.restart_args, [])

    def test_each_band_write_cycles_only_after_acknowledgement(self):
        for kind, val, command in [('lte','1,3','AT+SPLBAND=1,0,0,0,5,0'),
                                    ('nr','1,41,78','AT+SPLBAND=2,1,0,272,0')]:
            for failure in (None, 'rejected', 'no-final'):
                with self.subTest(kind=kind,failure=failure):
                    self.fail = command if failure == 'rejected' else None
                    self.omit_final = command if failure == 'no-final' else None
                    self.restart_args.clear()
                    before = (locks.STATE/kind).read_text() if (locks.STATE/kind).exists() else None
                    result = locks.main(['apply',kind,val])
                    self.assertEqual(self.restart_args, [] if failure else [['--bands']])
                    self.assertEqual(result['state'], 'error' if failure else 'done')
                    if failure:
                        self.assertEqual((locks.STATE/kind).read_text() if (locks.STATE/kind).exists() else None, before)

    def test_default_band_failure_never_cycles_or_saves_partial_request(self):
        commands = ['AT+SPLBAND=1,' + ','.join(map(str, locks.masks(locks.LTE, locks.LTE_TABLES))),
                    'AT+SPLBAND=2,0,0,0,0']
        for command in commands:
            with self.subTest(command=command):
                self.fail = command
                result = locks.main(['apply','bands_default',''])
                self.assertEqual(result['state'], 'error')
                self.assertEqual(self.restart_args, [])
                self.assertFalse((locks.STATE/'lte').exists())
                self.assertFalse((locks.STATE/'nr').exists())

    def test_band_replay_accepts_normalized_mask_without_late_restart(self):
        (locks.STATE/'nr').write_text('1,41,78')
        self.ignore = 'AT+SPLBAND=2,1,0,272,0'
        result = locks.replay('early')
        self.assertEqual(result['state'], 'done', result)
        self.assertEqual(self.sent.count(self.ignore), 1)
        self.assertTrue(locks.MARKER.exists())
        self.assertEqual(self.restarts, 0)
        self.assertEqual(locks.main(['verify']), {'ok': 1})

    def test_band_replay_no_ack_is_not_proven_by_matching_old_mask(self):
        (locks.STATE/'nr').write_text('1,41,78')
        self.omit_final = 'AT+SPLBAND=2,1,0,272,0'
        result = locks.replay('early')
        self.assertEqual(result['state'], 'error', result)
        self.assertFalse(locks.MARKER.exists())
        self.assertEqual(self.restarts, 0)

    def test_default_bands_may_be_normalized_after_reconnect(self):
        self.reset_bands_on_restart = True
        locks.apply('bands_default', '')
        self.assertEqual(self.restarts, 1)
        self.assertEqual((locks.STATE/'lte').read_text(), ','.join(map(str, locks.LTE)))
        self.assertEqual((locks.STATE/'nr').read_text(), '')

if __name__=='__main__':unittest.main()

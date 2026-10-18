"""GUI compatibility helpers cannot consume the NDJSON pipe as terminal input."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.adapter import Adapter, debug_output
from backend.state import Cancelled, Context, RecoveryRequired, Store
from backend.service import Service

LEGACY = '''GUI = None
class Android:
    def call(self, *args, **kwargs): pass
def adb(*args, **kwargs): pass
def confirm(message, word='yes'):
    print(message)
    return input('Type yes to continue / 输入 yes 继续: ').strip() == word
def missing_option():
    return input('A missing required option: ')
'''


class GuiConfirmation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'OpenWrt-Installer.py').write_text(LEGACY,encoding='utf-8')
        self.store=Store(self.root/'state')
        self.record=self.store.create({}, {}, {'method':'part'}, {'method':'part','wipe':True})
        self.record['status']='running'
        self.events=[]
        self.ctx=Context(self.store,self.record,lambda k,d:self.events.append((k,d)))

    def adapter(self,kind,context=True):
        return Adapter({'path':str(self.root),'adapter':kind}, self.ctx if context else None)

    def test_old_gui_confirm_never_prints_or_reads_yes_for_both_adapters(self):
        for kind in ('e5','mu300'):
            with self.subTest(adapter=kind):
                adapter=self.adapter(kind)
                with patch('builtins.input',side_effect=AssertionError('Unexpected terminal input')),debug_output(self.ctx):
                    self.assertTrue(adapter.legacy.confirm('Userdata will be formatted and Android reset'))
                self.assertEqual(self.events,[])
                self.assertFalse((self.ctx.directory/'debug.ndjson').exists())
                self.assertTrue(self.record['plan']['wipe'])
                self.assertFalse(self.record['effects'])

    def test_unstructured_option_stops_without_printing_a_console_prompt(self):
        adapter=self.adapter('mu300')
        with patch('builtins.input',side_effect=AssertionError('Unexpected terminal input')),debug_output(self.ctx):
            with self.assertRaisesRegex(RecoveryRequired,'required GUI option'):
                adapter.legacy.missing_option()
        self.assertEqual(self.events,[])

    def test_confirmation_cannot_bypass_cancel_or_a_missing_gui_context(self):
        adapter=self.adapter('mu300')
        self.ctx.cancel=True
        with self.assertRaises(Cancelled):adapter.legacy.confirm('message')
        self.ctx.cancel=False
        adapter.legacy.GUI=None
        with self.assertRaises(RecoveryRequired):adapter.legacy.confirm('message')
        with self.assertRaises(RecoveryRequired):self.adapter('e5',context=False).legacy.confirm('message')

    def test_plain_cli_retains_its_own_typed_confirmation(self):
        from backend.adapter import load
        cli=load(self.root/'OpenWrt-Installer.py','plain_cli_confirmation_fixture')
        with patch('builtins.input',return_value='yes') as read,patch('sys.stdout',io.StringIO()):
            self.assertTrue(cli.confirm('CLI destructive warning'))
        read.assert_called_once()
        with patch('builtins.input',return_value='no'),patch('sys.stdout',io.StringIO()):
            self.assertFalse(cli.confirm('CLI destructive warning'))

    def test_gui_final_confirmation_is_still_required_before_starting_worker(self):
        service=Service(self.root,self.store,io.StringIO())
        service.adapters=Mock(side_effect=AssertionError('Unconfirmed plan reached installation'))
        with patch('backend.service.inspect_package',return_value={}):
            with self.assertRaisesRegex(ValueError,'Confirm the displayed plan'):
                service.dispatch({'protocol':1,'command':'start','params':{'transaction':self.record['id'],'confirmed':False}})
        service.adapters.assert_not_called()
        self.assertIsNone(service.worker)
        self.assertFalse(self.store.load(self.record['id'])['effects'])


if __name__=='__main__':unittest.main()

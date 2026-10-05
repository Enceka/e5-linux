#!/usr/bin/env python3
"""Mock the production sender. No modem, WAN or actual SMS is touched."""
import importlib.machinery, importlib.util
from pathlib import Path
import tempfile, unittest
from unittest.mock import patch
TOP=Path(__file__).resolve().parents[2]
path=TOP/'openwrt/overlay/usr/libexec/e5-sms-send'
loader=importlib.machinery.SourceFileLoader('sender',str(path));spec=importlib.util.spec_from_loader(loader.name,loader)
sender=importlib.util.module_from_spec(spec);loader.exec_module(sender)
r=sender.receiver
class Send(unittest.TestCase):
 def exercise(self,text,fail_at=None,ucs2=False):
  commands=[];queries=[];sent=0
  def execute(argv,timeout=12):
   nonlocal sent
   commands.append(argv)
   if argv[0]=='mmcli':return 'No calls were found'
   if argv[-1]=='AT+E5SMS=?':return '+E5SMS: 1'
   if argv[-1].startswith('AT+E5SMS=1,'):
    sent+=1
    if sent==fail_at:raise RuntimeError('+CMS ERROR: 313')
    return '+CMGS: '+str(sent)
   raise AssertionError(argv)
  def at(card,query):
   queries.append((card,query))
   if query=='CPIN?':return '+CPIN: READY'
   if query=='CSCA?':return '+CSCA: "'+('+8613800100500'.encode('utf-16-be').hex() if ucs2 else '+8613800100500')+'",145'
   return 'OK'
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);file=root/'text';file.write_text(text)
   with patch.object(r,'DATA',root/'data'),patch.object(r,'INBOX',root/'data/inbox.json'),patch.object(r,'RUN',root/'run'),patch.object(r,'current_card',return_value=0),patch.object(r,'execute',side_effect=execute),patch.object(r,'at',side_effect=at):
    result=sender.send('10010',str(file),1);inbox=r.inbox()
  self.assertEqual(queries[-1],(0,'CFUN?'))
  self.assertFalse(any('SPSWDATA' in q or 'CFUN=' in q for card,q in queries))
  self.assertFalse(any(any(word in ['e5-sim','ifdown','ifup'] for word in command) for command in commands))
  return result,inbox
 def test_send_from_other_sim_keeps_data_and_records_origin(self):
  result,inbox=self.exercise('test 中文')
  self.assertTrue(result['ok']);self.assertEqual(result['sim'],'SIM2')
  self.assertEqual(inbox['messages'][0]['card'],1);self.assertEqual(inbox['messages'][0]['direction'],'out')
 def test_multipart_partial_failure_does_not_retry_or_claim_success(self):
  result,inbox=self.exercise('中文'*200,2)
  self.assertFalse(result['ok']);self.assertEqual(result['submitted_parts'],1)
  self.assertFalse(result['retry_safe']);self.assertEqual(inbox['messages'],[])
 def test_ucs2_smsc_from_modemmanager_charset(self):
  result,inbox=self.exercise('test',ucs2=True)
  self.assertTrue(result['ok']);self.assertEqual(inbox['messages'][0]['sim'],'SIM2')
if __name__=='__main__':unittest.main()

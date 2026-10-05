#!/usr/bin/env python3
"""PDU, two-card state and origin tests; no modem or external webhook involved."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOP=Path(__file__).resolve().parents[2]
LIB=TOP/'openwrt/overlay/usr/lib/e5'
sys.path.insert(0,str(LIB))
import sms_pdu
path=TOP/'openwrt/overlay/usr/libexec/e5-sms-receive'
loader=importlib.machinery.SourceFileLoader('sms_receive',str(path))
spec=importlib.util.spec_from_loader(loader.name,loader)
receiver=importlib.util.module_from_spec(spec);loader.exec_module(receiver)

def ucs2(text,ref=None,part=1,total=2):
    # A fixture builder writes fields in TS 23.040 order, independent of decode().
    header=bytes([5,0,3,ref,total,part]) if ref is not None else b''
    user=header+text.encode('utf-16-be')
    return (b'\x00'+bytes([0x40 if header else 0,5,0x81,0x01,0x80,0xf6,0,8])+
            bytes.fromhex('62015091208523')+bytes([len(user)])+user).hex()

def incoming(text,index=1,ref=None,part=1,total=2):
    result=sms_pdu.decode(ucs2(text,ref,part,total))
    return {**result,'storage_index':index,'storage_status':0}


class Pdu(unittest.TestCase):
    def test_gsm7_known_packed_string(self):
        self.assertEqual(sms_pdu.septets(bytes.fromhex('E8329BFD4697D9EC37'),10),'hellohello')

    def test_ucs2_sender_timestamp_and_non_ascii(self):
        msg=sms_pdu.decode(ucs2('测试\n"&<中文>'))
        self.assertEqual(msg['text'],'测试\n"&<中文>')
        self.assertEqual(msg['number'],'10086')
        self.assertEqual(msg['time'],'2026-10-05T19:02:58+08:00')

    def test_multipart_out_of_order_and_missing_part(self):
        one=incoming('第一段',1,55,1);two=incoming('第二段',2,55,2)
        self.assertEqual(sms_pdu.assemble([two,one])[0]['text'],'第一段第二段')
        self.assertEqual(sms_pdu.assemble([two])[0]['state'],'receiving')

    def test_malformed_pdu_does_not_become_empty_sms(self):
        parts,errors=sms_pdu.listing('+CMGL: 1,0,,1\n\n0000\n')
        self.assertEqual(parts,[]);self.assertEqual(len(errors),1)

    def test_submit_known_gsm7_and_international_address(self):
        pdu=bytes.fromhex(sms_pdu.submit('+12345','hellohello',77)[0])
        self.assertEqual(pdu[:8],bytes.fromhex('00010005912143f5'))
        self.assertEqual(pdu[8:],bytes.fromhex('00000AE8329BFD4697D9EC37'))

    def test_submit_multipart_limits_unicode_surrogates_and_extension(self):
        for text,alphabet in [('中文'*100,8),('a'*400,0),('^'*160,0),('😀'*100,8)]:
            pdus=sms_pdu.submit('10086',text,0x1234)
            self.assertGreater(len(pdus),1)
            payloads=[]
            for part,hexpdu in enumerate(pdus,1):
                pdu=bytes.fromhex(hexpdu);self.assertEqual(pdu[1],0x41)
                self.assertEqual(pdu[9],alphabet);self.assertLessEqual(len(pdu[11:]),140)
                self.assertEqual(pdu[11:18],bytes([6,8,4,0x12,0x34,len(pdus),part]))
                payloads.append(sms_pdu.septets(pdu[11:],pdu[10]-8,56) if alphabet==0 else pdu[18:].decode('utf-16-be'))
            self.assertEqual(''.join(payloads),text)

    def test_submit_rejects_invalid_recipient_and_empty_text(self):
        for number,text in [('x;ATD','test'),('10086','')]:
            with self.assertRaises(ValueError):sms_pdu.submit(number,text)


class Inbox(unittest.TestCase):
    def fresh(self):
        return {'version':1,'next_id':receiver.MIN_ID,'initialized':[],'messages':[],'slots':{}}

    def test_old_messages_silent_then_each_card_alerts_once(self):
        data=self.fresh();old=sms_pdu.assemble([incoming('old')])
        for card in [0,1]:
            self.assertEqual(receiver.ingest(data,card,'identity-'+str(card),old,1),([],[]))
        new=sms_pdu.assemble([incoming('new',2)])
        ids=[]
        for card in [0,1]:
            alerts,forwards=receiver.ingest(data,card,'identity-'+str(card),new,2)
            self.assertEqual(len(alerts),1);self.assertEqual(alerts,forwards);ids+=alerts
            self.assertEqual(receiver.ingest(data,card,'identity-'+str(card),new,3),([],[]))
        self.assertNotEqual(*ids)
        self.assertEqual([m['sim'] for m in data['messages'] if m['id'] in ids],['SIM1','SIM2'])

    def test_restart_keeps_ids_and_does_not_forward_again(self):
        data=self.fresh();receiver.ingest(data,1,'card2',[],1)
        receiver.ingest(data,1,'card2',sms_pdu.assemble([incoming('fixture')]),2)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(receiver,'DATA',root/'data'),patch.object(receiver,'RUN',root/'run'),patch.object(receiver,'INBOX',root/'data/inbox.json'):
                with receiver.locked():receiver.save(data)
                restored=receiver.load()
                self.assertEqual(receiver.ingest(restored,1,'card2',sms_pdu.assemble([incoming('fixture')]),3),([],[]))
                self.assertEqual(restored['messages'][0]['id'],data['messages'][0]['id'])
                self.assertTrue((root/'run/unread').read_text().endswith(str(data['messages'][0]['id'])+'\n'))

    def test_multipart_keeps_id_and_forwards_only_when_complete(self):
        data=self.fresh();receiver.ingest(data,1,'card2',[],1)
        two=incoming('尾部',2,8,2);one=incoming('头部',1,8,1)
        alerts,forwards=receiver.ingest(data,1,'card2',sms_pdu.assemble([two]),2)
        identifier=data['messages'][0]['id'];self.assertEqual(forwards,[])
        alerts,forwards=receiver.ingest(data,1,'card2',sms_pdu.assemble([two,one]),3)
        self.assertEqual(data['messages'][0]['id'],identifier)
        self.assertEqual(forwards,[identifier]);self.assertEqual(data['messages'][0]['text'],'头部尾部')

    def test_sim_replacement_does_not_relabel_old_messages(self):
        data=self.fresh()
        receiver.ingest(data,0,'oldcard',sms_pdu.assemble([incoming('old')]),1)
        receiver.ingest(data,0,'newcard',sms_pdu.assemble([incoming('new')]),2)
        self.assertEqual(len(data['messages']),2)
        self.assertEqual(data['messages'][0]['identity'],'oldcard')
        self.assertTrue(all(m['historical'] for m in data['messages']))

    def test_scan_restores_selected_card_and_uses_modemmanager_owner(self):
        data=self.fresh();commands=[]
        def fake(card,query):
            commands.append((card,query))
            if query=='CCID?':return '+CCID: "89860012345678901234"'
            if query=='CNMI?':return '+CNMI: 0,0,0,1,0'
            if query=='CMGF?':return '+CMGF: 0'
            if query=='CMGL=4':return '+CMGL: 1,0,,10\n\n'+ucs2('模拟内容')+'\n'
            return 'OK'
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'load',return_value=data),patch.object(receiver,'save'),patch.object(receiver,'alert'),patch.object(receiver,'forward'),patch.object(receiver,'execute',return_value='No calls were found'),patch.object(receiver,'current_card',return_value=0),patch.object(receiver,'at',side_effect=fake):
            receiver.scan({1})
        self.assertIn((1,'CNMI=2,1,0,0,0'),commands)
        self.assertEqual(commands[-1],(0,'CFUN?'))
        self.assertEqual(data['messages'][0]['card'],1)

    def test_reused_storage_index_and_replaced_sim_are_never_deleted(self):
        data=self.fresh()
        receiver.ingest(data,1,'original',sms_pdu.assemble([incoming('original')]),1)
        identifier=data['messages'][0]['id']
        with patch.object(receiver,'load',return_value=data),patch.object(receiver,'at') as modem,patch.object(receiver,'save') as save,patch.object(receiver,'current_card',return_value=0):
            for identity in ['replacement','original']:
                with patch.object(receiver,'read_card',return_value=(identity,sms_pdu.assemble([incoming('another')]))):
                    with self.assertRaises(RuntimeError):receiver.delete_locked(identifier)
            self.assertFalse(any('CMGD=' in args[1] for args,kwargs in modem.call_args_list))
            save.assert_not_called()
            self.assertFalse(data['messages'][0].get('deleted',False))

    def test_delete_only_matching_parts_then_restores_context(self):
        data=self.fresh();live=sms_pdu.assemble([incoming('original',7)])
        receiver.ingest(data,1,'original',live,1)
        with patch.object(receiver,'load',return_value=data),patch.object(receiver,'read_card',return_value=('original',live)),patch.object(receiver,'at') as modem,patch.object(receiver,'save'),patch.object(receiver,'current_card',return_value=0):
            self.assertTrue(receiver.delete_locked(data['messages'][0]['id'])['ok'])
            self.assertEqual(modem.call_args_list[0].args,(1,'CMGD=7'))
            self.assertEqual(modem.call_args_list[-1].args,(0,'CFUN?'))

    def test_one_absent_card_does_not_block_other_inbox(self):
        data=self.fresh()
        def read(card,own):
            if card==0:raise RuntimeError('SIM identity unavailable')
            return 'card2',sms_pdu.assemble([incoming('fixture')])
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'load',return_value=data),patch.object(receiver,'save'),patch.object(receiver,'alert'),patch.object(receiver,'forward'),patch.object(receiver,'execute',return_value='No calls were found'),patch.object(receiver,'current_card',return_value=0),patch.object(receiver,'at'),patch.object(receiver,'read_card',side_effect=read):
            receiver.scan({0,1})
        self.assertFalse(data['slots']['0']['ok']);self.assertTrue(data['slots']['1']['ok'])
        self.assertEqual(data['messages'][0]['sim'],'SIM2')

    def test_sending_lock_defers_scan(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(receiver,'RUN',Path(directory)),patch.object(receiver,'scan_locked') as scan:
            with receiver.modem_locked() as acquired:
                self.assertTrue(acquired);receiver.scan({0,1})
            scan.assert_not_called()
            receiver.scan({0,1});scan.assert_called_once()


if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Run on OpenWrt with ucode: isolated counters, ledger and ubus object."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

source=Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='dual-traffic-') as directory:
    root=Path(directory)
    for name in ['data','run','net']: (root/name).mkdir()
    for name in ['traffic','traffic-core.uc']: shutil.copy(source/name,root/name)
    card=root/'card';card.write_text('0')
    def counters(slot,rx,tx,cid=1):
        dev=root/'net'/('sipa_eth'+str(slot*8+cid-1))
        (dev/'statistics').mkdir(parents=True,exist_ok=True)
        (dev/'ifindex').write_text(str(slot+50+cid-1))
        (dev/'statistics/rx_bytes').write_text(str(rx))
        (dev/'statistics/tx_bytes').write_text(str(tx))
    counters(0,1000,200);counters(1,3000,400)
    # Existing CID2 counters must not be charged again during ledger migration.
    counters(0,7000,700,2);counters(1,9000,900,2)
    day=time.strftime('%Y-%m-%d');month=day[:7]
    old={'version':1,'config':{'plan_name':'legacy','monthly_gb':20},'started_at':int(time.time()),
         'last':{'device':'sipa_eth0','boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'ifindex':50,'rx':1000,'tx':200,'at':int(time.time())},
         'days':{day:{'rx':12345,'tx':234}},'months':{month:{'rx':12345,'tx':234}},
         'pending_rx':0,'pending_tx':0,'adjustment':None}
    (root/'data/state.json').write_text(json.dumps(old))
    bus='test.dualtraffic.'+str(os.getpid())
    env={**os.environ,'MU300_TRAFFIC_DIR':str(root/'data'),'MU300_TRAFFIC_RUN':str(root/'run'),
         'MU300_TRAFFIC_SYS':str(root/'net'),'MU300_TRAFFIC_CARD':str(card),'MU300_TRAFFIC_BUS':bus}
    def rpc(method,args=None):
        return json.loads(subprocess.check_output(['ubus','call',bus,method,json.dumps(args or {})]))
    def start():
        proc=subprocess.Popen(['ucode',str(root/'traffic')],env=env,stderr=subprocess.PIPE)
        for _ in range(30):
            if proc.poll() is not None: raise AssertionError(proc.stderr.read().decode())
            result=subprocess.run(['ubus','call',bus,'get','{}'],capture_output=True)
            if result.returncode==0:return proc
            time.sleep(.1)
        proc.terminate();proc.wait();raise AssertionError('no ubus object')
    proc=start()
    try:
        first=rpc('get',{'slot':'0'});second=rpc('get',{'slot':'1'})
        assert first['days'][0]['rx']==12345 and second['days'][0]['rx']==0,(first,second)
        assert json.loads((root/'data/state-v1.json').read_text())==old
        counters(0,1100,220);counters(1,3300,440);rpc('flush')
        a=rpc('get',{'slot':'0'});b=rpc('get',{'slot':'1'})
        assert a['days'][0]['rx']==12445 and a['days'][0]['tx']==254,a
        assert b['days'][0]['rx']==300 and b['days'][0]['tx']==40,b
        assert rpc('set',{'slot':'1','payload':json.dumps({'plan_name':'second','monthly_gb':55})})['ok']==1
        assert rpc('get',{'slot':'0'})['config']['plan_name']=='legacy'
        assert rpc('get',{'slot':'1'})['config']['monthly_gb']==55
        assert rpc('get',{'slot':'2'})['error']=='invalid_slot'
        assert rpc('set',{'slot':'1','payload':'{"device":"sipa_eth0"}'})['ok']==0
        card.write_text('1');rpc('flush');assert rpc('get')['slot']==1
        assert json.loads((root/'run/view.json').read_text())['slot']==1
    finally:
        proc.terminate();proc.wait(timeout=5)
        errors=proc.stderr.read().decode()
        if errors:print(errors,flush=True)
    proc=start()
    try:
        assert rpc('get',{'slot':'0'})['days']==a['days']
        assert rpc('get',{'slot':'1'})['days']==b['days']
        assert rpc('get',{'slot':'1'})['config']['plan_name']=='second'
        for args in [{},{'slot':'2','confirm':True},{'slot':'0'},{'slot':'all','confirm':False}]:
            assert rpc('clear',args)['ok']==0,args
        # Calibrated usage is part of history, while plan settings survive clear.
        conf=rpc('get',{'slot':'0'})['config']
        assert rpc('set',{'slot':'0','payload':json.dumps({**conf,'used_gb':0.5})})['ok']==1
        assert rpc('clear',{'slot':'0','confirm':True})['ok']==1
        cleared=rpc('get',{'slot':'0'})
        assert cleared['config']==conf
        assert cleared['status']['today_used']==cleared['status']['month_used']==cleared['status']['cycle_used']==0
        assert rpc('get',{'slot':'1'})['days']==b['days']
        assert json.loads((root/'run/view-sim0.json').read_text())['today_used']==0
        counters(0,1170,229);rpc('flush')
        after=rpc('get',{'slot':'0'})
        assert after['status']['today']=={'rx':70,'tx':9},after
        # Failed persistence must not clear the live record or acknowledgement.
        (root/'data').rename(root/'saved-data')
        try:
            assert rpc('clear',{'slot':'0','confirm':True})=={'ok':0,'error':'storage_failed'}
            assert rpc('get',{'slot':'0'})['days']==after['days']
        finally:(root/'saved-data').rename(root/'data')
        stale=(root/'run/state.json').read_text()
        assert rpc('clear',{'slot':'all','confirm':True})['ok']==1
        for slot in ['0','1']:
            assert rpc('get',{'slot':slot})['status']['today_used']==0
        assert rpc('get',{'slot':'1'})['config']['plan_name']=='second'
    finally:
        proc.terminate();proc.wait(timeout=5)
        errors=proc.stderr.read().decode()
        if errors:print(errors,flush=True)
    # Simulate a crash between the durable commit and runtime checkpoint.
    (root/'run/state.json').write_text(stale)
    proc=start()
    try:
        for slot in ['0','1']:assert rpc('get',{'slot':slot})['status']['cycle_used']==0
        counters(1,3310,442);rpc('flush')
        assert rpc('get',{'slot':'1'})['status']['today']=={'rx':10,'tx':2}
        counters(0,7100,720,2);counters(1,9300,940,2);rpc('flush')
        assert rpc('get',{'slot':'0'})['status']['today']=={'rx':100,'tx':20}
        assert rpc('get',{'slot':'1'})['status']['today']=={'rx':310,'tx':42}
    finally:proc.terminate();proc.wait(timeout=5)
    (root/'run/state.json').unlink()
    proc=start()
    try:
        assert rpc('get',{'slot':'0'})['status']['today']=={'rx':100,'tx':20}
        assert rpc('get',{'slot':'1'})['status']['today']=={'rx':310,'tx':42}
    finally:proc.terminate();proc.wait(timeout=5)
    api=(Path(__file__).parent/'infoscreen/base/api.uc').read_text()
    def function(name):
        start=api.index('function '+name+'(')
        return api[start:api.index('\n}',start)+2]
    screen=root/'screen-counters.uc'
    screen.write_text("import {readfile,stat} from 'fs';\n" +
                      '\n'.join(function(name) for name in ('read_trim','read_num','sim_counters')).replace('/sys/class/net',str(root/'net')) +
                      '\nprint(sprintf("%J",[sim_counters(0),sim_counters(1),sim_counters(2)]));\n')
    result=json.loads(subprocess.check_output(['ucode',str(screen)]))
    assert result==[{'rx':8270,'tx':949},{'rx':12610,'tx':1382},{'rx':None,'tx':None}],result
print('PASS: isolated SIM/CID2 counters/migration, screen counters, explicit clear scopes, preserved plans, calibration reset, live counter baselines, write-failure rollback, warm/cold restart')

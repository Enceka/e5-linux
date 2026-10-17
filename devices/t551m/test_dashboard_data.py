"""Dashboard APN/CID/data-port regressions; only files and simulated transports."""
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

TOP=next(p for p in Path(__file__).resolve().parents if (p/'openwrt').is_dir())
LIB=next((TOP/'openwrt'/name/'root/usr/libexec/unisoc-modem') for name in ('luci-app-t551m','luci-app-mu300') if (TOP/'openwrt'/name).is_dir())


JSONFILTER_STUB='''#!/usr/bin/env python3
import json,sys
try:
    args=sys.argv[1:];value=json.loads(args[args.index('-s')+1]) if '-s' in args else json.load(sys.stdin)
    expr=args[args.index('-e')+1]
    if expr=='@["dns-server"][*]':values=value.get('dns-server',[])
    else:
        for key in expr.removeprefix('@.').split('.'):value=value[key]
        values=[value]
    for item in values:
        if isinstance(item,bool):print(str(item).lower())
        elif isinstance(item,(str,int,float)):print(item)
        else:sys.exit(1)
except (ValueError,KeyError,TypeError):sys.exit(1)
'''

@unittest.skipUnless(os.name!='nt' and shutil.which('sh'),'requires POSIX shells, simulated modem only')
class DashboardData(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bin=self.root/'bin';self.bin.mkdir()
        self.stub('jsonfilter',JSONFILTER_STUB)
        self.stub('uci','''#!/bin/sh
case "$*" in
 *unisoc_modem.main.data_interface) echo wan;;
 *unisoc_modem.main.data_device) echo sipa_eth0;;
 *network.wan.apn) echo stale.global;;
 *) exit 1;;
esac
''')
        self.stub('ubus','#!/bin/sh\nprintf \'%s\\n\' "$LATEST_WAN"\n')
        self.stub('ip','#!/bin/sh\nexit 0\n')
        self.stub('apn','#!/bin/sh\n[ "$1" = status ] || exit 9\nprintf \'%s\\n\' "$APN_STATE"\n')
        self.shells=[['sh']]
        if shutil.which('bash'):self.shells.append(['bash'])
        if shutil.which('busybox'):self.shells.append(['busybox','ash'])
        self.wan=json.dumps({'up':True,'l3_device':'sipa_eth3','proto':'modemmanager','uptime':42,'dns-server':[]},indent=2)
        self.state={'ok':1,'apn':'CMIOT5G','source':'sim','data_sim':0}

    def stub(self,name,text):
        p=self.bin/name;p.write_text(text);p.chmod(0o755)

    def run_shell(self,shell,code,**values):
        env=dict(os.environ,PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                 WAN=self.wan,LATEST_WAN=self.wan,APN_STATE=json.dumps(self.state),
                 DASH_NET_BIN=str(self.bin),MU300_SIM_SLOT='',MU300_POWER_LIB=str(LIB/'power-supply.sh'),
                 MU300_POWER_SUPPLY_DIR=str(self.root/'sys/class/power_supply'),MU300_POWER_DEVICE='mu300',AT_REPLY='+CGEQOSRDP: 4,8,0,0,0,0,524000,62000\r\nOK\r\n')
        env.update({key:str(value) for key,value in values.items()})
        prefix='. '+shlex.quote(str(LIB/'dashboard-network.sh'))+'\nt3() { "$@"; }\nt2() { "$@"; }\n'
        return subprocess.run(shell+['-c',prefix+code],env=env,capture_output=True,text=True,timeout=20)

    def test_live_device_beats_static_config_and_ignores_nested_inactive_fields(self):
        for shell in self.shells:
            for value,expected in (({'l3_device':'sipa_eth3','inactive':{'l3_device':'sipa_eth0'}},'sipa_eth3'),
                                   ({'device':'sipa_eth11'},'sipa_eth11'),({},'sipa_eth0')):
                r=self.run_shell(shell,'dash_data_device "$WAN" sipa_eth0',WAN=json.dumps(value,indent=2))
                self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),expected)

    def test_cid_mapping_uses_the_selected_sim_group(self):
        for shell in self.shells:
            for slot in range(2):
                for cid in range(1,9):
                    r=self.run_shell(shell,f'dash_data_cid sipa_eth{slot*8+cid-1} {slot}')
                    self.assertEqual(r.stdout.strip(),str(cid));self.assertEqual(r.returncode,0)
            for device,slot in [('sipa_eth8',0),('sipa_eth7',1),('sipa_eth16',1),('sipa_eth01',0),('wwan0',0),('../bad',0),('sipa_eth3','unknown')]:
                r=self.run_shell(shell,'dash_data_cid '+shlex.quote(device)+' '+shlex.quote(str(slot)))
                self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,'')

    def test_sim_selection_default_and_errors_are_distinguished_without_credentials(self):
        for shell in self.shells:
            for state,expected in ((self.state,'CMIOT5G'),({'ok':1,'apn':'3gnet','source':'auto','data_sim':0},'3gnet'),
                                   ({'ok':1,'apn':'','source':'default','data_sim':0},'(SIM default)')):
                r=self.run_shell(shell,'dash_apn "$DASH_NET_BIN/apn" 0',APN_STATE=json.dumps(state))
                self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),expected)
            for state in ({'ok':0},{'ok':1,'source':'default','data_sim':0},
                          {'ok':1,'apn':None,'source':'default','data_sim':0},
                          {'ok':1,'apn':'','source':'error','data_sim':0},
                          {**self.state,'data_sim':1},{**self.state,'apn':'bad\nAT+CFUN=0'}):
                r=self.run_shell(shell,'dash_apn "$DASH_NET_BIN/apn" 0',APN_STATE=json.dumps(state))
                self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,'')

    def qos_code(self,slot='0'):
        source=(LIB/'cell').read_text()
        fragment=source[source.index('qos_fragment() {'):source.index('# ---------------------------------------------------------- staged AT round')]
        return fragment+'\nat() { echo "$1" >> '+shlex.quote(str(self.root/'commands'))+'; printf \'%s\\n\' "$AT_REPLY"; }\nQOS=$(dash_active_qos "$WAN" '+slot+'); qos_fragment "$QOS"'

    def test_report_cid4_qci8_ambr_and_sim2_cid4_with_multirow_replies(self):
        for shell in self.shells:
            for slot,device in (('0','sipa_eth3'),('1','sipa_eth11')):
                (self.root/'commands').unlink(missing_ok=True)
                wan=json.dumps({'up':True,'l3_device':device,'uptime':42})
                reply='+CGEQOSRDP: 1,9,0,0,0,0,1,1\n+CGEQOSRDP: 4,8,0,0,0,0,524000,62000OK\n'
                r=self.run_shell(shell,self.qos_code(slot),WAN=wan,LATEST_WAN=wan,AT_REPLY=reply)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(json.loads(r.stdout),{'qci':8,'dl':524.0,'ul':62.0})
                self.assertEqual((self.root/'commands').read_text().strip(),'AT+CGEQOSRDP=4')

    def test_disconnected_missing_unknown_and_wrong_sim_devices_never_query_cid1(self):
        for shell in self.shells:
            for wan in ({'up':False,'l3_device':'sipa_eth3'}, {'up':True}, {'up':True,'l3_device':'wwan0'},
                        {'up':True,'l3_device':'sipa_eth11'}, {'up':True,'l3_device':'../../sipa_eth3'}):
                (self.root/'commands').unlink(missing_ok=True)
                r=self.run_shell(shell,self.qos_code(),WAN=json.dumps(wan))
                self.assertEqual(json.loads(r.stdout),None,r.stderr)
                self.assertFalse((self.root/'commands').exists())

    def test_reconnect_during_at_discards_old_context_without_querying_another(self):
        for shell in self.shells:
            for latest in ({'up':False,'l3_device':'sipa_eth3'},{'up':True,'l3_device':'sipa_eth4'}):
                (self.root/'commands').unlink(missing_ok=True)
                r=self.run_shell(shell,self.qos_code(),LATEST_WAN=json.dumps(latest))
                self.assertEqual(json.loads(r.stdout),None)
                self.assertEqual((self.root/'commands').read_text().strip(),'AT+CGEQOSRDP=4')

    def test_same_port_reconnect_and_missing_connection_age_discard_qos(self):
        for shell in self.shells:
            for slot,device in (('0','sipa_eth3'),('1','sipa_eth11')):
                before={'up':True,'l3_device':device,'uptime':3600}
                for age in (1,0,None,'bad',''):
                    latest={**before,'uptime':age}
                    r=self.run_shell(shell,self.qos_code(slot),WAN=json.dumps(before),LATEST_WAN=json.dumps(latest))
                    self.assertEqual(json.loads(r.stdout),None,(shell,slot,age,r.stderr))
                latest={**before};del latest['uptime']
                r=self.run_shell(shell,self.qos_code(slot),WAN=json.dumps(before),LATEST_WAN=json.dumps(latest))
                self.assertEqual(json.loads(r.stdout),None)
                for age in (3600,3602):
                    r=self.run_shell(shell,self.qos_code(slot),WAN=json.dumps(before),LATEST_WAN=json.dumps({**before,'uptime':age}))
                    self.assertEqual(json.loads(r.stdout),{'qci':8,'dl':524.0,'ul':62.0})
                del before['uptime']
                (self.root/'commands').unlink(missing_ok=True)
                r=self.run_shell(shell,self.qos_code(slot),WAN=json.dumps(before))
                self.assertEqual(json.loads(r.stdout),None)
                self.assertFalse((self.root/'commands').exists())

    def test_malformed_or_foreign_qos_does_not_publish_invalid_json(self):
        for shell in self.shells:
            for reply,expected in (('ERROR',None),('+CGEQOSRDP: 1,8,0,0,0,0,524000,62000',None),
                                   ('+CGEQOSRDP: 4,error,0,0,0,0,524000,62000',None),
                                   ('+CGEQOSRDP: 4,8,0,0,0,0,bad,-1',{'qci':8,'dl':None,'ul':None})):
                r=self.run_shell(shell,self.qos_code(),AT_REPLY=reply)
                self.assertEqual(json.loads(r.stdout),expected,r.stderr)

    def test_wan_block_and_real_counter_files_follow_changed_apn_and_cid_port(self):
        source=(LIB/'dashboard-info').read_text()
        json_helpers=source[source.index('n_or_null() {'):source.index('# ------------------------------------------------------------- temperature')]
        jval=source[source.index('jval() {'):source.index('# ----------------------------------------------------------------- WAN')]
        wan=source[source.index('cfg() {'):source.index('# ------------------------------------------------------------------- system')]
        counter=source[source.index('net_obj() {'):source.index('# ------------------------------------------------------------------- Wi-Fi')]
        counter=counter.replace('/sys/class/net',str(self.root/'net'))
        for device,rx in (('sipa_eth0',915819),('sipa_eth3',6717270)):
            d=self.root/'net'/device;(d/'statistics').mkdir(parents=True)
            (d/'statistics/rx_bytes').write_text(str(rx));(d/'statistics/tx_bytes').write_text('100');(d/'operstate').write_text('up' if device.endswith('3') else 'down')
        emit=source[source.index('MOBILE_NET=$(net_obj'):source.index('printf \'"wifi":')]
        emit='\nprintf \'{\'\n'+emit+'\nprintf \'"_end":true}\''
        code=json_helpers+'\n'+jval+'\n'+wan+'\nrd() { cat "$1"; }\n'+counter+emit
        for shell in self.shells:
            first=self.run_shell(shell,code);self.assertEqual(first.returncode,0,first.stderr)
            data=json.loads(first.stdout)
            self.assertEqual(data['wan']['apn'],'CMIOT5G')
            self.assertEqual((data['wan']['device'],data['wan']['up']),('sipa_eth3',1))
            self.assertEqual(data['net']['mobile'],{'rx':6717270,'tx':100,'up':1})
            (self.root/'net/sipa_eth3/statistics/rx_bytes').write_text('6746383')
            second=json.loads(self.run_shell(shell,code).stdout)
            self.assertEqual(second['net']['mobile']['rx']-data['net']['mobile']['rx'],29113)
            (self.root/'net/sipa_eth3/statistics/rx_bytes').write_text('6717270')
            compact={'up':True,'l3_device':'sipa_eth3','proto':'modemmanager','inactive':{'up':False,'l3_device':'sipa_eth0','proto':'old'}}
            nested=json.loads(self.run_shell(shell,code,WAN=json.dumps(compact)).stdout)
            self.assertEqual((nested['wan']['up'],nested['wan']['proto'],nested['wan']['device']),(1,'modemmanager','sipa_eth3'))

    def test_shared_helper_is_packaged_and_collectors_keep_existing_at_ownership(self):
        make=(LIB.parents[3]/'Makefile').read_text()
        self.assertIn('$(CP) ./root/. $(1)/',make)
        for name in ('dashboard-info','cell'):
            source=(LIB/name).read_text();self.assertIn('. "$DASH_NET_BIN/dashboard-network.sh"',source)
        self.assertNotIn("at 'AT+CGEQOSRDP=1'",(LIB/'cell').read_text())
        self.assertNotIn('AT+',(LIB/'dashboard-info').read_text())
        if (TOP/'tools/build-openwrt-tf-magisk.sh').exists():
            for name in ('build-openwrt-tf-magisk.sh','make-release.sh'):
                self.assertIn('./usr/libexec/unisoc-modem/dashboard-network.sh ',(TOP/'tools'/name).read_text())

    def snapshot_fixture(self):
        """Run the entire collector with private proc/sys files and fake RPCs."""
        source=(LIB/'dashboard-info').read_text()
        source=re.sub(r'/sys/|/proc/|/run/|/tmp/dhcp[.]leases|/etc/openwrt_release|/etc/mu300/vpn[.]conf',lambda m:str(self.root)+m[0],source)
        # BusyBox standalone ash can prefer its ip/date applets over PATH.
        # Absolute fixture paths keep all three shells fully isolated.
        for command in ('t2 ip ', 'if ip ', '|| ip '):
            source=source.replace(command,command[:-3]+shlex.quote(str(self.bin/'ip'))+' ')
        source=source.replace('$(date ', '$('+shlex.quote(str(self.bin/'date'))+' ')
        path=self.root/'dashboard-info';path.write_text(source)
        shutil.copyfile(LIB/'dashboard-network.sh',self.bin/'dashboard-network.sh')
        self.stub('boot-status','boot_status() { printf \'{"next":"android"}\'; }\n')
        self.stub('hotspot', '''#!/bin/sh
printf '%s\n' available 1 enabled 1 pending 0 up 1 section default_radio0 radio radio0 device wlan0 ssid FixtureWiFi channel 36 band 5g htmode HE80 country CN enc psk2 hidden 0
''')
        self.stub('ubus', '''#!/bin/sh
case "$*" in
 *network.interface.wan6*) printf '%s\n' '{"up":true,"dns-server":["2001:4860:4860::8888"]}';;
 *network.interface.wan*) printf '%s\n' "$LATEST_WAN";;
 *'system board') printf '{\n"model": "Fixture board"\n}\n';;
 *get_status) printf '%s\n' '{"status":"ENABLED"}';;
 *) exit 1;;
esac
''')
        self.stub('uci', '''#!/bin/sh
printf '%s\n' "$*" >> "$FIXTURE_ROOT/uci-calls"
case "$*" in
 *'show wireless') cat <<'EOF'
wireless.default_radio0.mode='ap'
wireless.default_radio0.device='radio0'
wireless.default_radio0.ssid='FixtureWiFi'
wireless.default_radio0.encryption='psk2'
wireless.default_radio0.hidden='0'
wireless.radio0.channel='36'
wireless.radio0.band='5g'
wireless.radio0.htmode='HE80'
wireless.radio0.country='CN'
EOF
 ;;
 *unisoc_modem.main.data_interface) echo wan;;
 *unisoc_modem.main.data_device) echo sipa_eth0;;
 *hostname) echo fixture-router;;
 *) exit 1;;
esac
''')
        self.stub('iw', '#!/bin/sh\nexit 0\n')
        self.stub('ip', '''#!/bin/sh
case "$*" in
 '-4 addr show br-lan') echo 'inet 192.168.1.1/24';;
 '-6 addr show sipa_eth3') echo 'inet6 2001:db8::2/64';;
 *) exit 1;;
esac
''')
        self.stub('date','#!/bin/sh\necho 1000\n')
        for name in ('mu300-at','t551m-at','at','ifup','ifdown'):
            self.stub(name,'#!/bin/sh\necho forbidden >> "$FIXTURE_ROOT/forbidden"\nexit 99\n')
        files={'proc/uptime':'123.45 5\n','proc/stat':'cpu 10 0 5 85 0 0 0 0\n',
               'proc/cpuinfo':'processor : 0\nprocessor : 1\n','proc/meminfo':'MemTotal: 1024 kB\nMemAvailable: 512 kB\n',
               'proc/sys/net/netfilter/nf_conntrack_count':'7\n','sys/module/sipc_wwan/parameters/card':'0\n',
               'sys/class/power_supply/battery/capacity':'73\n','sys/class/power_supply/battery/present':'1\n',
               'sys/class/power_supply/battery/status':'Charging\n','sys/class/power_supply/battery/voltage_now':'4100000\n',
               'sys/class/power_supply/battery/current_now':'-200000\n','sys/class/power_supply/usb/online':'1\n',
               'sys/class/thermal/thermal_zone0/type':'soc-thmzone\n','sys/class/thermal/thermal_zone0/temp':'42000\n',
               'etc/openwrt_release':"DISTRIB_DESCRIPTION='Fixture OpenWrt'\n",'tmp/dhcp.leases':'2000 aa:bb:cc:dd:ee:ff 192.168.1.2 fixture-client *\n',
               'run/unisoc-modem-traffic/view.json':'{"fixture":123}\n'}
        for device in ('sipa_eth0','sipa_eth3','br-lan','wlan0','usb0'):
            for name,value in (('rx_bytes','101'),('tx_bytes','202')):
                files[f'sys/class/net/{device}/statistics/{name}']=value+'\n'
            files[f'sys/class/net/{device}/operstate']='up\n'
        for name,value in files.items():
            f=self.root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(value)
        return path

    def test_full_snapshot_preserves_unrelated_fields_when_apn_fails(self):
        path=self.snapshot_fixture()
        for shell in self.shells:
            snapshots=[]
            for state in (self.state,{'ok':0,'error':'apn_identity'}):
                r=self.run_shell(shell,'. '+shlex.quote(str(path)),FIXTURE_ROOT=self.root,MU300_DASH_BIN=self.bin,APN_STATE=json.dumps(state))
                self.assertEqual(r.returncode,0,r.stderr)
                snapshots.append(json.loads(r.stdout))
            good,bad=snapshots
            self.assertEqual(good['wan']['apn'],'CMIOT5G');self.assertIsNone(bad['wan']['apn'])
            for field in ('cpu','mem','temps','power','wifi','lan','net','boot','traffic','vpn','conns'):
                self.assertEqual(good[field],bad[field],field)
            self.assertEqual(good['cpu']['total'],100);self.assertEqual(good['mem']['avail_kb'],512)
            self.assertEqual(good['power']['capacity'],73);self.assertEqual(good['temps']['soc'],42)
            self.assertEqual(good['wifi']['ssid'],'FixtureWiFi');self.assertEqual(good['wifi']['width'],'80 MHz')
            self.assertEqual(good['lan']['ip'],'192.168.1.1');self.assertEqual(good['lan']['list'][0]['host'],'fixture-client')
            self.assertEqual(good['traffic'],{'fixture':123});self.assertEqual(good['conns'],7)
            self.assertEqual(good['wan']['ip6'],'2001:db8::2')
            self.assertFalse((self.root/'forbidden').exists())
        self.assertTrue(all(line.startswith('-q get ') or line=='-q show wireless' for line in (self.root/'uci-calls').read_text().splitlines()))

    def test_stuck_apn_is_bounded_and_does_not_destroy_snapshot(self):
        path=self.snapshot_fixture()
        self.stub('apn','#!/bin/sh\nexec sleep 30\n')
        started=time.monotonic()
        r=self.run_shell(['sh'],'. '+shlex.quote(str(path)),FIXTURE_ROOT=self.root,MU300_DASH_BIN=self.bin)
        elapsed=time.monotonic()-started
        self.assertEqual(r.returncode,0,r.stderr);data=json.loads(r.stdout)
        self.assertIsNone(data['wan']['apn']);self.assertEqual(data['wifi']['ssid'],'FixtureWiFi')
        self.assertLess(elapsed,8,'APN status exceeded the existing 3-second deadline')


if __name__=='__main__':unittest.main()

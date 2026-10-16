"""Exercise the actual RPC counter/cache functions against files, never a modem."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[2] / 'openwrt/luci-app-t551m/root/usr/libexec/rpcd/mu300dash').read_text()

def function(name):
    start = SOURCE.index(name + '() {')
    end = SOURCE.index('\n}', start) + 2
    return SOURCE[start:end]

class RatesTest(unittest.TestCase):
    def test_uncached_fractional_counters_per_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'uptime').write_text('123.45 500.00\n')
            for slot, dev in enumerate(('sipa_eth0','sipa_eth8')):
                base=root/dev
                (base/'statistics').mkdir(parents=True)
                (base/'statistics/rx_bytes').write_text(str(1000+slot)+'\n')
                (base/'statistics/tx_bytes').write_text(str(500+slot)+'\n')
                (base/'ifindex').write_text(str(10+slot)+'\n')
            script=function('m_rates').replace('/proc/uptime',str(root/'uptime')).replace('/sys/class/net',str(root))+'\nm_rates\n'
            def read(slot):
                return json.loads(subprocess.check_output(['sh','-c',script],env=dict(os.environ,MU300_SIM_SLOT=str(slot))))
            a,b=read(0),read(1)
            self.assertEqual((a['ts'],a['net']['rx'],b['net']['rx']),(123.45,1000,1001))
            self.assertEqual((a['card'],b['card'],b['device']),(0,1,'sipa_eth8'))
            for name, rx, tx in [('sipa_eth1',200,20),('sipa_eth9',300,30)]:
                base=root/name
                (base/'statistics').mkdir(parents=True)
                (base/'statistics/rx_bytes').write_text(str(rx)+'\n')
                (base/'statistics/tx_bytes').write_text(str(tx)+'\n')
            self.assertEqual(read(0)['net'],{'rx':1200,'tx':520})
            self.assertEqual(read(1)['net'],{'rx':1301,'tx':531})
            (root/'sipa_eth0/statistics/rx_bytes').write_text('9000\n')
            self.assertEqual(read(0)['net']['rx'],9200)
            (root/'sipa_eth0/statistics/rx_bytes').write_text('bad\n')
            self.assertIn('error',read(0))
            (root/'sipa_eth8/statistics/tx_bytes').unlink()
            self.assertIsNone(read(1)['net'])

    def test_cache_refresh_boundaries_and_inflight_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('cell','sig'):(root/(name+'.json')).write_text('{}')
            ttl='\n'.join(line for line in SOURCE.splitlines() if line.startswith(('TTL=','TTL_FAST=')))
            for cage,sage,busy,expected in [(0,0,False,''),(4,1,False,'fast'),(5,0,False,'full'),(-1,-1,False,'full'),(5,5,True,'')]:
                with self.subTest(cage=cage,sage=sage,busy=busy):
                    launch=root/'launched'
                    launch.unlink(missing_ok=True)
                    pre=f'''{ttl}
CELL={root}/cell.json
SIGF={root}/sig.json
DASH=/unused
age_of() {{ case "$1" in */cell.json) echo {cage};; *) echo {sage};; esac; }}
collecting() {{ {'true' if busy else 'false'}; }}
fast_busy() {{ false; }}
setsid() {{ echo "${{2:-full}}" > {launch}; }}
'''
                    # cells mode skips sysinfo; use the status path with an empty
                    # stub executable to retain fast-tier scheduling.
                    subprocess.run(['sh','-c',pre+function('m_status')+'\nm_status\nwait\n'],check=True,stdout=subprocess.DEVNULL)
                    self.assertEqual(launch.read_text().strip() if launch.exists() else '',expected)

if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Check cold-start cleanup and bounded local readiness waits."""
from pathlib import Path
import subprocess
import unittest
SOURCE = (Path(__file__).resolve().parents[2] / 'ci/infoscreen/root/usr/libexec/e5-infoscreen/session').read_text()
class Session(unittest.TestCase):
    def cleanup(self, alive):
        block = SOURCE[SOURCE.index('CLIENTS='):SOURCE.index('on_term()')]
        harness = f"pidof() {{ return {0 if alive else 1}; }}\n" + """
killall() { echo "kill:$*"; }
sleep() { echo "sleep:$*"; }
""" + block + '\nstop_clients\n'
        return subprocess.check_output(['sh','-c',harness],text=True).splitlines()
    def test_cold_start_has_no_cleanup_sleep(self):
        self.assertEqual(self.cleanup(False), [])
    def test_existing_clients_keep_grace_then_forced_cleanup(self):
        self.assertEqual(self.cleanup(True), ['kill:-q cog WPEWebProcess WPENetworkProcess',
            'sleep:1', 'kill:-q -9 cog WPEWebProcess WPENetworkProcess'])
    def test_unavailable_api_wait_remains_bounded(self):
        start = SOURCE.index('i=0\n# (8088')
        block = SOURCE[start:SOURCE.index('# cog and its WebKit')]
        out = subprocess.check_output(['sh','-c',
            'grep() { return 1; }; sleep() { echo "$1"; };\n'+block.replace('/opt/e5/bin/busybox sleep', 'sleep')],text=True).splitlines()
        self.assertEqual(out, ['0.1'] * 100)
if __name__ == '__main__': unittest.main()

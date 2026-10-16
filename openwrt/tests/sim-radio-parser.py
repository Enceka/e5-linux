#!/usr/bin/env python3
"""Compile the production MM policy parser against GLib; no modem required."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

source=Path(sys.argv[1]).read_text()
start=source.index('static gboolean\nsim_radio_enabled (')
function=source[start:source.index('\n}\n',start)+3]
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); policy=root/'policy'
    c='#include <glib.h>\n#include <stdio.h>\n'+function.replace('/etc/e5/sim-radio',str(policy))+'''
int main(void) { printf("%d %d\\n",sim_radio_enabled(0),sim_radio_enabled(1)); }
'''
    (root/'test.c').write_text(c)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True))
    subprocess.run(['cc','-Wall','-Werror',str(root/'test.c'),'-o',str(root/'test'),*flags],check=True)
    def read(): return subprocess.check_output([str(root/'test')],text=True).strip()
    assert read()=='1 1'
    for a in (0,1):
        for b in (0,1):
            for ending in ('','\n'):
                policy.write_text(f'{a} {b}{ending}'); assert read()==f'{a} {b}'
    for bad in ('','1','1 2','1 1\n0','1 1\n\n','true false','1\t1'):
        policy.write_text(bad); assert read()=='0 0',repr(bad)
    policy.unlink();policy.mkdir();assert read()=='0 0'
    print('PASS: production MM RF policy parser: defaults, four combinations, malformed and unreadable policies')

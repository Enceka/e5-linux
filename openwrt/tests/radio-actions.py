#!/usr/bin/env python3
"""Both real RPC routers must return RF jobs, not blind detached success."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile

repos = [Path(__file__).resolve().parents[2], *map(Path, sys.argv[1:])]
for repo in repos:
    app = 'luci-app-t551m' if (repo/'openwrt/luci-app-t551m').is_dir() else 'luci-app-mu300'
    source = (repo/'openwrt'/app/'root/usr/libexec/rpcd/mu300dash').read_text()
    function = re.search(r'^m_act\(\) \{.*?^\}', source, re.M|re.S)[0]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('action','data-sim'):
            script = root/name
            script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$TRACE"\nprintf \'{"ok":true,"id":"rf-job","state":"running"}\\n\'\n')
            script.chmod(0o755)
        for argument, expected in [('on','1'),('off','0')]:
            trace = root/'trace'
            environment = dict(os.environ,DASH=str(root),TRACE=str(trace),MU300_SIM_SLOT='1',ARG=argument)
            body = 'inp(){ case $1 in @.op) echo radio;; @.arg) echo "$ARG";; esac; }\n'+function+'\nm_act\n'
            result = subprocess.run(['sh','-c',body],env=environment,capture_output=True,text=True,check=True)
            assert json.loads(result.stdout)['id']=='rf-job',result
            wanted = 'radio '+argument if app=='luci-app-t551m' else 'start radio-1-'+expected
            assert trace.read_text().strip()==wanted,trace.read_text()
        environment['ARG']='invalid'
        trace.unlink()
        result = subprocess.run(['sh','-c',body],env=environment,capture_output=True,text=True,check=True)
        assert not json.loads(result.stdout)['ok'] and not trace.exists()
        allowed=root/'radio-allowed'
        allowed.write_text('#!/bin/sh\nexit 1\n');allowed.chmod(0o755)
        environment['MU300_RADIO_ALLOWED']=str(allowed)
        body=body.replace('echo radio','echo modem-reset')
        result=subprocess.run(['sh','-c',body],env=environment,capture_output=True,text=True,check=True)
        assert not json.loads(result.stdout)['ok'] and not trace.exists()
    print('PASS RF action job receipts, explicit slot and invalid request:',repo.name)

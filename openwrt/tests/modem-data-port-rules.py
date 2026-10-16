#!/usr/bin/env python3
"""Exercise SIPA rules with MM's actual non-udev string matcher."""
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

src=Path(sys.argv[1])
helper=(src/'kerneldevice/mm-kernel-device-helpers.c').read_text()
start=helper.index('static gchar *\nbuild_string_match_pattern (')
end=helper.index('\n}\n',helper.index('mm_kernel_device_generic_string_match (',start))+3
rules=(src/'plugins/unisoc/77-mm-unisoc-sipc.rules').read_text()
patterns=re.findall(r'SUBSYSTEM=="net", KERNEL=="([^"]+)", ENV\{(ID_MM_UNISOC_SIPC|ID_MM_PHYSDEV_UID)\}="([^"]+)"',rules)
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    code='#include <glib.h>\n#include <string.h>\n#define mm_obj_dbg(...) ((void)0)\n#define mm_obj_warn(...) ((void)0)\n'+helper[start:end]
    code+='\nint main(int argc,char **argv){return mm_kernel_device_generic_string_match(argv[1],argv[2],NULL)?0:1;}\n'
    (root/'match.c').write_text(code)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True))
    subprocess.run(['cc','-Wall','-Werror',str(root/'match.c'),'-o',str(root/'match'),*flags],check=True)
    def match(name,pattern):return subprocess.run([str(root/'match'),name,pattern]).returncode==0
    assert not match('sipa_eth0','sipa_eth[0-9]|sipa_eth1[0-5]'), 'Baseline reproducer changed'
    for number in range(16):
        properties={key:value for pattern,key,value in patterns if match('sipa_eth'+str(number),pattern)}
        assert properties=={'ID_MM_UNISOC_SIPC':'1','ID_MM_PHYSDEV_UID':'unisoc-sipc'},(number,properties)
    for name in ('sipa_eth16','sipa_eth99','usb0','sipa_eth','sipa_eth0other'):
        assert not any(match(name,p) for p,_,_ in patterns),name
print('PASS: actual MM matcher tags all 16 SIPA ports, excludes unrelated ports; old bracket/alternation rule reproduced')

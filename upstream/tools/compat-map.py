#!/usr/bin/env python3
"""Enabled nodes of the live DTB -> which tree has a driver for their compatible."""
import re, subprocess, sys, collections
dts = open(sys.argv[1]).read().splitlines()
ml, vendor = sys.argv[2], sys.argv[3]
nodes, stack = [], []
for line in dts:
    s = line.strip()
    m = re.match(r'^(?:[\w-]+:\s*)?([\w@,.+-]+|/)\s*\{', s)
    if m:
        stack.append({'name': m.group(1), 'compat': [], 'status': 'okay'}); continue
    if s.startswith('};') and stack:
        n = stack.pop(); n['path'] = '/'.join(x['name'] for x in stack[1:] + [n]); nodes.append(n); continue
    if stack and s.startswith('compatible ='):
        stack[-1]['compat'] = re.findall(r'"([^"]+)"', s)
    if stack and s.startswith('status ='):
        stack[-1]['status'] = re.findall(r'"([^"]+)"', s)[0]
def grep(tree, c):
    r = subprocess.run(['git', '-C', tree, 'grep', '-l', '-F', f'"{c}"', '--', '*.c'], capture_output=True, text=True)
    return [f for f in r.stdout.split() if not f.startswith(('Documentation', 'arch/arm64/boot/dts', 'scripts'))]
seen = collections.OrderedDict()
for n in nodes:
    if n['status'] not in ('okay', 'ok') or not n['compat']:
        continue
    key = tuple(n['compat'])
    seen.setdefault(key, []).append(n['path'])
skip = re.compile(r'^(arm,|simple-bus|syscon$|fixed-|regulator-fixed|gpio-keys|shared-dma-pool|ramoops|linux,|pwm-backlight|simple-mfd)')
for key, paths in seen.items():
    mlf = vf = None
    for c in key:
        mlf = mlf or grep(ml, c) and (c, grep(ml, c)[0])
    for c in key:
        vf = vf or grep(vendor, c) and (c, grep(vendor, c)[0])
    tag = 'ML ' if mlf else ('VEN' if vf else '---')
    if skip.match(key[0]) and mlf: continue
    print(f"{tag} {key[0]:<42} x{len(paths):<3} ml={mlf[1] if mlf else '-'}  ven={vf[1] if vf else '-'}")

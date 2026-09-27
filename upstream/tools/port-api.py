#!/usr/bin/env python3
"""The mechanical part of moving a Unisoc 5.15 driver to 6.18: kernel API renames and signature changes that
have exactly one right answer.  Everything else (cfg80211 ops, removed interfaces) is done by hand, in the
driver's own commit.

usage: port-api.py file.c|dir ...        (prints every file it changes and what)

  class_create(THIS_MODULE, n)       -> class_create(n)                         (6.4)
  del_timer[_sync](t)                -> timer_delete[_sync](t)                  (6.15)
  from_timer(v, t, f)                -> timer_container_of(v, t, f)             (6.16)
  PDE_DATA(i)                        -> pde_data(i)                             (5.17)
  x = wakeup_source_create(n); wakeup_source_add(x);   -> x = wakeup_source_register(NULL, n);
  wakeup_source_remove(x) [+ wakeup_source_destroy(x)]  -> wakeup_source_unregister(x);
  static int <remove>(struct platform_device *) -> void                         (6.11, remove-void.py)
  and the headers 5.15 included through others (of.h, of_platform.h, vmalloc.h) where their functions are used
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


INCLUDES = [
    (['of_find_device_by_node', 'devm_of_platform_populate', 'of_platform_populate', 'of_platform_depopulate'],
     'linux/of_platform.h'),
    (['sched_setscheduler', 'sched_setattr'], 'linux/soc/sprd/unisoc_compat.h'),
    (['vmap', 'vunmap', 'vmalloc', 'vzalloc', 'vfree', 'VM_MAP'], 'linux/vmalloc.h'),
    (['of_property_read_u32', 'of_property_read_string', 'of_get_property', 'of_find_node_by_path',
      'of_property_read_bool', 'of_find_compatible_node'], 'linux/of.h'),
]


def port(path):
    s = orig = open(path, encoding='utf-8', errors='surrogateescape').read()
    done = []

    def sub(pat, rep, what, flags=0):
        nonlocal s
        s, n = re.subn(pat, rep, s, flags=flags)
        if n:
            done.append(f'{what} x{n}')

    sub(r'\bclass_create\(\s*THIS_MODULE\s*,\s*', 'class_create(', 'class_create')
    sub(r'\bdel_timer_sync\(', 'timer_delete_sync(', 'del_timer_sync')
    sub(r'\bdel_timer\(', 'timer_delete(', 'del_timer')
    sub(r'\bfrom_timer\(', 'timer_container_of(', 'from_timer')
    sub(r'\bPDE_DATA\(', 'pde_data(', 'PDE_DATA')
    # wakeup sources: create + add -> register, remove + destroy -> unregister
    sub(r'\bwakeup_source_create\(', 'wakeup_source_register(NULL, ', 'wakeup_source_create')
    sub(r'^[ \t]*wakeup_source_add\([^;]*\);[ \t]*\n', '', 'wakeup_source_add', re.M)
    # remove (+ destroy) of one source -> unregister: the vendor code often only removes
    for var in sorted(set(re.findall(r'\bwakeup_source_remove\(([^;]*)\);', s))):
        sub(r'^([ \t]*)wakeup_source_destroy\(%s\);[ \t]*\n' % re.escape(var), '', 'wakeup_source_destroy', re.M)
    sub(r'\bwakeup_source_remove\(', 'wakeup_source_unregister(', 'wakeup_source_remove')
    sub(r'\bwakeup_source_destroy\(', 'wakeup_source_unregister(', 'wakeup_source_destroy')
    # headers 5.15 pulled in through others: added after the file's first #include <...>
    for syms, hdr in INCLUDES:
        if re.search(r'\b(%s)\b' % '|'.join(syms), s) and f'<{hdr}>' not in s and path.endswith('.c'):
            m = re.search(r'^#include <[^>]+>\n', s, re.M)
            if m:
                s = s[:m.start()] + f'#include <{hdr}>\n' + s[m.start():]
                done.append(f'+{hdr}')
    if s != orig:
        open(path, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    # a platform driver's remove
    m = re.search(r'\.remove\s*=\s*(\w+)\s*,', s)
    if m and re.search(r'^static int %s\(struct platform_device \*\w+\)' % m.group(1), s, re.M):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'remove-void.py'), path, m.group(1)],
                           capture_output=True, text=True)
        done.append(f'remove {m.group(1)} -> void' if r.returncode == 0 else f'REMOVE BY HAND: {r.stderr.strip()}')
    if done:
        print(f'{path}: ' + ', '.join(done))


for arg in sys.argv[1:]:
    files = [arg] if os.path.isfile(arg) else [os.path.join(d, f) for d, _, fs in os.walk(arg) for f in fs
                                               if f.endswith('.c') or f.endswith('.h')]
    for f in sorted(files):
        port(f)

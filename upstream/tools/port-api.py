#!/usr/bin/env python3
"""The mechanical part of moving a Unisoc 5.15 driver to 6.18: kernel API renames and signature changes that
have exactly one right answer.  Everything else (cfg80211 ops, removed interfaces) is done by hand, in the
driver's own commit.

usage: port-api.py file.c|dir ...        (prints every file it changes and what)

  class_create(THIS_MODULE, n)       -> class_create(n)                         (6.4)
  del_timer[_sync](t)                -> timer_delete[_sync](t)                  (6.15)
  from_timer(v, t, f)                -> timer_container_of(v, t, f)             (6.16)
  PDE_DATA(i)                        -> pde_data(i)                             (5.17)
  _copy_to_user/_copy_from_user     -> copy_to_user/copy_from_user (not exported on arm64)
  eth_random_addr(n->dev_addr) -> eth_hw_addr_random(n), ether_addr_copy(n->dev_addr, a) -> eth_hw_addr_set(n, a)
  strlcpy -> strscpy, prandom_u32() -> get_random_u32(), random_ether_addr -> eth_random_addr
  napi_reschedule -> napi_schedule (6.8), netif_napi_add(d, n, p, w) -> netif_napi_add_weight (6.1)
  hrtimer_init(&t, c, m); t.function = f;  -> hrtimer_setup(&t, f, c, m);      (6.15)
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
    (['netdev_rx_queue'], 'net/netdev_rx_queue.h'),
    (['vmap', 'vunmap', 'vmalloc', 'vzalloc', 'vfree', 'VM_MAP'], 'linux/vmalloc.h'),
    (['of_property_read_u32', 'of_property_read_string', 'of_get_property', 'of_find_node_by_path',
      'of_property_read_bool', 'of_find_compatible_node', 'of_device_id', 'of_match_ptr'], 'linux/of.h'),
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
    sub(r'\bstrlcpy\(', 'strscpy(', 'strlcpy')
    # arm64 inlines _copy_{to,from}_user (INLINE_COPY_*): modules cannot link the underscore versions
    sub(r'\b_copy_(to|from)_user\(', r'copy_\1_user(', '_copy_*_user')
    # networking: napi_schedule() returns whether it scheduled since 6.8; the weighted napi add (6.1)
    sub(r'\bnapi_reschedule\(', 'napi_schedule(', 'napi_reschedule')
    sub(r'\bnetif_napi_add\(([^;]*?),([^;]*?),([^;]*?),([^;]*?)\);', r'netif_napi_add_weight(\1,\2,\3,\4);', 'netif_napi_add(4 args)')
    # dev_addr is const since 5.17: the helpers that set it
    sub(r'\b(?:random_ether_addr|eth_random_addr)\(\s*([\w.>-]+?)->dev_addr\s*\)', r'eth_hw_addr_random(\1)', 'random dev_addr')
    sub(r'\bether_addr_copy\(\s*(?:\(u8 \*\))?([\w.>-]+?)->dev_addr\s*,', r'eth_hw_addr_set(\1,', 'ether_addr_copy(dev_addr)')
    sub(r'\brandom_ether_addr\(', 'eth_random_addr(', 'random_ether_addr')
    sub(r'\bprandom_u32\(\)', 'get_random_u32()', 'prandom_u32')
    # hrtimer_init() + .function = f  ->  hrtimer_setup()                       (6.15)
    sub(r'\bhrtimer_init\(\s*&([^,]+?),\s*([^,]+?),\s*([^)]+?)\);(\s*\n\s*)\1\.function\s*=\s*([\w]+);',
        r'hrtimer_setup(&\1, \5, \2, \3);', 'hrtimer_init+function')
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
            else:
                # a file with only local headers: after the first of them
                m = re.search(r'^#include "[^"]+"\n', s, re.M)
                if m:
                    s = s[:m.end()] + f'#include <{hdr}>\n' + s[m.end():]
                    done.append(f'+{hdr}')
    if s != orig:
        open(path, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    # a platform driver's remove
    m = re.search(r'\.remove\s*=\s*(\w+)\s*,', s)
    if m and re.search(r'^static\s+int\s+%s\(struct platform_device \*\w+\)' % m.group(1), s, re.M):
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

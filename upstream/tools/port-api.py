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
  pwm_apply_state -> pwm_apply_might_sleep, dma_buf_map -> iosys_map, vm_flags |= / &= ~ -> vm_flags_set/clear,
  const bin_attribute callbacks and arrays
  strlcpy -> strscpy, prandom_u32() -> get_random_u32(), random_ether_addr -> eth_random_addr
  napi_reschedule -> napi_schedule (6.8), netif_napi_add(d, n, p, w) -> netif_napi_add_weight (6.1)
  hrtimer_init(&t, c, m); t.function = f;  -> hrtimer_setup(&t, f, c, m);      (6.15)
  x = wakeup_source_create(n); wakeup_source_add(x);   -> x = wakeup_source_register(NULL, n);
  wakeup_source_remove(x) [+ wakeup_source_destroy(x)]  -> wakeup_source_unregister(x);
  static int <remove>(struct platform_device *) -> void                         (6.11, remove-void.py)
  i2c: probe(client, id) -> probe(client) (6.3), int remove -> void (6.1)
  and the headers 5.15 included through others (of.h, of_platform.h, vmalloc.h, platform_device.h, the DRM
  ones) where their functions are used
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
      'of_property_read_bool', 'of_find_compatible_node', 'of_device_id', 'of_match_ptr', 'device_node'],
     'linux/of.h'),
    (['platform_device', 'platform_get_drvdata', 'platform_get_resource', 'platform_driver'],
     'linux/platform_device.h'),
    # DRM headers 5.15's drm_crtc.h and friends pulled in
    (['drm_framebuffer'], 'drm/drm_framebuffer.h'),
    (['DRM_MODE_BLEND_PIXEL_NONE', 'DRM_MODE_BLEND_COVERAGE', 'DRM_MODE_BLEND_PREMULTI', 'drm_plane_create_zpos_property',
      'drm_plane_create_zpos_immutable_property', 'drm_plane_create_alpha_property',
      'drm_plane_create_blend_mode_property', 'drm_plane_create_rotation_property'], 'drm/drm_blend.h'),
    (['edid', 'drm_edid'], 'drm/drm_edid.h'),
    (['input_dev', 'input_report_key', 'input_sync', 'input_set_capability', 'devm_input_allocate_device',
      'input_register_device', 'input_allocate_device'], 'linux/input.h'),
    (['of_get_gpio', 'of_get_named_gpio'], 'linux/of_gpio.h'),
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
    sub(r'\bpwm_apply_state\(', 'pwm_apply_might_sleep(', 'pwm_apply_state')
    sub(r'\bno_llseek\b', 'noop_llseek', 'no_llseek')
    # sysfs binary attributes are const (6.13-6.17): the read/write callbacks and the groups' arrays
    sub(r'(struct file\s*\*\s*\w+\s*,\s*struct kobject\s*\*\s*\w+\s*,\s*)struct bin_attribute\s*\*',
        r'\1const struct bin_attribute *', 'bin_attribute callback')
    sub(r'\bstatic struct bin_attribute\s*\*\s*(\w+)\[\]', r'static const struct bin_attribute *const \1[]',
        'bin_attribute array')
    # vma->vm_flags is read-only (6.3)
    sub(r'\b(\w+)->vm_flags\s*\|=\s*([^;]+);', r'vm_flags_set(\1, \2);', 'vm_flags |=')
    sub(r'\b(\w+)->vm_flags\s*&=\s*~\s*([^;]+);', r'vm_flags_clear(\1, \2);', 'vm_flags &= ~')
    # struct dma_buf_map is struct iosys_map (5.18), with all its helpers
    sub(r'<linux/dma-buf-map\.h>', '<linux/iosys-map.h>', 'dma-buf-map.h')
    sub(r'\bdma_buf_map', 'iosys_map', 'dma_buf_map')
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
        if hdr.startswith('drm/') and not re.search(r'\bdrm_', s):
            continue
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
    # an i2c driver's probe takes no device id since 6.3: i2c_client_get_device_id() where the body used it
    for name in re.findall(r'struct i2c_driver\s+\w+\s*=\s*\{[^;]*?\.probe\s*=\s*(\w+)', s, re.S):
        pat = (r'^((?:static\s+)?int\s+%s\s*\(\s*struct i2c_client\s*\*\s*(\w+))\s*,\s*'
               r'const struct i2c_device_id\s*\*\s*(\w+)\s*\)' % name)
        m = re.search(pat + r'\s*\{\n', s, re.M)
        if m:
            j = s.index('\n}\n', m.end())
            uses = re.search(r'\b%s\b' % m.group(3), s[m.end():j])
            decl = f'\tconst struct i2c_device_id *{m.group(3)} = i2c_client_get_device_id({m.group(2)});\n\n' if uses else ''
            s = s[:m.start()] + m.group(1) + ')\n{\n' + decl + s[m.end():]
            s = re.sub(pat + r';', r'\1);', s, flags=re.M)
            done.append(f'i2c probe {name} without id')
    if s != orig:
        open(path, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    # an i2c driver's remove
    for name in re.findall(r'struct i2c_driver\s+\w+\s*=\s*\{[^;]*?\.remove\s*=\s*(\w+)', s, re.S):
        if re.search(r'^static\s+int\s+%s\(struct i2c_client \*\w+\)' % name, s, re.M):
            r = subprocess.run([sys.executable, os.path.join(HERE, 'remove-void.py'), path, name],
                               capture_output=True, text=True)
            done.append(f'i2c remove {name} -> void' if r.returncode == 0 else f'REMOVE BY HAND: {r.stderr.strip()}')
            s = open(path, encoding='utf-8', errors='surrogateescape').read()
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

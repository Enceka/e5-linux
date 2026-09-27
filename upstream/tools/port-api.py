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
  asoc_rtd_to_cpu/codec, asoc_substream_to_rtd -> snd_soc_*, asoc_simple_* -> simple_util_* (6.8),
  a DAI driver's .probe/.remove -> its ops', DAIFMT_CBM/CBS_CFM/CFS -> CBP/CBC_CFP/CFC, snd_soc_of_get_dai_name(np, name, 0)
  syscore_ops -> struct syscore + register_syscore() (6.18), gpio_set_debounce -> gpiod_set_debounce
  pwm_apply_state -> pwm_apply_might_sleep, dma_buf_map -> iosys_map, vm_flags |= / &= ~ -> vm_flags_set/clear,
  const bin_attribute callbacks and arrays
  thermal_zone_of_device_ops -> thermal_zone_device_ops (callbacks take the zone), *_zone_of_sensor_* -> *_of_zone_*
  psy->of_node -> psy->dev.of_node, power_supply_config.of_node -> .fwnode, usb_types[] -> a BIT() mask
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
    # legacy GPIO calls 6.x removed: include/linux/soc/sprd/unisoc_gpio_compat.h
    (['devm_gpio_request', 'of_get_named_gpio_flags', 'of_get_gpio_flags', 'OF_GPIO_ACTIVE_LOW'],
     'linux/soc/sprd/unisoc_gpio_compat.h'),
]


def _block(s, i):
    """s[i] is '{': the index just past its matching '}'."""
    depth = 0
    for j in range(i, len(s)):
        depth += {'{': 1, '}': -1}.get(s[j], 0)
        if not depth:
            return j + 1
    return len(s)


def move_dai_callbacks(s, done):
    """Move .probe/.remove from snd_soc_dai_driver initialisers into the ops they point at (one callback per ops)."""
    want = {}                   # ops name -> {cb: fn}
    edits = []                  # (start, end) of the .probe/.remove lines to drop
    for m in re.finditer(r'struct snd_soc_dai_driver\s+\w+(?:\[[^\]]*\])?\s*=\s*\{', s):
        end = _block(s, m.end() - 1)
        body = s[m.end():end - 1]
        entries = []
        if '[' not in m.group(0):
            entries = [body]            # a single driver, not an array
        else:
            k = 0
            while (i := body.find('{', k)) >= 0:
                j = _block(body, i)
                entries.append(body[i:j])
                k = j
        base = m.end()
        for e in entries:
            ops = re.search(r'\.ops\s*=\s*&(\w+)', e)
            for cb in ('probe', 'remove'):
                c = re.search(r'^[ \t]*\.%s\s*=\s*(\w+)\s*,[ \t]*\n' % cb, e, re.M)
                if not c:
                    continue
                if not ops:
                    done.append(f'DAI .{cb} = {c.group(1)} without ops: BY HAND')
                    continue
                prev = want.setdefault(ops.group(1), {}).setdefault(cb, c.group(1))
                if prev != c.group(1):
                    done.append(f'DAI ops {ops.group(1)} with two {cb}s: BY HAND')
                    continue
                off = base + body.find(e) + c.start()
                edits.append((off, off + len(c.group(0))))
    if not edits:
        return s
    for a, b in sorted(edits, reverse=True):
        s = s[:a] + s[b:]
    for ops, cbs in want.items():
        m = re.search(r'struct snd_soc_dai_ops\s+%s\s*=\s*\{\n' % ops, s)
        if not m:
            done.append(f'DAI ops {ops} not found: BY HAND')
            continue
        add = ''.join(f'\t.{cb} = {fn},\n' for cb, fn in cbs.items()
                      if not re.search(r'\.%s\s*=' % cb, s[m.end():_block(s, m.end() - 2)]))
        s = s[:m.end()] + add + s[m.end():]
    done.append(f'DAI probe/remove -> ops x{len(edits)}')
    return s


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
    # ASoC's asoc_* helpers are snd_soc_* since 6.8
    sub(r'\basoc_(rtd_to_cpu|rtd_to_codec|substream_to_rtd)\(', r'snd_soc_\1(', 'asoc_* -> snd_soc_*')
    sub(r'\bno_llseek\b', 'noop_llseek', 'no_llseek')
    # struct power_supply lost its of_node (6.x): its device carries it
    sub(r'\bpsy->of_node\b', 'psy->dev.of_node', 'psy->of_node')
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
    # (the struct and its own helpers only: dma_buf_map_attachment() is dma-buf's and keeps its name)
    sub(r'\bdma_buf_map\b', 'iosys_map', 'dma_buf_map')
    sub(r'\bdma_buf_map_(set_vaddr_iomem|set_vaddr|clear|is_null|is_set|is_equal|memcpy_to|incr)\b', r'iosys_map_\1',
        'dma_buf_map_* helper')
    sub(r'\bDMA_BUF_MAP_INIT_VADDR\b', 'IOSYS_MAP_INIT_VADDR', 'DMA_BUF_MAP_INIT_VADDR')
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
    # power supplies (6.x): the config takes a fwnode, and the USB types are a bitmask without a count
    for var in set(re.findall(r'struct power_supply_config\s+(\w+)\b', s)):
        sub(r'\b%s\.of_node\s*=\s*([^;]+);' % var, r'%s.fwnode = of_fwnode_handle(\1);' % var, 'psy config of_node')
    for m in list(re.finditer(r'^static (?:const )?enum power_supply_usb_type (\w+)\[\] = \{([^}]*)\};\n', s, re.M)):
        name, items = m.group(1), [x.strip() for x in m.group(2).split(',') if x.strip()]
        mask = ' | \\\n\t'.join(f'BIT({x})' for x in items)
        s = s.replace(m.group(0), f'#define {name} ( \\\n\t{mask})\n')
        s = re.sub(r'^[ \t]*[\w.>-]*\.?num_usb_types\s*=\s*ARRAY_SIZE\(%s\)\s*[,;][ \t]*\n' % name, '', s, flags=re.M)
        done.append(f'usb_types {name} -> bitmask')
    # thermal OF sensors (6.x): the zone's own ops, callbacks that take the zone, the zone registration
    if 'thermal_zone_of_device_ops' in s:
        sub(r'\bstruct thermal_zone_of_device_ops\b', 'struct thermal_zone_device_ops', 'thermal_zone_of_device_ops')
        for op in ('get_temp', 'set_trips', 'get_trend', 'set_emul_temp'):
            for fn in set(re.findall(r'\.%s\s*=\s*(\w+)' % op, s)):
                m = re.search(r'^(static\s+int\s+%s\s*\()\s*void\s*\*\s*(\w+)\s*,([^)]*)\)\s*\{\n' % fn, s, re.M)
                if m:
                    s = (s[:m.start()] + f'{m.group(1)}struct thermal_zone_device *tzd,{m.group(3)})\n{{\n'
                         f'\tvoid *{m.group(2)} = thermal_zone_device_priv(tzd);\n\n' + s[m.end():])
                    done.append(f'thermal {op} {fn}(tzd)')
    # struct thermal_zone_device is opaque (6.x): its temperature and type through the core
    tzvars = set(re.findall(r'struct thermal_zone_device\s*\*\s*(\w+)', s)) | {'tz', 'tzd'}
    for v in sorted(tzvars):
        sub(r'\s*\|\|\s*!%s->ops->get_temp\b' % re.escape(v), '', 'tz ops check')
        sub(r'\b%s->ops->get_temp\(\s*%s\s*,' % (re.escape(v), re.escape(v)), f'thermal_zone_get_temp({v},', 'tz->ops->get_temp')
        sub(r'\b%s->type\b' % re.escape(v), f'thermal_zone_device_type({v})', 'tz->type')
    sub(r'\bdevm_thermal_zone_of_sensor_register\(', 'devm_thermal_of_zone_register(', 'devm_thermal_zone_of_sensor_register')
    sub(r'\bdevm_thermal_zone_of_sensor_unregister\(', 'devm_thermal_of_zone_unregister(', 'devm_thermal_zone_of_sensor_unregister')
    # (the non-devm pair took a struct device too; 6.x exports only the devm one for that)
    sub(r'\bthermal_zone_of_sensor_register\(', 'devm_thermal_of_zone_register(', 'thermal_zone_of_sensor_register')
    sub(r'\bthermal_zone_of_sensor_unregister\(', 'devm_thermal_of_zone_unregister(', 'thermal_zone_of_sensor_unregister')
    # ASoC (6.5-6.8): a DAI's probe/remove are its ops', and asoc_simple_* is simple_util_*
    s = move_dai_callbacks(s, done)
    sub(r'\basoc_simple_', 'simple_util_', 'asoc_simple_* -> simple_util_*')
    # dapm's idle_bias_off is snd_soc_dapm_set_idle_bias() of the inverse (6.18)
    sub(r'\b(\w+)->idle_bias_off\s*=\s*(?:1|true)\s*;', r'snd_soc_dapm_set_idle_bias(\1, false);', 'idle_bias_off = 1')
    sub(r'\b(\w+)->idle_bias_off\s*=\s*(?:0|false)\s*;', r'snd_soc_dapm_set_idle_bias(\1, true);', 'idle_bias_off = 0')
    # syscore (6.18): the ops are a struct syscore's, registered with register_syscore(), and take its data
    for ops in set(re.findall(r'static\s+struct\s+syscore_ops\s+(\w+)\s*=', s)):
        for fn in set(re.findall(r'\.(?:suspend|resume|shutdown)\s*=\s*(\w+)', s)):
            sub(r'^(static\s+(?:int|void)\s+%s\s*\()\s*void\s*\)' % fn, r'\1void *data)', f'syscore {fn}(data)', re.M)
        sub(r'static\s+struct\s+syscore_ops\s+%s\s*=' % ops, f'static const struct syscore_ops {ops} =', 'syscore_ops const')
        m = re.search(r'static const struct syscore_ops %s = \{.*?\n\};\n' % ops, s, re.S)
        if m:
            s = s[:m.end()] + f'\nstatic struct syscore {ops}_syscore = {{\n\t.ops = &{ops},\n}};\n' + s[m.end():]
        sub(r'\bregister_syscore_ops\(\s*&%s\s*\)' % ops, f'register_syscore(&{ops}_syscore)', 'register_syscore_ops')
        sub(r'\bunregister_syscore_ops\(\s*&%s\s*\)' % ops, f'unregister_syscore(&{ops}_syscore)', 'unregister_syscore_ops')
    # ASoC's clock provider names (6.x): bit/frame master/slave -> provider/consumer
    for old, new in (('CBM_CFM', 'CBP_CFP'), ('CBM_CFS', 'CBP_CFC'), ('CBS_CFM', 'CBC_CFP'), ('CBS_CFS', 'CBC_CFC')):
        sub(r'\bSND_SOC_DAIFMT_%s\b' % old, f'SND_SOC_DAIFMT_{new}', f'DAIFMT_{old}')
    sub(r'\bsnd_soc_of_get_dai_name\(([^,;()]+),([^,;()]+)\)', r'snd_soc_of_get_dai_name(\1,\2, 0)', 'snd_soc_of_get_dai_name')
    sub(r'\bgpio_set_debounce\(\s*([^,;]+?)\s*,', r'gpiod_set_debounce(gpio_to_desc(\1),', 'gpio_set_debounce')
    # snd_soc_card_jack_new() takes no pins (6.x): the _pins variant does
    sub(r'\bsnd_soc_card_jack_new\(([^;]*?),\s*NULL\s*,\s*0\s*\)', r'snd_soc_card_jack_new(\1)', 'snd_soc_card_jack_new(NULL, 0)')
    # dma-buf's exports are in the DMA_BUF namespace (5.16)
    if (re.search(r'\bdma_buf_(attach|detach|export|fd|get|put|map_attachment|unmap_attachment|vmap|vunmap|begin_cpu_access)\b', s)
            and 'MODULE_IMPORT_NS' not in s and re.search(r'^MODULE_LICENSE\(', s, re.M)):
        s = re.sub(r'^(MODULE_LICENSE\([^)]*\);\n)', r'\1MODULE_IMPORT_NS("DMA_BUF");\n', s, count=1, flags=re.M)
        done.append('MODULE_IMPORT_NS(DMA_BUF)')
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
    # a platform driver's remove (a file may have several drivers, and other .remove callbacks)
    for name in dict.fromkeys(re.findall(r'\.remove\s*=\s*(\w+)\s*,', s)):
        if not re.search(r'^static\s+int\s+%s\(struct platform_device \*\w+\)' % name, s, re.M):
            continue
        r = subprocess.run([sys.executable, os.path.join(HERE, 'remove-void.py'), path, name],
                           capture_output=True, text=True)
        done.append(f'remove {name} -> void' if r.returncode == 0 else f'REMOVE BY HAND: {r.stderr.strip()}')
        s = open(path, encoding='utf-8', errors='surrogateescape').read()
    if done:
        print(f'{path}: ' + ', '.join(done))


for arg in sys.argv[1:]:
    files = [arg] if os.path.isfile(arg) else [os.path.join(d, f) for d, _, fs in os.walk(arg) for f in fs
                                               if f.endswith('.c') or f.endswith('.h')]
    for f in sorted(files):
        port(f)

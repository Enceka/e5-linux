#!/usr/bin/env python3
"""A driver's remove callback returns void (platform since 6.11, i2c and mipi-dsi since 6.1, spi since 5.18):
convert a vendor driver's `int` one.

usage: remove-void.py file.c [function]   (default: the .remove = <name> of the file's driver)

The function's `return 0;` statements are dropped (the last one) or become `return;` (early ones); any other
return value stops the conversion, since it would be an error the new signature cannot report.
"""
import re
import sys

path = sys.argv[1]
s = open(path).read()
name = sys.argv[2] if len(sys.argv) > 2 else re.search(r'\.remove\s*=\s*(\w+)\s*,', s).group(1)
DEV = r'struct (?:platform_device|i2c_client|spi_device|mipi_dsi_device) \*\s*\w+'
m = re.search(r'^static\s+int\s+(%s)\((%s)\)\n\{\n' % (name, DEV), s, re.M)
if not m:
    sys.exit(f'{path}: no "static int {name}(struct <device> *)" to convert')
start = m.end()
depth, i = 1, start
while depth:
    depth += {'{': 1, '}': -1}.get(s[i], 0)
    i += 1
body = s[start:i - 1]
others = [r for r in re.findall(r'return\s+([^;]+);', body) if r.strip() != '0']
if others:
    sys.exit(f'{path}: {name} returns {others}: convert by hand')
body = re.sub(r'\n\n\treturn 0;\n$', '\n', body)          # the final return, with the blank line before it
body = re.sub(r'\n\treturn 0;\n$', '\n', body)
body = re.sub(r'return 0;', 'return;', body)               # early returns
s = s[:m.start()] + f'static void {name}({m.group(2)})\n{{\n' + body + s[i - 1:]
# and its forward declaration, if any
s = re.sub(r'^static\s+int\s+(%s\(%s\));' % (name, DEV.replace('\\w+', '\\w*')), r'static void \1;', s, flags=re.M)
open(path, 'w').write(s)
print(f'{path}: {name} returns void')
